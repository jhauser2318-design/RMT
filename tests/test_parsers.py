"""RMT parsers: ESPN games and odds, sportsbook comparison, Yahoo quotes, RSS/Atom feeds,
the AI chat's tools, and the sample-data fallback. No internet needed: every download is faked.

Run:  python tests/test_parsers.py   (from the RMT folder)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["RMT_DEMO"] = "0"
os.environ["ODDS_API_KEY"] = ""

from backend import ai, fetch, markets, news, sports  # noqa: E402

ESPN = {"events": [{
    "id": "401", "name": "Buffalo Bills at Kansas City Chiefs", "shortName": "BUF @ KC", "date": "2026-10-25T20:25Z",
    "links": [{"rel": ["summary", "desktop", "event"], "href": "https://espn.com/x"},
              {"rel": ["gamecast", "desktop"], "href": "https://espn.com/gamecast/401"}],
    "competitions": [{
        "date": "2026-10-25T20:25Z", "status": {"type": {"state": "pre", "shortDetail": "10/25 - 4:25 PM EDT"}},
        "venue": {"fullName": "Arrowhead Stadium"}, "broadcasts": [{"names": ["CBS"]}],
        "competitors": [
            {"homeAway": "home", "score": "0", "team": {"displayName": "Kansas City Chiefs", "abbreviation": "KC", "logo": "kc.png"},
             "records": [{"summary": "6-1"}]},
            {"homeAway": "away", "score": "0", "team": {"displayName": "Buffalo Bills", "abbreviation": "BUF", "logo": "buf.png"},
             "records": [{"summary": "5-2"}]}],
        "odds": [{"provider": {"name": "ESPN BET"}, "details": "KC -2.5", "overUnder": 47.5,
                  "homeTeamOdds": {"moneyLine": -135}, "awayTeamOdds": {"moneyLine": 114}}],
    }],
}, {
    # Newer ESPN layout: moneyline nested under "close", no homeTeamOdds.moneyLine
    "id": "402", "name": "A at B", "shortName": "A @ B", "date": "2026-10-25T17:00Z",
    "competitions": [{
        "status": {"type": {"state": "in", "shortDetail": "Q2 3:10"}},
        "competitors": [
            {"homeAway": "home", "score": "14", "team": {"displayName": "B Team", "abbreviation": "B"}},
            {"homeAway": "away", "score": "7", "team": {"displayName": "A Team", "abbreviation": "A"}}],
        "odds": [{"provider": {"name": "DraftKings"}, "details": "B -6.5", "overUnder": 44,
                  "moneyline": {"home": {"close": {"odds": "-250"}}, "away": {"close": {"odds": "+205"}}}}],
    }],
}]}

ODDS_API = [{
    "home_team": "Kansas City Chiefs", "away_team": "Buffalo Bills", "commence_time": "2026-10-25T20:25:00Z",
    "bookmakers": [
        {"title": "DraftKings", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Kansas City Chiefs", "price": -130}, {"name": "Buffalo Bills", "price": 110}]},
            {"key": "spreads", "outcomes": [{"name": "Kansas City Chiefs", "price": -110, "point": -2.5},
                                            {"name": "Buffalo Bills", "price": -110, "point": 2.5}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": -108, "point": 47.5}, {"name": "Under", "price": -112, "point": 47.5}]}]},
        {"title": "FanDuel", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Kansas City Chiefs", "price": -142}, {"name": "Buffalo Bills", "price": 120}]}]},
    ]}, {
    "home_team": "Somewhere FC", "away_team": "Elsewhere FC", "commence_time": "2026-10-26T15:00:00Z",
    "bookmakers": [{"title": "BetMGM", "markets": [
        {"key": "h2h", "outcomes": [{"name": "Somewhere FC", "price": 150}, {"name": "Elsewhere FC", "price": 170}, {"name": "Draw", "price": 230}]}]}],
}]

YAHOO = {"chart": {"result": [{"meta": {"regularMarketPrice": 110.0, "chartPreviousClose": 100.0, "shortName": "Test Corp", "currency": "USD"},
                               "indicators": {"quote": [{"close": [100, None, 105, 110]}]}}]}}

RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title>Stocks &amp; bonds rally</title><link>https://a.example/1</link><pubDate>Fri, 23 Oct 2026 14:00:00 GMT</pubDate>
<description>&lt;p&gt;Big &lt;b&gt;day&lt;/b&gt;&lt;/p&gt;</description><media:content url="https://img/1.jpg"/></item>
<item><title>Older story</title><link>https://a.example/2</link><pubDate>Thu, 22 Oct 2026 14:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"
 xmlns:media="http://search.yahoo.com/mrss/"><entry><yt:videoId>abc123</yt:videoId><title>Market close: NVDA rips</title>
<link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/><author><name>CNBC Television</name></author>
<published>2026-10-23T20:00:00+00:00</published><media:group><media:thumbnail url="https://i.ytimg.com/vi/abc123/hq.jpg"/>
<media:description>Recap</media:description></media:group></entry></feed>"""


def fake_get_json(url, params=None, timeout=10):
    if "scoreboard" in url:
        return ESPN
    if "the-odds-api" in url:
        return ODDS_API
    if "finance/chart" in url:
        if "BAD" in url:
            raise OSError("no such symbol")
        return YAHOO
    raise OSError(f"offline: {url}")


def reset():
    fetch._cache.clear()


def test_espn_games_and_odds():
    reset()
    sports.get_json = fake_get_json
    res = sports.games("nfl")
    assert res["live"] and not res["multi_book"]
    live, pre = res["games"]  # live games sort first
    assert live["state"] == "in" and live["home"]["score"] == "14"
    assert live["odds"]["home_ml"] == -250 and live["odds"]["away_ml"] == 205, live["odds"]
    assert pre["home"]["name"] == "Kansas City Chiefs" and pre["away"]["abbr"] == "BUF"
    assert pre["home"]["record"] == "6-1" and pre["venue"] == "Arrowhead Stadium" and pre["broadcast"] == "CBS"
    assert pre["odds"] == {"provider": "ESPN BET", "spread": "KC -2.5", "total": 47.5, "home_ml": -135, "away_ml": 114, "draw_ml": None}
    assert pre["link"] == "https://espn.com/gamecast/401"


def test_many_sportsbooks_and_best_price():
    reset()
    sports.get_json = fake_get_json
    os.environ["ODDS_API_KEY"] = "k"
    try:
        res = sports.games("nfl")
    finally:
        os.environ["ODDS_API_KEY"] = ""
    assert res["multi_book"]
    kc = next(g for g in res["games"] if g["home"]["abbr"] == "KC")
    assert [b["book"] for b in kc["books"]] == ["DraftKings", "FanDuel"]
    dk = kc["books"][0]
    assert dk["home_spread"] == -2.5 and dk["away_spread_price"] == -110 and dk["total"] == 47.5 and dk["under_price"] == -112
    # Best price = the one that pays the most: -130 beats -142, +120 beats +110.
    assert kc["best"]["home_ml"] == {"price": -130, "book": "DraftKings"}
    assert kc["best"]["away_ml"] == {"price": 120, "book": "FanDuel"}
    # A game only the odds service knows about still shows up, with the draw price.
    soccer = next(g for g in res["games"] if g["home"]["name"] == "Somewhere FC")
    assert soccer["books"][0]["draw_ml"] == 230 and soccer["best"]["draw_ml"]["price"] == 230


def test_odds_numbers():
    assert sports._num("+150") == 150 and sports._num("-110") == -110
    assert sports._num("EVEN") == 100 and sports._num("OFF") is None and sports._num(None) is None
    assert sports._same_team("Kansas City Chiefs", "kansas city chiefs") and not sports._same_team("", "x")


def test_quotes_and_ribbons():
    reset()
    markets.get_json = fake_get_json
    found, live = markets.quotes(["aapl", "BAD"])
    assert live and len(found) == 1  # a bad symbol is skipped, not fatal
    q = found[0]
    assert q["symbol"] == "AAPL" and q["price"] == 110 and q["change"] == 10 and round(q["pct"], 2) == 10.0
    assert q["spark"] == [100, 105, 110] and q["name"] == "Test Corp"
    rib = markets.ribbons(["TSLA"])
    assert rib["live"] and rib["ribbons"][0]["name"] == "My Watchlist" and rib["ribbons"][0]["items"][0]["symbol"] == "TSLA"
    crypto = next(r for r in rib["ribbons"] if r["id"] == "crypto")
    assert crypto["items"][0]["label"] == "Bitcoin"


def test_feeds():
    rss = fetch.parse_feed(RSS)
    assert rss[0]["title"] == "Stocks & bonds rally" and rss[0]["image"] == "https://img/1.jpg" and rss[0]["time"] > rss[1]["time"]
    assert rss[1]["image"] == ""
    atom = fetch.parse_feed(ATOM)
    assert atom[0]["video_id"] == "abc123" and atom[0]["source"] == "CNBC Television"
    assert atom[0]["link"].endswith("abc123") and atom[0]["image"].endswith("hq.jpg") and atom[0]["time"] > 0

    reset()
    news.get = lambda url, *a, **k: RSS if "rss" in url or "feed" in url or ".xml" in url else (_ for _ in ()).throw(OSError())
    res = news.headlines()
    assert res["live"] and [i["title"] for i in res["items"]] == ["Stocks & bonds rally", "Older story"]  # deduped across feeds
    assert res["items"][0]["summary"] == "Big day"  # HTML stripped


def test_falls_back_to_sample_data_when_offline():
    reset()
    offline = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))  # noqa: E731
    sports.get_json = markets.get_json = news.get_json = news.get = offline
    assert not markets.quotes(["AAPL"])[1]
    g = sports.games("all")
    assert not g["live"] and g["games"] and all(x["odds"] for x in g["games"])
    assert not news.headlines()["live"] and not news.trading_talk()["live"] and not news.youtube()["live"]
    assert not sports.standings("nfl")["live"] and not sports.search("lebron")["live"]


def test_chat_tools_answer():
    reset()
    sports.get_json = markets.get_json = fake_get_json
    out = ai._run_tool("get_quotes", {"symbols": ["AAPL"]})
    assert out["quotes"][0]["price"] == 110
    games = ai._run_tool("get_games", {"league": "nfl"})
    assert games["games"][1]["home"] == "Kansas City Chiefs 6-1 0"
    json.dumps(games)  # must be sendable to Claude
    names = {t["name"] for t in ai.TOOLS}
    assert names == {"get_quotes", "get_market_news", "get_trading_talk", "get_games", "get_standings", "search_sports"}


def test_chat_without_key_explains():
    os.environ["ANTHROPIC_API_KEY"] = ""
    try:
        ai.chat([{"role": "user", "content": "hi"}])
    except RuntimeError as e:
        assert ai.friendly_error(e)[0] == 400 and ".env" in str(e)
    else:
        raise AssertionError("expected a friendly error")


def test_chat_runs_tools_then_answers():
    """Claude asks for odds, gets them, then answers with a cited web source."""
    from types import SimpleNamespace as NS
    reset()
    sports.get_json = fake_get_json
    calls = []

    def create(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return NS(stop_reason="tool_use", content=[
                NS(type="text", text="Checking the line.", citations=None),
                NS(type="tool_use", id="t1", name="get_games", input={"league": "nfl"})])
        cite = NS(url="https://espn.com/injuries", title="NFL injuries")
        return NS(stop_reason="end_turn", content=[NS(type="text", text="**KC -2.5** at ESPN BET.", citations=[cite])])

    fake = NS(beta=NS(messages=NS(create=create)))
    real = ai._client
    ai._client = lambda: fake
    try:
        res = ai.chat([{"role": "assistant", "content": "hello"}, {"role": "user", "content": "KC line?"}])
    finally:
        ai._client = real
    assert res["reply"].endswith("**KC -2.5** at ESPN BET.") and res["used"] == ["get games"]
    assert res["sources"] == [{"url": "https://espn.com/injuries", "title": "NFL injuries"}]
    first, second = calls
    assert first["messages"][0]["role"] == "user"  # a leading assistant turn is dropped
    assert first["fallbacks"] == "default" and first["model"] == (os.getenv("RMT_MODEL") or "claude-opus-5-5")
    results = second["messages"][-1]["content"]
    assert results[0]["tool_use_id"] == "t1" and "Kansas City Chiefs" in results[0]["content"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("all RMT tests passed")
