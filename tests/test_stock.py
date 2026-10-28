"""Stock lookup: search, chart data, key stats (with Yahoo's session crumb), and the chat tool.
No internet needed: every download is faked.

Run:  python tests/test_stock.py   (from the RMT folder)
"""
import io
import json
import os
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["RMT_DEMO"] = "0"
os.environ["ALPACA_KEY_ID"] = os.environ["ALPACA_SECRET_KEY"] = ""

from backend import ai, alpaca, fetch, markets, stock  # noqa: E402

SEARCH = {"quotes": [
    {"symbol": "AAPL", "shortname": "Apple Inc.", "exchDisp": "NASDAQ", "quoteType": "EQUITY"},
    {"symbol": "AAPL.MX", "shortname": "Apple (Mexico)", "exchDisp": "Mexico", "quoteType": "EQUITY"},
    {"symbol": "APLE", "longname": "Apple Hospitality REIT", "exchDisp": "NYSE", "quoteType": "EQUITY"},
    {"symbol": "XX", "shortname": "Some option", "quoteType": "OPTION"},  # not something RMT shows
]}

META = {"regularMarketPrice": 230.5, "chartPreviousClose": 228.0, "longName": "Apple Inc.", "fullExchangeName": "NasdaqGS",
        "currency": "USD", "instrumentType": "EQUITY", "regularMarketDayLow": 227.1, "regularMarketDayHigh": 231.9,
        "fiftyTwoWeekLow": 164.08, "fiftyTwoWeekHigh": 260.1, "regularMarketVolume": 51234567}


def chart_json(rng):
    return {"chart": {"result": [{"meta": META, "timestamp": [1, 2, 3, 4], "indicators": {"quote": [{"close": [228.5, None, 229.9, 230.5]}]}}]}}


def fake_get_json(url, params=None, timeout=10, headers=None):
    if "finance/search" in url:
        return SEARCH
    if "finance/chart/NOPE" in url:
        raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))
    if "finance/chart/" in url:
        return chart_json(params["range"])
    raise OSError("offline")


SUMMARY = {"quoteSummary": {"result": [{
    "summaryDetail": {"marketCap": {"raw": 3.5e12, "fmt": "3.5T"}, "trailingPE": {"raw": 35.1, "fmt": "35.10"},
                      "forwardPE": {"fmt": "31.20"}, "dividendYield": {"fmt": "0.44%"}, "beta": {"fmt": "1.24"},
                      "open": {"fmt": "228.90"}, "averageVolume": {"fmt": "55.1M"}},
    "defaultKeyStatistics": {"trailingEps": {"fmt": "6.57"}, "shortPercentOfFloat": {"fmt": "0.71%"}},
    "financialData": {"targetMeanPrice": {"fmt": "245.00"}, "recommendationKey": "strong_buy",
                      "numberOfAnalystOpinions": {"fmt": "41"}, "profitMargins": {"fmt": "24.30%"}, "revenueGrowth": {}},
    "assetProfile": {"sector": "Technology", "industry": "Consumer Electronics", "website": "https://www.apple.com",
                     "fullTimeEmployees": 164000, "longBusinessSummary": "Apple designs iPhones."},
    "calendarEvents": {"earnings": {"earningsDate": [{"raw": 1, "fmt": "2026-10-30"}]}},
}], "error": None}}

opened = []


def fake_open(url, timeout=10):
    opened.append(url)
    if "fc.yahoo.com" in url:
        raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))  # sets the cookie anyway
    if "getcrumb" in url:
        return b"crumb123" if len([u for u in opened if "getcrumb" in u]) == 1 else b"crumb456"
    if "quoteSummary" in url:
        if "crumb123" in url and len([u for u in opened if "quoteSummary" in u]) == 1:
            raise urllib.error.HTTPError(url, 401, "expired", {}, io.BytesIO(b""))  # first crumb went stale
        return json.dumps(SUMMARY).encode()
    raise OSError(url)


def setup():
    fetch._cache.clear()
    stock.get_json = markets.get_json = fake_get_json
    stock._open = fake_open
    stock._crumb.update(value="", at=0)
    opened.clear()


def test_search():
    setup()
    got = stock.search("apple")
    assert [r["symbol"] for r in got] == ["AAPL", "AAPL.MX", "APLE"]
    assert got[0] == {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "type": "Stock"}
    assert got[2]["name"] == "Apple Hospitality REIT"
    assert stock.search("  ") == []


def test_chart():
    setup()
    c = stock.chart("aapl", "1d")
    assert c["symbol"] == "AAPL" and c["points"] == [[1, 228.5], [3, 229.9], [4, 230.5]]  # missing bars dropped
    assert c["prev_close"] == 228.0
    assert stock.chart("AAPL", "1y")["prev_close"] is None  # only the 1-day chart compares to yesterday
    assert stock.chart("AAPL", "bogus")["range"] == "1d"
    try:
        stock.chart("NOPE", "1d")
    except stock.StockError as e:
        assert "Couldn't find NOPE" in str(e)
    else:
        raise AssertionError("an unknown symbol should say so")
    for bad in ("", "AAPL; rm", "x" * 20):
        try:
            stock.clean_symbol(bad)
        except stock.StockError:
            pass
        else:
            raise AssertionError(f"{bad!r} should be refused")


def test_details_full_stats_with_crumb_retry():
    setup()
    d = stock.details("AAPL")
    stats = {s["label"]: s["value"] for s in d["stats"]}
    assert d["name"] == "Apple Inc." and d["exchange"] == "NasdaqGS" and d["type"] == "Stock" and d["full_stats"]
    assert stats["Market cap"] == "3.5T" and stats["P/E (TTM)"] == "35.10" and stats["EPS (TTM)"] == "6.57"
    assert stats["Dividend yield"] == "0.44%" and stats["52-week range"] == "164.08 – 260.10"
    assert stats["Analyst target"] == "245.00 · Strong Buy (41 analysts)"
    assert stats["Next earnings"] == "2026-10-30" and stats["Volume"] == "51.23M"
    assert "Revenue growth" not in stats  # empty values are left out
    assert d["profile"]["sector"] == "Technology" and d["profile"]["employees"] == "164,000"
    # The first crumb was rejected (401): RMT got a fresh one and tried once more.
    assert [u.split("?")[0].split("/")[-1] for u in opened if "quoteSummary" in u] == ["AAPL", "AAPL"]
    assert "crumb=crumb456" in [u for u in opened if "quoteSummary" in u][-1]


def test_details_without_yahoo_session_still_shows_basics():
    setup()

    def no_session(url, timeout=10):
        raise urllib.error.HTTPError(url, 429, "too many", {}, io.BytesIO(b""))
    stock._open = no_session
    d = stock.details("AAPL")
    labels = [s["label"] for s in d["stats"]]
    assert not d["full_stats"] and labels == ["Previous close", "Day range", "52-week range", "Volume"]
    assert d["stats"][0]["value"] == "228.00"


def test_stock_page_streams_live_while_open():
    s = alpaca.StockStream()
    s.set_wanted(["SPY", "VOO", "QQQ"])
    s.set_focus("PLTR")
    assert s.wanted[:2] == ["PLTR", "SPY"]
    s.set_wanted(["SPY", "VOO", "QQQ"])  # the ribbons refresh: the open page keeps its slot
    assert s.wanted[0] == "PLTR"
    s.set_focus(None)
    s.set_wanted(["SPY", "VOO", "QQQ"])
    assert s.wanted == ["SPY", "VOO", "QQQ"]
    s.set_focus("BTC-USD")  # crypto streams from Coinbase, not Alpaca
    assert s.focus is None


def test_chat_can_look_up_a_stock():
    setup()
    assert "get_stock_details" in {t["name"] for t in ai.TOOLS}
    out = ai._run_tool("get_stock_details", {"symbol": "aapl"})
    assert out["symbol"] == "AAPL" and out["quote"]["price"] == 230.5
    json.dumps(out)  # must be sendable to Claude


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("all stock lookup tests passed")
