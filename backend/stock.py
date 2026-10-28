"""Look up any stock, ETF, index or coin: search, price chart, key stats and profile.

Everything comes from Yahoo Finance's public data (the same source as the
ribbons). The price on top is real-time with Alpaca keys, and the stock you're
looking at streams live while its page is open (see alpaca.StockStream.focus).
Key stats (market cap, P/E, dividend, analyst target…) need a short-lived
Yahoo session "crumb", which is fetched and reused automatically; if Yahoo
refuses it, the page still shows the price, chart and the basic stats.
"""
import http.cookiejar
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import demo
from .fetch import UA, _ssl, cached, demo_mode, get_json

log = logging.getLogger("rmt.stock")

SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
SUMMARY = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{}"
MODULES = "price,summaryDetail,defaultKeyStatistics,financialData,assetProfile,calendarEvents"
KINDS = {"EQUITY": "Stock", "ETF": "ETF", "INDEX": "Index", "CRYPTOCURRENCY": "Crypto",
         "MUTUALFUND": "Fund", "FUTURE": "Futures", "CURRENCY": "Currency"}

# chart range → bar size
RANGES = {"1d": "5m", "5d": "15m", "1mo": "60m", "6mo": "1d", "ytd": "1d", "1y": "1d", "5y": "1wk"}
SYMBOL = re.compile(r"^[A-Za-z0-9.^=\-]{1,15}$")


class StockError(Exception):
    pass


def clean_symbol(symbol: str) -> str:
    symbol = (symbol or "").strip().upper()
    if not SYMBOL.match(symbol):
        raise StockError("That doesn't look like a ticker symbol.")
    return symbol


def search(query: str) -> list[dict]:
    """Tickers matching a symbol or company name, best first."""
    query = (query or "").strip()
    if not query:
        return []
    if demo_mode():
        return demo.stock_search(query)

    def load():
        data = get_json(SEARCH, {"q": query, "quotesCount": 10, "newsCount": 0, "listsCount": 0}, timeout=8)
        out = []
        for q in data.get("quotes", []):
            kind = KINDS.get(q.get("quoteType", ""))
            if not kind or not q.get("symbol"):
                continue
            out.append({"symbol": q["symbol"], "name": q.get("shortname") or q.get("longname") or q["symbol"],
                        "exchange": q.get("exchDisp") or q.get("exchange", ""), "type": kind})
        return out
    try:
        return cached(f"search:stock:{query.lower()}", 600, load)
    except Exception as e:  # noqa: BLE001
        log.info("Stock search failed: %s", e)
        return demo.stock_search(query)


def chart(symbol: str, rng: str = "1d") -> dict:
    """Price points for the chart: {"points": [[unix time, price], ...], "prev_close", "meta"}."""
    symbol = clean_symbol(symbol)
    rng = rng if rng in RANGES else "1d"
    if demo_mode():
        return demo.stock_chart(symbol, rng)

    def load():
        data = get_json(CHART.format(symbol), {"range": rng, "interval": RANGES[rng], "includePrePost": "false"}, timeout=10)
        res = (data.get("chart", {}).get("result") or [None])[0]
        if not res:
            raise StockError(f"Yahoo Finance has no data for {symbol}.")
        closes = ((res.get("indicators", {}).get("quote") or [{}])[0].get("close")) or []
        points = [[t, round(c, 6)] for t, c in zip(res.get("timestamp") or [], closes) if c is not None]
        meta = res.get("meta", {})
        return {"symbol": symbol, "range": rng, "points": points,
                "prev_close": meta.get("chartPreviousClose") if rng == "1d" else None, "meta": meta}
    try:
        return cached(f"chart:{symbol}:{rng}", 60 if rng in ("1d", "5d") else 900, load)
    except StockError:
        raise
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise StockError(f"Couldn't find {symbol}. Check the symbol.") from e
        return demo.stock_chart(symbol, rng)
    except Exception as e:  # noqa: BLE001
        log.info("Chart for %s failed: %s", symbol, e)
        return demo.stock_chart(symbol, rng)


# ---------- key stats (Yahoo quoteSummary, which needs a session "crumb") ----------

_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar),
                                      urllib.request.HTTPSHandler(context=_ssl()))
_crumb = {"value": "", "at": 0.0}
_crumb_lock = threading.Lock()


def _open(url: str, timeout: float = 10) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with _opener.open(req, timeout=timeout) as res:
        return res.read()


def _get_crumb(fresh: bool = False) -> str:
    with _crumb_lock:
        if not fresh and _crumb["value"] and time.time() - _crumb["at"] < 3600:
            return _crumb["value"]
        try:
            _open("https://fc.yahoo.com", timeout=8)  # sets Yahoo's session cookie (the page itself is a 404)
        except urllib.error.HTTPError:
            pass
        crumb = _open("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=8).decode("utf-8", "replace").strip()
        if not crumb or "<" in crumb or len(crumb) > 64:
            raise StockError("Yahoo didn't hand out a session for key stats.")
        _crumb.update(value=crumb, at=time.time())
        return crumb


def _summary(symbol: str) -> dict:
    for attempt in (0, 1):
        crumb = _get_crumb(fresh=attempt == 1)
        url = f"{SUMMARY.format(urllib.parse.quote(symbol))}?modules={MODULES}&crumb={urllib.parse.quote(crumb)}"
        try:
            data = json.loads(_open(url))
            return ((data.get("quoteSummary") or {}).get("result") or [{}])[0]
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and attempt == 0:
                continue  # the session expired: get a new crumb once
            raise
    return {}


def _fmt(module: dict, key: str) -> str:
    v = (module or {}).get(key)
    if isinstance(v, dict):
        return v.get("fmt") or (str(v["raw"]) if v.get("raw") not in (None, "") else "")
    return str(v) if v not in (None, "", {}) else ""


def _money(n) -> str:
    if n is None:
        return ""
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= size:
            return f"{n / size:.2f}{unit}"
    return f"{n:,.0f}"


def _range(lo, hi, digits=2) -> str:
    if lo is None or hi is None:
        return ""
    return f"{lo:,.{digits}f} – {hi:,.{digits}f}"


def details(symbol: str) -> dict:
    """Name, key stats, profile and the 1-day chart meta for one symbol."""
    symbol = clean_symbol(symbol)
    if demo_mode():
        return demo.stock_details(symbol)
    meta = chart(symbol, "1d").get("meta", {})
    digits = 4 if (meta.get("regularMarketPrice") or 10) < 1 else 2
    stats = [  # always available from the chart data
        ("Previous close", f"{meta['chartPreviousClose']:,.{digits}f}" if meta.get("chartPreviousClose") else ""),
        ("Day range", _range(meta.get("regularMarketDayLow"), meta.get("regularMarketDayHigh"), digits)),
        ("52-week range", _range(meta.get("fiftyTwoWeekLow"), meta.get("fiftyTwoWeekHigh"), digits)),
        ("Volume", _money(meta.get("regularMarketVolume"))),
    ]
    profile, summary_ok = {}, False
    try:
        s = cached(f"summary:{symbol}", 900, lambda: _summary(symbol))
        sd, ks, fd = s.get("summaryDetail", {}), s.get("defaultKeyStatistics", {}), s.get("financialData", {})
        ap, cal, price = s.get("assetProfile", {}), s.get("calendarEvents", {}), s.get("price", {})
        earnings = ((cal.get("earnings") or {}).get("earningsDate") or [{}])[0]
        rec = _fmt(fd, "recommendationKey").replace("_", " ").title()
        analysts = _fmt(fd, "numberOfAnalystOpinions")
        target = _fmt(fd, "targetMeanPrice")
        stats = [
            ("Market cap", _fmt(sd, "marketCap") or _fmt(price, "marketCap")),
            ("P/E (TTM)", _fmt(sd, "trailingPE")),
            ("Forward P/E", _fmt(sd, "forwardPE")),
            ("EPS (TTM)", _fmt(ks, "trailingEps")),
            ("Dividend yield", _fmt(sd, "dividendYield") or _fmt(sd, "yield")),
            ("Beta", _fmt(sd, "beta")),
            ("Open", _fmt(sd, "open")),
            *stats,
            ("Avg. volume", _fmt(sd, "averageVolume")),
            ("Short % of float", _fmt(ks, "shortPercentOfFloat")),
            ("Analyst target", f"{target}{f' · {rec}' if rec else ''}{f' ({analysts} analysts)' if analysts else ''}" if target else ""),
            ("Next earnings", earnings.get("fmt", "") if isinstance(earnings, dict) else ""),
            ("Profit margin", _fmt(fd, "profitMargins")),
            ("Revenue growth", _fmt(fd, "revenueGrowth")),
            ("Net assets", _fmt(sd, "totalAssets")),
            ("Expense ratio", _fmt(ks, "annualReportExpenseRatio")),
        ]
        profile = {"sector": ap.get("sector", ""), "industry": ap.get("industry", ""), "website": ap.get("website", ""),
                   "employees": f"{ap['fullTimeEmployees']:,}" if isinstance(ap.get("fullTimeEmployees"), int) else "",
                   "summary": (ap.get("longBusinessSummary") or "")[:1200]}
        summary_ok = True
    except Exception as e:  # noqa: BLE001 (the basic stats above still show)
        log.info("Key stats for %s unavailable: %s", symbol, e)
    return {
        "symbol": symbol,
        "name": meta.get("longName") or meta.get("shortName") or symbol,
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName", ""),
        "currency": meta.get("currency", "USD"),
        "type": KINDS.get((meta.get("instrumentType") or "").upper(), ""),
        "stats": [{"label": k, "value": v} for k, v in stats if v],
        "profile": profile,
        "full_stats": summary_ok,
    }
