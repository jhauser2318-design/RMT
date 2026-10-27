"""Live prices pushed to the window: crypto from Coinbase (this file) and
stocks from Alpaca (alpaca.py, which builds on LiveStream below).

Crypto prices are streamed from Coinbase the moment each trade happens.

Coinbase's public market feed needs no account or key. RMT keeps one
connection open while it runs, and pushes the newest prices to the open
window a few times a second (see /api/stream/crypto in main.py).

Two Coinbase feeds are tried in turn: the Exchange feed, then the Advanced
Trade feed. If neither can be reached, the Crypto ribbon falls back to the
regular (delayed) quotes, and the status says so.
"""
import asyncio
import json
import logging
import threading
import time

from websockets.asyncio.client import connect

from .fetch import _ssl

log = logging.getLogger("rmt.stream")

# Always streamed (the Crypto ribbon). Watchlist coins ending in -USD are added on request.
BASE = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD", "ADA-USD", "AVAX-USD", "LINK-USD"]
FRESH = 60          # seconds a streamed price counts as current
SILENT_LIMIT = 45   # reconnect if the feed goes quiet this long
PUSH_EVERY = 0.35   # seconds between pushes to the window


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Feed:
    """One Coinbase WebSocket API: its address, how to subscribe and how to read a message."""
    name = ""
    url = ""

    def subscribe(self, products: list[str]) -> dict:
        raise NotImplementedError

    def parse(self, msg: dict) -> tuple[list[dict], str | None]:
        """(price updates, error text or None)."""
        raise NotImplementedError


class ExchangeFeed(Feed):
    name = "Coinbase Exchange"
    url = "wss://ws-feed.exchange.coinbase.com"

    def subscribe(self, products):
        return {"type": "subscribe", "product_ids": products, "channels": ["ticker"]}

    def parse(self, msg):
        kind = msg.get("type")
        if kind == "error":
            return [], f"{msg.get('message', 'error')}: {msg.get('reason', '')}".strip(": ")
        if kind != "ticker" or not msg.get("product_id"):
            return [], None
        price, opened = _f(msg.get("price")), _f(msg.get("open_24h"))
        if price is None:
            return [], None
        return [{"symbol": msg["product_id"], "price": price, "open": opened,
                 "high": _f(msg.get("high_24h")), "low": _f(msg.get("low_24h")),
                 "volume": _f(msg.get("volume_24h")), "bid": _f(msg.get("best_bid")), "ask": _f(msg.get("best_ask"))}], None


class AdvancedTradeFeed(Feed):
    name = "Coinbase Advanced Trade"
    url = "wss://advanced-trade-ws.coinbase.com"

    def subscribe(self, products):
        return {"type": "subscribe", "product_ids": products, "channel": "ticker"}

    def parse(self, msg):
        if msg.get("type") == "error":
            return [], msg.get("message", "error")
        if msg.get("channel") != "ticker":
            return [], None
        out = []
        for event in msg.get("events") or []:
            for t in event.get("tickers") or []:
                price, pct = _f(t.get("price")), _f(t.get("price_percent_chg_24_h"))
                if price is None or not t.get("product_id"):
                    continue
                opened = price / (1 + pct / 100) if pct is not None and pct > -100 else None
                out.append({"symbol": t["product_id"], "price": price, "open": opened,
                            "high": _f(t.get("high_24_h")), "low": _f(t.get("low_24_h")),
                            "volume": _f(t.get("volume_24_h")), "bid": _f(t.get("best_bid")), "ask": _f(t.get("best_ask"))})
        return out, None


class LiveStream:
    """Prices pushed from a live connection: keeps the newest price per symbol,
    and hands batches of changes to every open window a few times a second."""
    kind = ""  # "crypto" or "stocks": tells the window which stream an event is from

    def __init__(self):
        self.prices: dict[str, dict] = {}
        self.status = "off"         # off → connecting → live (or offline / error)
        self.source = ""
        self.error = ""
        self.since = 0.0
        self._lock = threading.Lock()
        self._dirty: set[str] = set()
        self._listeners: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task] = []

    # ---------- used by the rest of RMT (any thread) ----------

    def latest(self, symbol: str) -> dict | None:
        with self._lock:
            p = self.prices.get(symbol)
        return p if p and time.time() - p["time"] < self.fresh_for(symbol) else None

    def fresh_for(self, symbol: str) -> float:
        return FRESH

    def overlay(self, quote: dict) -> dict:
        """A quote with the streamed price in place of the regular (delayed) one, when there is one."""
        p = self.latest(quote["symbol"])
        if not p:
            return quote
        return {**quote, "price": p["price"], "change": p["change"], "pct": p["pct"], "streaming": True}

    def info(self) -> dict:
        return {"stream": self.kind, "status": self.status, "source": self.source, "error": self.error,
                "since": self.since, "symbols": len(self.prices)}

    # ---------- the window's live connection ----------

    def listen(self, q: asyncio.Queue | None = None) -> asyncio.Queue:
        q = q or asyncio.Queue(maxsize=100)
        self._listeners.add(q)
        return q

    def unlisten(self, q: asyncio.Queue) -> None:
        self._listeners.discard(q)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [p for s, p in self.prices.items() if time.time() - p["time"] < self.fresh_for(s)]

    def _broadcast(self, event: dict) -> None:
        event = {**event, "stream": self.kind}
        for q in list(self._listeners):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # a stalled window: skip it, it gets the next batch
                pass

    def _set_status(self, status: str, source: str = "", error: str = "") -> None:
        self.status, self.source, self.error, self.since = status, source, error, time.time()
        self._broadcast({"type": "status", **self.info()})

    # ---------- the connection itself (runs on the server's event loop) ----------

    def start(self) -> None:
        if self._tasks:
            return
        self._loop = asyncio.get_running_loop()
        self._tasks = [asyncio.create_task(self._run()), asyncio.create_task(self._pusher())]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self._tasks = []

    async def _run(self) -> None:
        raise NotImplementedError

    def _apply(self, updates: list[dict]) -> None:
        """updates: {"symbol", "price", "open" (what the % change is measured from), ...}"""
        now = time.time()
        with self._lock:
            for u in updates:
                opened = u.pop("open")
                change = u["price"] - opened if opened else 0.0
                self.prices[u["symbol"]] = {**u, "change": change, "pct": (change / opened * 100) if opened else 0.0,
                                            "time": now}
                self._dirty.add(u["symbol"])

    async def _pusher(self) -> None:
        while True:
            await asyncio.sleep(PUSH_EVERY)
            if not self._dirty:
                continue
            with self._lock:
                items = [self.prices[s] for s in self._dirty if s in self.prices]
                self._dirty.clear()
            self._broadcast({"type": "prices", "items": items})


class CryptoStream(LiveStream):
    kind = "crypto"

    def __init__(self, feeds=None):
        super().__init__()
        self.feeds = feeds or [ExchangeFeed(), AdvancedTradeFeed()]
        self.wanted: list[str] = list(BASE)
        self._ws = None
        self._feed: Feed | None = None

    def want(self, symbols) -> None:
        """Also stream these coins (e.g. from the watchlist). Non-crypto symbols are ignored."""
        new = [s for s in (x.upper() for x in symbols) if s.endswith("-USD") and s not in self.wanted]
        if not new:
            return
        self.wanted += new
        if self._loop and self._ws:
            self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._subscribe(new)))

    async def _subscribe(self, products: list[str]) -> None:
        if not (self._ws and self._feed):
            return
        try:
            for p in products:  # one at a time: an unknown coin can't spoil the rest
                await self._ws.send(json.dumps(self._feed.subscribe([p])))
        except Exception as e:  # noqa: BLE001 (the reconnect loop takes care of it)
            log.info("Subscribing to %s failed: %s", products, e)

    async def _session(self, feed: Feed) -> None:
        secure = {"ssl": _ssl()} if feed.url.startswith("wss://") else {}
        async with connect(feed.url, **secure, open_timeout=10, ping_interval=20, ping_timeout=20,
                           max_size=2 ** 22, user_agent_header="RMT/0.2") as ws:
            self._ws, self._feed = ws, feed
            await ws.send(json.dumps(feed.subscribe(list(BASE))))
            await self._subscribe([s for s in self.wanted if s not in BASE])
            got_any = False
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=SILENT_LIMIT)
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                updates, err = feed.parse(msg)
                if err:
                    log.info("%s: %s", feed.name, err)
                    bad = [s for s in self.wanted if s in err and s not in BASE]
                    if bad:  # a watchlist coin Coinbase doesn't list: stop asking for it
                        self.wanted = [s for s in self.wanted if s not in bad]
                    elif not got_any:
                        raise ConnectionError(err)
                if updates:
                    if not got_any:
                        got_any = True
                        self._set_status("live", feed.name)
                    self._apply(updates)

    async def _run(self) -> None:
        delay = 2
        while True:
            for feed in self.feeds:
                self._set_status("connecting", feed.name)
                started = time.time()
                try:
                    await self._session(feed)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 (try the next feed, then wait and retry)
                    log.info("%s stream ended: %r", feed.name, e)
                    self.error = str(e) or e.__class__.__name__
                finally:
                    self._ws = self._feed = None
                if time.time() - started > 60:  # it was working for a while: reconnect quickly
                    delay = 2
                    break
            self._set_status("offline", "", self.error)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120)


crypto = CryptoStream()
