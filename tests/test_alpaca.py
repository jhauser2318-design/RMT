"""Real-time stocks from Alpaca, against a fake Alpaca running on this computer.

Run:  python tests/test_alpaca.py   (from the RMT folder)
"""
import asyncio
import io
import json
import os
import sys
import tempfile
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["RMT_DEMO"] = "0"

from websockets.asyncio.server import serve  # noqa: E402
from websockets.exceptions import ConnectionClosed  # noqa: E402

from backend import alpaca, fetch, markets, settings  # noqa: E402

PREV = {"AAPL": 200.0, "SPY": 600.0, "BRK.B": 450.0, "TSLA": 300.0}
NOW = {"AAPL": 210.0, "SPY": 606.0, "BRK.B": 459.0, "TSLA": 297.0}
messages = []  # what the fake Alpaca stream received


def fake_get_json(url, params=None, timeout=10, headers=None):
    assert headers["APCA-API-KEY-ID"] and headers["APCA-API-SECRET-KEY"]
    if headers["APCA-API-KEY-ID"] != "PKGOOD":
        raise urllib.error.HTTPError(url, 401, "unauthorized", {}, io.BytesIO(b""))
    if url.endswith("/clock"):
        return {"is_open": True}
    syms = params["symbols"].split(",")
    assert params["feed"] == "iex"
    if "ZZZZ" in syms:  # Alpaca fails the whole batch for one unknown symbol
        raise urllib.error.HTTPError(url, 400, "invalid symbol", {}, io.BytesIO(b""))
    return {s: {"latestTrade": {"p": NOW[s], "t": "2026-10-27T15:00:00Z"}, "prevDailyBar": {"c": PREV[s]},
                "dailyBar": {"c": NOW[s]}} for s in syms if s in NOW}


async def fake_alpaca(ws):
    try:
        await ws.send(json.dumps([{"T": "success", "msg": "connected"}]))
        async for raw in ws:
            msg = json.loads(raw)
            messages.append(msg)
            if msg["action"] == "auth":
                if msg["key"] == "PKGOOD" and msg["secret"] == "s3cret":
                    await ws.send(json.dumps([{"T": "success", "msg": "authenticated"}]))
                else:
                    await ws.send(json.dumps([{"T": "error", "code": 402, "msg": "auth failed"}]))
            elif msg["action"] == "subscribe":
                await ws.send(json.dumps([{"T": "subscription", "trades": msg["trades"], "quotes": [], "bars": []}]))
                await ws.send(json.dumps([{"T": "t", "S": s, "p": NOW.get(s, 1) + 1, "s": 10, "t": "2026-10-27T15:00:01Z"}
                                          for s in msg["trades"]]))
    except ConnectionClosed:
        pass


async def until(check, seconds=5):
    for _ in range(int(seconds / 0.05)):
        if check():
            return True
        await asyncio.sleep(0.05)
    return False


def use_keys(key, secret):
    os.environ["ALPACA_KEY_ID"], os.environ["ALPACA_SECRET_KEY"] = key, secret
    fetch._cache.clear()


async def stream_test():
    alpaca.get_json = fake_get_json
    async with serve(fake_alpaca, "127.0.0.1", 0) as server:
        s = alpaca.StockStream(url=f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")

        use_keys("", "")
        s.start()
        assert await until(lambda: s.status == "off")  # no keys: waits quietly

        use_keys("PKBAD", "nope")
        s.keys_changed()
        assert await until(lambda: s.status == "error"), s.info()
        assert "didn't accept the keys" in s.error

        use_keys("PKGOOD", "s3cret")
        s.set_wanted(["AAPL", "^GSPC", "BTC-USD", "BRK-B", "SPY", "AAPL"])  # only real stocks, no repeats
        s.keys_changed()
        assert await until(lambda: s.status == "live"), s.info()
        sub = next(m for m in messages if m["action"] == "subscribe")
        assert sub["trades"] == ["AAPL", "BRK.B", "SPY"], sub  # Alpaca writes BRK-B as BRK.B
        assert await until(lambda: (s.latest("AAPL") or {}).get("price") == 211.0)
        aapl = s.latest("AAPL")
        assert round(aapl["pct"], 2) == 5.5 and aapl["change"] == 11.0  # from yesterday's close (200)
        assert s.latest("BRK-B")["price"] == 460.0
        assert s.info()["streaming"] == 3 and s.info()["market_open"] is True

        q = s.overlay({"symbol": "AAPL", "price": 1, "change": 0, "pct": 0})
        assert q["streaming"] and q["price"] == 211.0

        # Change what streams: drop BRK-B and SPY, add TSLA.
        s.set_wanted(["AAPL", "TSLA"])
        assert await until(lambda: any(m.get("action") == "unsubscribe" for m in messages))
        unsub = next(m for m in messages if m["action"] == "unsubscribe")
        assert sorted(unsub["trades"]) == ["BRK.B", "SPY"]
        assert await until(lambda: s.latest("TSLA") is not None)
        assert round(s.latest("TSLA")["pct"], 2) == round((298 - 300) / 300 * 100, 2)

        # Only the first 30 stream (free plan).
        many = [f"S{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(40)]
        s.set_wanted(many)
        assert await until(lambda: len([m for m in messages if m["action"] == "subscribe"]) >= 3)
        last_sub = [m for m in messages if m["action"] == "subscribe"][-1]
        assert len(set(last_sub["trades"]) | {"AAPL", "TSLA"}) <= 32 and "SBO" not in last_sub["trades"]
        await s.stop()


def test_snapshots_and_ribbon_prices():
    alpaca.get_json = fake_get_json
    use_keys("PKGOOD", "s3cret")
    alpaca._bad.clear()
    got = alpaca.snapshots(["AAPL", "BRK-B", "^GSPC", "BTC-USD", "ZZZZ"])
    assert set(got) == {"AAPL", "BRK-B"} and got["AAPL"] == {"price": 210.0, "prev": 200.0, "at": "2026-10-27T15:00:00Z"}
    assert "ZZZZ" in alpaca._bad  # remembered, so the next lookup is one request again

    # The ribbons: Yahoo's delayed AAPL price is replaced by Alpaca's real-time one.
    yahoo = {"chart": {"result": [{"meta": {"regularMarketPrice": 190.0, "chartPreviousClose": 200.0},
                                   "indicators": {"quote": [{"close": [199, 190]}]}}]}}
    markets.get_json = lambda url, params=None, timeout=10: yahoo
    found, live = markets.quotes(["AAPL", "^GSPC"])
    by = {q["symbol"]: q for q in found}
    assert live and by["AAPL"]["price"] == 210.0 and by["AAPL"]["realtime"] and round(by["AAPL"]["pct"], 1) == 5.0
    assert by["AAPL"]["spark"] == [199, 190]  # the mini chart still comes from Yahoo
    assert by["^GSPC"]["price"] == 190.0 and not by["^GSPC"].get("realtime")

    # Yahoo down: only the real prices are shown (no sample numbers next to real ones).
    def offline(*a, **k):
        raise OSError("offline")
    markets.get_json = offline
    fetch._cache.clear()
    found, live = markets.quotes(["AAPL", "^GSPC"])
    assert live and [q["symbol"] for q in found] == ["AAPL"]

    # No keys: Alpaca isn't asked at all.
    use_keys("", "")
    assert alpaca.snapshots(["AAPL"]) == {}


def test_voo_is_on_the_etf_ribbon_and_streams():
    etfs = next(r for r in markets.RIBBONS if r["id"] == "etfs")
    assert ("VOO", "") in etfs["symbols"]
    use_keys("", "")
    markets.get_json = lambda url, params=None, timeout=10: (_ for _ in ()).throw(OSError("offline"))
    real = alpaca.stocks.set_wanted
    seen = []
    alpaca.stocks.set_wanted = seen.extend
    try:
        markets.ribbons(["TSLA"])
    finally:
        alpaca.stocks.set_wanted = real
    assert seen[:4] == ["TSLA", "SPY", "VOO", "QQQ"]  # watchlist, then the index ETFs: inside the 30 that stream


def test_key_check():
    alpaca.get_json = fake_get_json
    use_keys("PKGOOD", "s3cret")
    ok, msg = alpaca.test_keys()
    assert ok and "SPY is $606.00" in msg
    use_keys("PKBAD", "x")
    ok, msg = alpaca.test_keys()
    assert not ok and "didn't accept the keys" in msg
    use_keys("", "")
    assert alpaca.test_keys()[0] is False


def test_saving_keys_to_env():
    with tempfile.TemporaryDirectory() as tmp:
        real = settings.ENV, settings.ROOT
        settings.ENV, settings.ROOT = Path(tmp) / ".env", Path(tmp)
        try:
            settings.ENV.write_text("ANTHROPIC_API_KEY=sk-ant-mine\nALPACA_KEY_ID=\n")
            settings.save({"ALPACA_KEY_ID": " PKNEW ", "ALPACA_SECRET_KEY": "abc/123+=", "GITHUB_TOKEN": "hacked"})  # not editable from the app
            text = settings.ENV.read_text()
            assert text == "ANTHROPIC_API_KEY=sk-ant-mine\nALPACA_KEY_ID=PKNEW\nALPACA_SECRET_KEY=abc/123+=\n", text
            assert os.environ["ALPACA_KEY_ID"] == "PKNEW"
            try:
                settings.save({"ALPACA_KEY_ID": "PK\nEVIL=1"})
            except ValueError:
                pass
            else:
                raise AssertionError("a key with a line break must be refused")
        finally:
            settings.ENV, settings.ROOT = real
            use_keys("", "")


def test_only_rmt_window_can_change_settings():
    from backend.main import app
    from starlette.requests import Request

    async def run(method, headers):
        scope = {"type": "http", "method": method, "path": "/api/settings/alpaca", "headers": headers,
                 "query_string": b"", "server": ("127.0.0.1", 8050), "client": ("127.0.0.1", 1), "scheme": "http"}
        mw = next(m for m in app.user_middleware if "only_rmt" in getattr(m.kwargs.get("dispatch"), "__name__", ""))
        called = []

        async def nxt(req):
            called.append(True)
            return "ok"
        res = await mw.kwargs["dispatch"](Request(scope), nxt)
        return res, called
    res, called = asyncio.run(run("POST", []))
    assert res.status_code == 403 and not called
    res, called = asyncio.run(run("DELETE", []))
    assert res.status_code == 403 and not called
    res, called = asyncio.run(run("POST", [(b"x-rmt", b"1")]))
    assert res == "ok" and called
    res, called = asyncio.run(run("GET", []))
    assert res == "ok"


if __name__ == "__main__":
    asyncio.run(stream_test())
    print("ok  live stock stream end to end")
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("all Alpaca tests passed")
