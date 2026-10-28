"""Stock ribbons: live prices for indexes, big names, hot names, crypto and more.

Prices come from Yahoo Finance's public chart data (delayed up to ~15 minutes
for some exchanges). With Alpaca keys, every stock gets its real-time price
from Alpaca instead, and up to 30 stream live (alpaca.py). Crypto streams live
from Coinbase (stream.py). If nothing can be reached, sample prices are shown
and the page says so.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from . import alpaca, demo
from .fetch import cached, demo_mode, get_json
from .stream import crypto

RIBBONS = [
    {"id": "indexes", "name": "Indexes & Futures", "symbols": [
        ("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow"), ("^RUT", "Russell 2K"),
        ("^VIX", "VIX"), ("ES=F", "S&P Fut"), ("NQ=F", "Nasdaq Fut"), ("YM=F", "Dow Fut"),
        ("^TNX", "10Y Yield"), ("DX-Y.NYB", "Dollar")]},
    {"id": "megacap", "name": "Mega Caps", "symbols": [
        ("AAPL", ""), ("MSFT", ""), ("NVDA", ""), ("GOOGL", ""), ("AMZN", ""), ("META", ""),
        ("TSLA", ""), ("AVGO", ""), ("BRK-B", ""), ("JPM", ""), ("LLY", ""), ("V", ""),
        ("WMT", ""), ("XOM", ""), ("NFLX", ""), ("COST", "")]},
    {"id": "hot", "name": "Day-Trader Favorites", "symbols": [
        ("AMD", ""), ("PLTR", ""), ("SMCI", ""), ("COIN", ""), ("MSTR", ""), ("HOOD", ""),
        ("SOFI", ""), ("RIVN", ""), ("GME", ""), ("AMC", ""), ("MARA", ""), ("RIOT", ""),
        ("NIO", ""), ("ARM", ""), ("RDDT", ""), ("IONQ", "")]},
    {"id": "etfs", "name": "ETFs", "symbols": [
        ("SPY", ""), ("VOO", ""), ("QQQ", ""), ("IWM", ""), ("DIA", ""), ("TQQQ", ""), ("SQQQ", ""),
        ("SOXL", ""), ("ARKK", ""), ("XLF", ""), ("XLE", ""), ("TLT", ""), ("GLD", "")]},
    {"id": "crypto", "name": "Crypto", "symbols": [
        ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"),
        ("XRP-USD", "XRP"), ("DOGE-USD", "Dogecoin"), ("ADA-USD", "Cardano"),
        ("AVAX-USD", "Avalanche"), ("LINK-USD", "Chainlink")]},
    {"id": "macro", "name": "Commodities & FX", "symbols": [
        ("CL=F", "Crude Oil"), ("GC=F", "Gold"), ("SI=F", "Silver"), ("NG=F", "Nat Gas"),
        ("HG=F", "Copper"), ("EURUSD=X", "EUR/USD"), ("JPY=X", "USD/JPY"), ("GBPUSD=X", "GBP/USD")]},
]

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"


def _quote(symbol: str) -> dict | None:
    def load():
        data = get_json(CHART.format(symbol), {"range": "1d", "interval": "5m"}, timeout=8)
        res = data["chart"]["result"][0]
        meta = res["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        closes = [c for c in (res.get("indicators", {}).get("quote", [{}])[0].get("close") or []) if c]
        change = (price - prev) if price is not None and prev else 0
        return {
            "symbol": symbol,
            "name": meta.get("shortName") or meta.get("longName") or symbol,
            "price": price,
            "change": change,
            "pct": (change / prev * 100) if prev else 0,
            "currency": meta.get("currency", "USD"),
            "spark": closes[-40:],
        }
    try:
        return cached(f"q:{symbol}", 30, load)
    except Exception:  # noqa: BLE001 (one bad symbol shouldn't sink the ribbon)
        return None


def _realtime(q: dict, snaps: dict) -> dict:
    """Alpaca's real-time price in place of Yahoo's, then the live streams on top."""
    sn = snaps.get(q["symbol"])
    if sn:
        prev = sn["prev"] or (q["price"] - q["change"] if q.get("price") is not None else None)
        change = sn["price"] - prev if prev else 0.0
        q = {**q, "price": sn["price"], "change": change, "pct": (change / prev * 100) if prev else 0.0, "realtime": True}
    return alpaca.stocks.overlay(crypto.overlay(q))


def quotes(symbols: list[str]) -> tuple[list[dict], bool]:
    """Quotes for the symbols, and whether they are live (False = sample data)."""
    symbols = [s.strip().upper() for s in symbols if s.strip()][:80]
    if not demo_mode():
        crypto.want(symbols)  # coins (…-USD) get live streamed prices on top
        with ThreadPoolExecutor(max_workers=12) as pool:
            yahoo = pool.submit(lambda: [q for q in pool.map(_quote, symbols) if q])
            try:
                snaps = alpaca.snapshots(symbols)
            except alpaca.AlpacaError as e:
                logging.info("Alpaca: %s", e)
                snaps = {}
            got = yahoo.result()
        if got:
            return [_realtime(q, snaps) for q in got], True
        # Yahoo is down: use whatever real prices we have (Alpaca, the live streams).
        real = [_realtime({"symbol": s, "name": s, "price": None, "change": 0, "pct": 0, "currency": "USD", "spark": []}, snaps)
                for s in symbols]
        real = [q for q in real if q.get("realtime") or q.get("streaming")]
        if real:
            return real, True
        return [crypto.overlay(demo.quote(s)) for s in symbols], False
    return [demo.quote(s) for s in symbols], False


def ribbons(extra: list[str] | None = None) -> dict:
    groups = [dict(r) for r in RIBBONS]
    if extra:
        groups.insert(0, {"id": "watch", "name": "My Watchlist", "symbols": [(s, "") for s in extra]})
    every = list(dict.fromkeys(s for g in groups for s, _ in g["symbols"]))
    # Alpaca streams 30 stocks live: the watchlist first, then the index ETFs (SPY, VOO, QQQ) and the busiest names.
    by_id = {g["id"]: [s for s, _ in g["symbols"]] for g in groups}
    alpaca.stocks.set_wanted([*(extra or []), "SPY", "VOO", "QQQ", *by_id["hot"], *by_id["megacap"], *by_id["etfs"]])
    found, live = quotes(every)
    by_sym = {q["symbol"]: q for q in found}
    out = []
    for g in groups:
        items = []
        for sym, label in g["symbols"]:
            q = by_sym.get(sym.upper())
            if q:
                items.append({**q, "label": label or sym.replace("-USD", "")})
        out.append({"id": g["id"], "name": g["name"], "items": items})
    return {"live": live, "ribbons": out}
