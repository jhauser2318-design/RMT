"""More live-streamed stocks from Finnhub's free plan (up to 50 at once).

With FINNHUB_API_KEY in .env (paste it in ⚙ → Live data), Finnhub streams the
stocks Alpaca's 30 don't cover, so every stock on the ribbons can tick live.
Without Alpaca keys, Finnhub streams the first 50 by itself.

% change is measured from the previous close: RMT learns it from the regular
quotes (Yahoo) and, for anything missing, asks Finnhub's quote endpoint,
gently (the free plan allows about 60 requests a minute).
"""
import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.parse

from websockets.asyncio.client import connect

from .alpaca import from_alpaca, is_stock, to_alpaca
from .fetch import _ssl, cached, get_json
from .stream import LiveStream

log = logging.getLogger("rmt.finnhub")

STREAM_URL = "wss://ws.finnhub.io"
QUOTE = "https://finnhub.io/api/v1/quote"
MAX_STREAM = 50  # free plan


def key() -> str:
    return os.getenv("FINNHUB_API_KEY", "").strip()


def configured() -> bool:
    return bool(key())


def _explain(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        if e.code in (401, 403):
            return "Finnhub didn't accept the key. Copy it again from your Finnhub dashboard."
        if e.code == 429:
            return "Too many requests to Finnhub this minute; slowing down."
        return f"Finnhub answered with an error ({e.code})."
    return f"Couldn't reach Finnhub ({getattr(e, 'reason', e)})."


def quote(symbol: str) -> dict:
    """{"c": price, "pc": previous close, ...} from Finnhub's quote endpoint."""
    return get_json(QUOTE, {"symbol": to_alpaca(symbol), "token": key()}, timeout=8)


def test_key() -> tuple[bool, str]:
    if not configured():
        return False, "Paste your Finnhub API key."
    try:
        q = quote("SPY")
    except Exception as e:  # noqa: BLE001
        return False, _explain(e)
    if not q.get("c"):
        return False, "The key works, but Finnhub returned no price for SPY. Try again in a minute."
    return True, f"✅ Key works. SPY is ${q['c']:,.2f} right now."


class FinnhubStream(LiveStream):
    kind = "finnhub"

    def __init__(self, url: str = STREAM_URL):
        super().__init__()
        self.url = url
        self.wanted: list[str] = []
        self.prev: dict[str, float] = {}
        self._ws = None
        self._streaming: list[str] = []
        self._keys_changed: asyncio.Event | None = None

    def fresh_for(self, symbol: str) -> float:
        return 6 * 3600  # the last trade stays the price until the next one (quiet stocks, after hours)

    def learn_prev(self, closes: dict[str, float]) -> None:
        """Previous closes already known from the regular quotes."""
        self.prev.update({s: c for s, c in closes.items() if c})

    def set_wanted(self, symbols: list[str]) -> None:
        wanted = list(dict.fromkeys(s for s in symbols if is_stock(s)))[:MAX_STREAM]
        if wanted == self.wanted:
            return
        self.wanted = wanted
        if self._loop and self._ws:
            self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._resubscribe()))

    def keys_changed(self) -> None:
        if self._loop and self._keys_changed:
            self._loop.call_soon_threadsafe(self._keys_changed.set)

    def info(self) -> dict:
        return {**super().info(), "streaming": len(self._streaming), "configured": configured()}

    async def _send(self, kind: str, symbols: list[str]) -> None:
        for s in symbols:
            await self._ws.send(json.dumps({"type": kind, "symbol": to_alpaca(s)}))
        if kind == "subscribe":
            self._streaming += [s for s in symbols if s not in self._streaming]
        else:
            self._streaming = [s for s in self._streaming if s not in symbols]

    async def _resubscribe(self) -> None:
        if not self._ws:
            return
        try:
            await self._send("unsubscribe", [s for s in self._streaming if s not in self.wanted])
            await self._send("subscribe", [s for s in self.wanted if s not in self._streaming])
        except Exception as e:  # noqa: BLE001 (the reconnect loop takes care of it)
            log.info("Changing Finnhub subscriptions failed: %s", e)

    async def _fill_prev(self) -> None:
        """Ask Finnhub for missing previous closes, about one a second (well inside 60 a minute)."""
        while True:
            missing = [s for s in self.wanted if s not in self.prev]
            if not missing:
                await asyncio.sleep(5)
                continue
            sym = missing[0]
            try:
                q = await asyncio.to_thread(lambda: cached(f"finnhub:quote:{sym}", 3600, lambda: quote(sym)))
                self.prev[sym] = q.get("pc") or 0
            except Exception as e:  # noqa: BLE001
                log.info("Finnhub quote for %s failed: %s", sym, e)
                self.prev.setdefault(sym, 0)  # don't keep asking for one that fails
            await asyncio.sleep(1.2)

    def _handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "trade":
            latest = {}
            for t in msg.get("data") or []:
                if t.get("s") and t.get("p") is not None:
                    latest[t["s"]] = t  # keep the last trade per symbol in this batch
            updates = []
            for raw, t in latest.items():
                sym = from_alpaca(raw)
                updates.append({"symbol": sym, "price": float(t["p"]), "open": self.prev.get(sym) or None})
            if updates:
                self._apply(updates)
        elif kind == "error":
            raise ConnectionError(msg.get("msg") or "Finnhub error")

    async def _session(self) -> None:
        url = f"{self.url}?{urllib.parse.urlencode({'token': key()})}"
        secure = {"ssl": _ssl()} if url.startswith("wss://") else {}
        async with connect(url, **secure, open_timeout=10, ping_interval=20, ping_timeout=20,
                           user_agent_header="RMT/0.4") as ws:
            self._ws, self._streaming = ws, []
            await self._send("subscribe", list(self.wanted))
            self._set_status("live", "Finnhub")
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except asyncio.TimeoutError:  # quiet (market closed): keep the connection
                    continue
                try:
                    self._handle(json.loads(raw))
                except ValueError:
                    continue

    async def _run(self) -> None:
        self._keys_changed = asyncio.Event()
        filler = asyncio.create_task(self._fill_prev())
        delay = 5
        try:
            while True:
                self._keys_changed.clear()
                if not configured():
                    self._set_status("off", "", "")
                    await self._keys_changed.wait()
                    continue
                self._set_status("connecting", "Finnhub")
                session = asyncio.create_task(self._session())
                changed = asyncio.create_task(self._keys_changed.wait())
                try:
                    done, _ = await asyncio.wait({session, changed}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for t in (session, changed):
                        if not t.done():
                            t.cancel()
                self._ws, self._streaming = None, []
                if changed in done:
                    self.prices.clear()
                    delay = 5
                    continue
                err = session.exception() if not session.cancelled() else None
                text = str(err or "Disconnected")
                if "401" in text or "403" in text or "Invalid API key" in text:
                    self._set_status("error", "Finnhub", "Finnhub didn't accept the key. Paste it again in ⚙ → Live data.")
                    await self._keys_changed.wait()
                    continue
                wait = 60 if "429" in text else delay  # 429: another program is using the key's connection
                self._set_status("offline", "Finnhub", text)
                try:
                    await asyncio.wait_for(self._keys_changed.wait(), timeout=wait)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, 120)
        finally:
            filler.cancel()


stocks = FinnhubStream()
