"""Real-time US stock prices from Alpaca's free market data (the IEX exchange).

With ALPACA_KEY_ID and ALPACA_SECRET_KEY in .env (paste them in ⚙ → Live data):
  - up to 30 stocks stream live, the moment each trade happens: your
    watchlist first, then SPY and QQQ, then the Day-Trader Favorites and
    Mega Caps;
  - every other stock on the ribbons gets its real-time price from a quick
    lookup (one request for all of them; the free plan allows 200 a minute).
% change is measured from the previous day's close, like the rest of RMT.

Free-plan limits (Alpaca's docs): one live connection per key, 30 symbols.
Prices come from IEX only: the price is real, but quiet stocks trade there less often.
Outside market hours nothing trades on IEX, so prices sit still until the next open.
"""
import asyncio
import json
import logging
import os
import re
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor

from websockets.asyncio.client import connect

from .fetch import _ssl, cached, get_json
from .stream import LiveStream

log = logging.getLogger("rmt.alpaca")

DATA = "https://data.alpaca.markets/v2"
STREAM_URL = "wss://stream.data.alpaca.markets/v2/iex"
CLOCKS = ["https://paper-api.alpaca.markets/v2/clock", "https://api.alpaca.markets/v2/clock"]
MAX_STREAM = 30          # free plan
STOCK = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")  # AAPL, BRK-B; not ^GSPC, ES=F, BTC-USD, EURUSD=X


class AlpacaError(Exception):
    pass


def keys() -> tuple[str, str]:
    return os.getenv("ALPACA_KEY_ID", "").strip(), os.getenv("ALPACA_SECRET_KEY", "").strip()


def configured() -> bool:
    return all(keys())


def is_stock(symbol: str) -> bool:
    return bool(STOCK.match(symbol)) and not symbol.endswith("-USD")


def to_alpaca(symbol: str) -> str:   # Yahoo's BRK-B is Alpaca's BRK.B
    return symbol.replace("-", ".")


def from_alpaca(symbol: str) -> str:
    return symbol.replace(".", "-")


def _headers() -> dict:
    key, secret = keys()
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _explain(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (401, 403):
            return "Alpaca didn't accept the keys. Check that you copied both the Key ID and the Secret Key."
        if e.code == 429:
            return "Too many requests to Alpaca this minute; slowing down."
        return f"Alpaca answered with an error ({e.code})."
    return f"Couldn't reach Alpaca ({getattr(e, 'reason', e)})."


_bad: set[str] = set()  # symbols Alpaca doesn't know (e.g. foreign listings): skipped from then on


def _snap_batch(symbols: list[str]) -> dict:
    data = get_json(f"{DATA}/stocks/snapshots", {"symbols": ",".join(to_alpaca(s) for s in symbols), "feed": "iex"},
                    headers=_headers(), timeout=8)
    out = {}
    for sym, snap in (data or {}).items():
        if not snap:
            continue
        trade = snap.get("latestTrade") or {}
        prev = (snap.get("prevDailyBar") or {}).get("c")
        price = trade.get("p") or (snap.get("dailyBar") or {}).get("c")
        if price is None:
            continue
        out[from_alpaca(sym)] = {"price": price, "prev": prev, "at": trade.get("t", "")}
    return out


def snapshots(symbols: list[str]) -> dict:
    """{symbol: {"price", "prev", "at"}} for the stocks among symbols. Raises AlpacaError."""
    want = sorted({s for s in symbols if is_stock(s) and s not in _bad})
    if not want or not configured():
        return {}

    def load():
        try:
            return _snap_batch(want)
        except urllib.error.HTTPError as e:
            if e.code not in (400, 404, 422):
                raise AlpacaError(_explain(e)) from e
        # One unknown symbol fails the whole batch: look them up one by one and remember the bad ones.
        out = {}

        def one(sym):
            try:
                return _snap_batch([sym])
            except urllib.error.HTTPError as e:
                if e.code in (400, 404, 422):
                    _bad.add(sym)
                    return {}
                raise
        with ThreadPoolExecutor(max_workers=6) as pool:
            for part in pool.map(one, want):
                out.update(part)
        return out
    try:
        return cached(f"alpaca:{','.join(want)}", 5, load)
    except AlpacaError:
        raise
    except Exception as e:  # noqa: BLE001
        raise AlpacaError(_explain(e)) from e


def market_open() -> bool | None:
    """Whether the US stock market is open right now (None if unknown)."""
    def load():
        for url in CLOCKS:  # paper keys answer on the first, live-account keys on the second
            try:
                return bool(get_json(url, headers=_headers(), timeout=6).get("is_open"))
            except Exception:  # noqa: BLE001
                continue
        return None
    if not configured():
        return None
    return cached("alpaca:clock", 120, load)


def test_keys() -> tuple[bool, str]:
    """Try the keys with one lookup. (ok, message for the person)"""
    if not configured():
        return False, "Paste both the API Key ID and the Secret Key."
    try:
        got = _snap_batch(["SPY"])
    except Exception as e:  # noqa: BLE001
        return False, _explain(e)
    if "SPY" not in got:
        return False, "The keys work, but Alpaca returned no price for SPY. Try again in a minute."
    return True, f"✅ Keys work. SPY is ${got['SPY']['price']:,.2f} right now."


class StockStream(LiveStream):
    kind = "stocks"

    def __init__(self, url: str = STREAM_URL):
        super().__init__()
        self.url = url
        self.wanted: list[str] = []      # in priority order; the first 30 stream
        self.focus: str | None = None    # the stock whose page is open
        self.prev: dict[str, float] = {}  # previous close, for the % change
        self.market = None
        self._ws = None
        self._streaming: list[str] = []
        self._authed = False
        self._keys_changed: asyncio.Event | None = None  # made on the server's event loop

    def fresh_for(self, symbol: str) -> float:
        # A streamed price stays current until the next trade; quiet stocks can go minutes
        # without one, and after the close it's simply the last price.
        return 6 * 3600

    def set_focus(self, symbol: str | None) -> None:
        """The stock whose page is open: it streams live first, ahead of everything else."""
        self.focus = symbol if symbol and is_stock(symbol) else None
        self.set_wanted([s for s in self.wanted if s != self.focus])

    def set_wanted(self, symbols: list[str]) -> None:
        """Which stocks to stream, most important first (only the first 30 are used)."""
        symbols = [self.focus, *symbols] if self.focus else symbols
        wanted = list(dict.fromkeys(s for s in symbols if is_stock(s) and s not in _bad))
        if wanted[:MAX_STREAM] == self.wanted[:MAX_STREAM]:
            self.wanted = wanted
            return
        self.wanted = wanted
        if self._loop and self._ws:
            self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._resubscribe()))

    def keys_changed(self) -> None:
        """New keys were saved: reconnect with them."""
        if self._loop and self._keys_changed:
            self._loop.call_soon_threadsafe(self._keys_changed.set)

    def info(self) -> dict:
        return {**super().info(), "streaming": len(self._streaming), "market_open": self.market,
                "configured": configured()}

    async def _resubscribe(self) -> None:
        if not self._ws:
            return
        target = self.wanted[:MAX_STREAM]
        drop = [s for s in self._streaming if s not in target]
        add = [s for s in target if s not in self._streaming]
        try:
            if drop:
                await self._ws.send(json.dumps({"action": "unsubscribe", "trades": [to_alpaca(s) for s in drop]}))
            if add:
                await self._load_prev(add)
                await self._ws.send(json.dumps({"action": "subscribe", "trades": [to_alpaca(s) for s in add]}))
        except Exception as e:  # noqa: BLE001 (the reconnect loop takes care of it)
            log.info("Changing Alpaca subscriptions failed: %s", e)

    async def _load_prev(self, symbols: list[str]) -> None:
        """Yesterday's close for each stock (and today's price, so the ribbon is right before the first trade)."""
        try:
            snaps = await asyncio.to_thread(snapshots, symbols)
        except AlpacaError as e:
            log.info("Alpaca lookup failed: %s", e)
            return
        updates = []
        for sym, sn in snaps.items():
            if sn["prev"]:
                self.prev[sym] = sn["prev"]
            if sym not in self.prices:
                updates.append({"symbol": sym, "price": sn["price"], "open": sn["prev"]})
        if updates:
            self._apply(updates)
        self.market = await asyncio.to_thread(market_open)

    def _handle(self, msgs) -> None:
        """One message from Alpaca (always a list of events)."""
        trades = []
        for m in msgs if isinstance(msgs, list) else [msgs]:
            kind = m.get("T")
            if kind == "t" and m.get("S") and m.get("p") is not None:
                sym = from_alpaca(m["S"])
                trades.append({"symbol": sym, "price": float(m["p"]), "open": self.prev.get(sym), "size": m.get("s")})
            elif kind == "success" and m.get("msg") == "authenticated":
                self._authed = True
            elif kind == "subscription":
                self._streaming = [from_alpaca(s) for s in m.get("trades") or []]
                self._set_status("live", "Alpaca (IEX)")
            elif kind == "error":
                raise AlpacaStreamError(m.get("code"), m.get("msg", "error"))
        if trades:
            self._apply(trades)

    async def _session(self) -> None:
        key, secret = keys()
        async with connect(self.url, **({"ssl": _ssl()} if self.url.startswith("wss://") else {}),
                           open_timeout=10, ping_interval=20, ping_timeout=20, user_agent_header="RMT/0.3") as ws:
            self._authed = False
            await ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
            while not self._authed:
                self._handle(json.loads(await asyncio.wait_for(ws.recv(), timeout=15)))
            self._ws = ws
            target = self.wanted[:MAX_STREAM]
            await self._load_prev(target)
            await ws.send(json.dumps({"action": "subscribe", "trades": [to_alpaca(s) for s in target]}))
            refreshed = time.time()
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except asyncio.TimeoutError:  # quiet (e.g. market closed): fine, keep the connection
                    raw = None
                if raw:
                    self._handle(json.loads(raw))
                if time.time() - refreshed > 15 * 60:  # a new trading day brings new closes
                    refreshed = time.time()
                    self.prev.clear()
                    await self._load_prev(self.wanted[:MAX_STREAM])

    async def _run(self) -> None:
        self._keys_changed = asyncio.Event()
        delay = 5
        while True:
            self._keys_changed.clear()
            if not configured():
                self._set_status("off", "", "")
                await self._keys_changed.wait()
                continue
            self._set_status("connecting", "Alpaca (IEX)")
            session = asyncio.create_task(self._session())
            changed = asyncio.create_task(self._keys_changed.wait())
            try:
                done, _ = await asyncio.wait({session, changed}, return_when=asyncio.FIRST_COMPLETED)
            finally:  # also when RMT shuts down: never leave the connection running on its own
                for t in (session, changed):
                    if not t.done():
                        t.cancel()
            self._ws, self._streaming = None, []
            if changed in done:  # new keys: start over right away
                self.prices.clear()
                delay = 5
                continue
            err = session.exception() if not session.cancelled() else None
            wait = delay
            if isinstance(err, AlpacaStreamError):
                if err.code in (401, 402, 403):
                    self._set_status("error", "Alpaca", "Alpaca didn't accept the keys. Paste them again in ⚙ → Live data.")
                    await self._keys_changed.wait()  # nothing to do until new keys arrive
                    continue
                if err.code == 406:  # another connection with these keys is still open (or closing)
                    wait = 90
                    err = "Another program is using these Alpaca keys' one live connection. Retrying in 90 seconds."
                elif err.code == 405:
                    err = "Alpaca's 30-symbol limit was reached."
            self._set_status("offline", "Alpaca", str(err or "Disconnected"))
            try:
                await asyncio.wait_for(self._keys_changed.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, 120)


class AlpacaStreamError(Exception):
    def __init__(self, code, msg):
        super().__init__(f"{msg} ({code})")
        self.code = code


stocks = StockStream()
