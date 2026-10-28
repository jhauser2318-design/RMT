"""More live stocks from Finnhub, against a fake Finnhub running on this computer.

Run:  python tests/test_finnhub.py   (from the RMT folder)
"""
import asyncio
import io
import json
import os
import sys
import urllib.error
from http import HTTPStatus
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["RMT_DEMO"] = "0"

from websockets.asyncio.server import serve  # noqa: E402
from websockets.exceptions import ConnectionClosed  # noqa: E402

from backend import alpaca, fetch, finnhub, markets  # noqa: E402

got = []  # messages the fake Finnhub received


def use_keys(finn="", alp=("", "")):
    os.environ["FINNHUB_API_KEY"] = finn
    os.environ["ALPACA_KEY_ID"], os.environ["ALPACA_SECRET_KEY"] = alp
    fetch._cache.clear()


def reject_bad_token(connection, request):
    if "token=GOODKEY" not in request.path:
        return connection.respond(HTTPStatus.UNAUTHORIZED, "Invalid API key\n")
    return None


async def fake_finnhub(ws):
    try:
        await ws.send(json.dumps({"type": "ping"}))
        async for raw in ws:
            msg = json.loads(raw)
            got.append(msg)
            if msg["type"] == "subscribe":
                s = msg["symbol"]
                await ws.send(json.dumps({"type": "trade", "data": [
                    {"s": s, "p": 100.0, "t": 1, "v": 5}, {"s": s, "p": 101.5, "t": 2, "v": 3}]}))  # last one wins
    except ConnectionClosed:
        pass


async def until(check, seconds=5):
    for _ in range(int(seconds / 0.05)):
        if check():
            return True
        await asyncio.sleep(0.05)
    return False


def fake_quote(url, params=None, timeout=10, headers=None):
    if params.get("token") != "GOODKEY":
        raise urllib.error.HTTPError(url, 401, "no", {}, io.BytesIO(b""))
    return {"c": 606.0, "pc": {"SPY": 600.0, "BRK.B": 450.0}.get(params["symbol"], 100.0)}


async def stream_test():
    finnhub.get_json = fake_quote
    async with serve(fake_finnhub, "127.0.0.1", 0, process_request=reject_bad_token) as server:
        s = finnhub.FinnhubStream(url=f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}")
        use_keys("")
        s.start()
        assert await until(lambda: s.status == "off")

        use_keys("BADKEY")
        s.keys_changed()
        assert await until(lambda: s.status == "error"), s.info()
        assert "didn't accept the key" in s.error

        use_keys("GOODKEY")
        s.learn_prev({"AMD": 101.5 / 1.015})  # from the regular quotes
        s.set_wanted(["AMD", "BRK-B", "^GSPC", "BTC-USD", "AMD"])
        s.keys_changed()
        assert await until(lambda: s.status == "live"), s.info()
        assert await until(lambda: s.latest("AMD") is not None and s.latest("BRK-B") is not None)
        assert [m["symbol"] for m in got if m["type"] == "subscribe"] == ["AMD", "BRK.B"]  # stocks only, Finnhub's spelling
        assert s.latest("AMD")["price"] == 101.5 and round(s.latest("AMD")["pct"], 2) == 1.5
        assert await until(lambda: s.prev.get("BRK-B") == 450.0)  # missing close asked from Finnhub's quote endpoint

        s.set_wanted(["AMD", "TSLA"])
        assert await until(lambda: any(m == {"type": "unsubscribe", "symbol": "BRK.B"} for m in got))
        assert await until(lambda: s.latest("TSLA") is not None)
        assert s.info()["streaming"] == 2
        await s.stop()


def test_alpaca_takes_30_finnhub_the_next_50():
    order = [f"S{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(100)]
    use_keys("GOODKEY", ("PK", "secret"))
    alpaca.stocks.focus = None
    markets.assign_streams(order)
    assert alpaca.stocks.wanted[:30] == order[:30]
    assert finnhub.stocks.wanted == order[30:80]  # no overlap; 80 live in all

    markets.focus("ZZZ")  # a stock page opens: it goes first, in Alpaca's 30
    assert alpaca.stocks.wanted[0] == "ZZZ" and "ZZZ" not in finnhub.stocks.wanted
    assert finnhub.stocks.wanted[0] == order[29]  # the one it bumped moves over to Finnhub
    markets.focus(None)

    use_keys("GOODKEY", ("", ""))  # no Alpaca keys: Finnhub streams the first 50 itself
    markets.assign_streams(order)
    assert finnhub.stocks.wanted == order[:50]


def test_key_check_and_overlay():
    finnhub.get_json = fake_quote
    use_keys("GOODKEY")
    ok, msg = finnhub.test_key()
    assert ok and "SPY is $606.00" in msg
    use_keys("BAD")
    assert finnhub.test_key() == (False, "Finnhub didn't accept the key. Copy it again from your Finnhub dashboard.")
    use_keys("")
    assert finnhub.test_key()[0] is False


if __name__ == "__main__":
    asyncio.run(stream_test())
    print("ok  live Finnhub stream end to end")
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("all Finnhub tests passed")
