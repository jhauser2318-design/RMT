"""The live crypto stream, against a fake Coinbase feed running on this computer.

Run:  python tests/test_stream.py   (from the RMT folder)
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from websockets.asyncio.server import serve  # noqa: E402
from websockets.exceptions import ConnectionClosed  # noqa: E402

from backend import stream  # noqa: E402

received = []  # subscribe messages the fake Coinbase got


async def fake_exchange(ws):
    try:
        await _fake_exchange(ws)
    except ConnectionClosed:  # the test ended
        pass


async def _fake_exchange(ws):
    async for raw in ws:
        msg = json.loads(raw)
        received.append(msg)
        products = msg["product_ids"]
        if "FAKE-USD" in products:
            await ws.send(json.dumps({"type": "error", "message": "Failed to subscribe", "reason": "FAKE-USD is not a valid product"}))
            continue
        await ws.send(json.dumps({"type": "subscriptions", "channels": [{"name": "ticker", "product_ids": products}]}))
        for p in products:
            await ws.send(json.dumps({"type": "ticker", "product_id": p, "price": "110.5", "open_24h": "100",
                                      "high_24h": "111", "low_24h": "99", "volume_24h": "1234", "best_bid": "110.4",
                                      "best_ask": "110.6", "time": "2026-10-24T15:00:00Z"}))
            await ws.send("not json")  # ignored
            await ws.send(json.dumps({"type": "heartbeat"}))  # ignored


class Local(stream.ExchangeFeed):
    name = "Fake Coinbase"

    def __init__(self, url):
        self.url = url


async def until(check, seconds=5):
    for _ in range(int(seconds / 0.05)):
        if check():
            return True
        await asyncio.sleep(0.05)
    return False


async def main():
    async with serve(fake_exchange, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        dead = Local("ws://127.0.0.1:1")  # nothing listens there: the stream moves on to the next feed
        s = stream.CryptoStream(feeds=[dead, Local(f"ws://127.0.0.1:{port}")])
        q = s.listen()
        s.start()

        assert await until(lambda: s.status == "live"), s.info()
        assert s.source == "Fake Coinbase"
        assert received[0]["product_ids"] == stream.BASE and received[0]["channels"] == ["ticker"]
        assert await until(lambda: len(s.prices) == len(stream.BASE))

        btc = s.latest("BTC-USD")
        assert btc["price"] == 110.5 and round(btc["pct"], 2) == 10.5 and round(btc["change"], 2) == 10.5
        assert btc["high"] == 111 and btc["bid"] == 110.4

        # Regular quotes get the live price on top; stocks are left alone.
        q_btc = s.overlay({"symbol": "BTC-USD", "price": 1, "change": 0, "pct": 0, "spark": [1, 2]})
        assert q_btc["price"] == 110.5 and q_btc["streaming"] and q_btc["spark"] == [1, 2]
        assert s.overlay({"symbol": "AAPL", "price": 5})["price"] == 5

        # The window gets status and batched price updates.
        events = []
        assert await until(lambda: (events.extend(q.get_nowait() for _ in range(q.qsize())) or
                                    any(e["type"] == "prices" for e in events)))
        assert any(e["type"] == "status" and e["status"] == "live" for e in events)
        pushed = {p["symbol"] for e in events if e["type"] == "prices" for p in e["items"]}
        assert pushed == set(stream.BASE), pushed

        # A watchlist coin is added to the live connection; one Coinbase doesn't list is dropped.
        s.want(["PEPE-USD", "AAPL", "FAKE-USD", "btc-usd"])
        assert await until(lambda: s.latest("PEPE-USD") is not None)
        assert await until(lambda: "FAKE-USD" not in s.wanted)
        assert "AAPL" not in s.wanted and s.status == "live"
        assert [m["product_ids"] for m in received[1:]] == [["PEPE-USD"], ["FAKE-USD"]]

        await s.stop()
        s.unlisten(q)


def test_advanced_trade_messages():
    feed = stream.AdvancedTradeFeed()
    assert feed.subscribe(["BTC-USD"]) == {"type": "subscribe", "product_ids": ["BTC-USD"], "channel": "ticker"}
    updates, err = feed.parse({"channel": "ticker", "events": [{"type": "update", "tickers": [
        {"type": "ticker", "product_id": "ETH-USD", "price": "3300", "price_percent_chg_24_h": "10",
         "volume_24_h": "5", "low_24_h": "2900", "high_24_h": "3400", "best_bid": "3299", "best_ask": "3301"}]}]})
    assert err is None and updates[0]["symbol"] == "ETH-USD" and round(updates[0]["open"], 2) == 3000.0
    assert feed.parse({"channel": "heartbeats", "events": []}) == ([], None)
    assert feed.parse({"type": "error", "message": "bad"}) == ([], "bad")


def test_feed_unreachable_reports_offline():
    async def run():
        s = stream.CryptoStream(feeds=[Local("ws://127.0.0.1:1")])
        s.start()
        assert await until(lambda: s.status == "offline")
        assert s.error and s.overlay({"symbol": "BTC-USD", "price": 7})["price"] == 7
        await s.stop()
    asyncio.run(run())


if __name__ == "__main__":
    asyncio.run(main())
    print("ok  live stream end to end")
    test_advanced_trade_messages()
    print("ok  advanced trade messages")
    test_feed_unreachable_reports_offline()
    print("ok  offline status")
    print("all stream tests passed")
