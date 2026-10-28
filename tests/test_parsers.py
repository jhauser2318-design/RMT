"""RMT parsers: ESPN games and odds, sportsbook comparison, Yahoo quotes, RSS/Atom feeds,
the AI chat's tools, the sample-data fallback and the "Update" button. No internet needed: every download is faked.

Run:  python tests/test_parsers.py   (from the RMT folder)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["RMT_DEMO"] = "0"
os.environ["ODDS_API_KEY"] = ""

from backend import ai, fetch, markets, news, odds, sports  # noqa: E402

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
<media:description>Recap</media:description><media:community><media:starRating count="10" average="5.00" min="1" max="5"/>
<media:statistics views="123456"/></media:community></media:group></entry></feed>"""


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
    odds._lines.clear()
    odds._viewed.clear()
    odds._budget.update(remaining=None, used=None, at=0.0)
    odds.get_with_headers = lambda url, params=None, timeout=10: (
        json.dumps(ODDS_API).encode(), {"x-requests-remaining": "480", "x-requests-used": "20"})


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
    assert atom[0]["views"] == 123456
    assert atom[0]["link"].endswith("abc123") and atom[0]["image"].endswith("hq.jpg") and atom[0]["time"] > 0

    reset()
    news.get = lambda url, *a, **k: RSS if "rss" in url or "feed" in url or ".xml" in url else (_ for _ in ()).throw(OSError())
    res = news.headlines()
    assert res["live"] and [i["title"] for i in res["items"]] == ["Stocks & bonds rally", "Older story"]  # deduped across feeds
    assert res["items"][0]["summary"] == "Big day"  # HTML stripped


def test_youtube_popular_advice_ranked_by_views():
    import time as _t
    now = _t.time()

    def feed(cid):
        def entry(vid, title, days, views):
            stamp = _t.strftime("%Y-%m-%dT%H:%M:%S+00:00", _t.gmtime(now - days * 86400))
            return f"""<entry><yt:videoId>{vid}</yt:videoId><title>{title}</title>
<link rel="alternate" href="https://www.youtube.com/watch?v={vid}"/><author><name>{cid}</name></author>
<published>{stamp}</published><media:group><media:community><media:statistics views="{views}"/></media:community></media:group></entry>"""
        entries = {
            "UCV6KDgJskWaEckne5aPA0aQ": entry("g1", "Buy these 3 stocks", 2, 900000) + entry("g0", "Old video", 30, 9000000),
            "UCBayuhgYpKNbhJxfExYkPfA": entry("r1", "Small cap momentum setup", 1, 250000),
            "UCrp_UI8XtuYfpiqluWLD7Lw": entry("c1", "Market close", 0.5, 5000000),
        }.get(cid, "")
        return f"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"
 xmlns:media="http://search.yahoo.com/mrss/">{entries}</feed>""".encode()

    reset()
    news.get = lambda url, *a, **k: feed(url.split("channel_id=")[1])
    os.environ["YOUTUBE_API_KEY"] = ""
    popular = news.youtube(tab="popular")
    assert [v["video_id"] for v in popular["items"]] == ["g1", "r1"], popular  # last week only, most viewed first
    assert popular["items"][0]["views"] == 900000 and popular["items"][0]["image"].endswith("g1/mqdefault.jpg")
    assert [v["video_id"] for v in news.youtube(tab="news")["items"]] == ["c1"]  # market news is its own tab
    assert [v["video_id"] for v in news.youtube(tab="trading")["items"]] == ["r1"]
    assert [v["video_id"] for v in news.youtube("momentum")["items"]] == ["r1"]  # a search looks in every tab


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
    assert names == {"get_quotes", "get_stock_details", "get_market_news", "get_trading_talk", "get_games", "get_standings", "search_sports"}


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
    assert first["cache_control"] == {"type": "ephemeral"}
    assert first["fallbacks"] == "default" and first["model"] == (os.getenv("RMT_MODEL") or "claude-opus-5-5")
    results = second["messages"][-1]["content"]
    assert results[0]["tool_use_id"] == "t1" and "Kansas City Chiefs" in results[0]["content"]


def test_update_installs_new_version_and_keeps_keys():
    import io
    import tempfile
    import zipfile
    import updater
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-mine")
        (root / "data").mkdir()
        (root / "data" / "app.log").write_text("old log")
        (root / "requirements.txt").write_text("fastapi\n")
        (root / "app.txt").write_text("v1")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:  # GitHub's ZIP: one top-level folder
            z.writestr("RMT-abc/app.txt", "v2")
            z.writestr("RMT-abc/new/file.txt", "hi")
            z.writestr("RMT-abc/.env", "ANTHROPIC_API_KEY=")
            z.writestr("RMT-abc/data/app.log", "")
            z.writestr("RMT-abc/requirements.txt", "fastapi\n")
        commit = {"sha": "a" * 40, "commit": {"message": "Merge pull request #2 from x/desktop\n\nRMT desktop app",
                                               "committer": {"date": "2026-10-24T00:00:00Z"}}}
        real = (updater.ROOT, updater.VERSION_FILE, updater._get)
        updater.ROOT, updater.VERSION_FILE = root, root / "data" / "version.json"
        updater._get = lambda url, timeout=15: buf.getvalue() if "zipball" in url else json.dumps(commit).encode()
        try:
            check = updater.check()
            assert check["available"] and check["latest"]["summary"] == "RMT desktop app"
            res = updater.update()
            assert res == {"updated": True, "error": None, "summary": "RMT desktop app"}
            assert (root / "app.txt").read_text() == "v2" and (root / "new" / "file.txt").read_text() == "hi"
            assert (root / ".env").read_text() == "ANTHROPIC_API_KEY=sk-ant-mine"  # keys untouched
            assert (root / "data" / "app.log").read_text() == "old log"
            assert not updater.check()["available"]
            assert updater.update()["summary"] == "You already have the latest version."
        finally:
            updater.ROOT, updater.VERSION_FILE, updater._get = real


def test_update_works_around_files_windows_wont_overwrite():
    """The real failure: "[Errno 13] Permission denied: ...\\INSTALL.bat" stopped a whole update."""
    import io
    import shutil as _sh
    import tempfile
    import zipfile
    import updater
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "backend").mkdir()
        (root / "docs").mkdir()
        for name, text in {"INSTALL.bat": "old", "backend/app.py": "v1", "backend/locked.py": "v1", "docs/guide.md": "v1",
                           "requirements.txt": "x\n", ".env": "KEY=mine"}.items():
            (root / name).write_text(text)

        def zipped(version):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for name in ("INSTALL.bat", "backend/app.py", "backend/locked.py", "docs/guide.md", "scripts/install.ps1"):
                    z.writestr(f"RMT-abc/{name}", version)
                z.writestr("RMT-abc/requirements.txt", "x\n")
            return buf.getvalue()

        real_copy = _sh.copy2
        calls = {}

        def picky_copy(src, dest):
            dest = Path(dest)
            calls[dest.name] = calls.get(dest.name, 0) + 1
            if dest.name == "INSTALL.bat":
                raise PermissionError(13, "Permission denied", str(dest))  # what happened on the PC
            if dest.name == "locked.py" and state["sha"] == "b" * 40 and dest.exists() and calls[dest.name] <= 2:
                raise PermissionError(13, "Permission denied", str(dest))  # in use: only a move-aside works
            if dest.name == "guide.md":
                raise PermissionError(13, "Permission denied", str(dest))  # never writable: optional, skipped
            return real_copy(src, dest)

        state = {"zip": zipped("v2"), "sha": "b" * 40}

        def fake_get(url, timeout=15):
            if "zipball" in url:
                return state["zip"]
            return json.dumps({"sha": state["sha"], "commit": {"message": "Fix updates", "committer": {"date": ""}}}).encode()
        saved = (updater.ROOT, updater.VERSION_FILE, updater._get, updater.shutil.copy2)
        updater.ROOT, updater.VERSION_FILE, updater._get = root, root / "data" / "version.json", fake_get
        updater.shutil.copy2 = picky_copy
        try:
            res = updater.update()
            assert res["updated"] and res["error"] is None, res
            assert (root / "INSTALL.bat").read_text() == "old" and "INSTALL.bat" not in calls  # never touched
            assert not (root / "scripts").exists()  # install-only folder skipped
            assert (root / "backend" / "app.py").read_text() == "v2"
            assert (root / "backend" / "locked.py").read_text() == "v2"  # the locked one was moved aside
            assert (root / "docs" / "guide.md").read_text() == "v1"  # optional file left as it was
            assert (root / ".env").read_text() == "KEY=mine"
            assert len(list(root.rglob("*.rmt-old*"))) == 1

            # Next update: the moved-aside file is cleaned up.
            state.update(zip=zipped("v3"), sha="c" * 40)
            calls.clear()
            assert updater.update()["updated"]
            assert not list(root.rglob("*.rmt-old*")) and (root / "backend" / "app.py").read_text() == "v3"

            # A file RMT needs that truly can't be replaced: the update stops and says why.
            state.update(zip=zipped("v4"), sha="d" * 40)
            updater.shutil.copy2 = lambda s, d: (_ for _ in ()).throw(PermissionError(13, "Permission denied", str(d)))
            real_replace = updater.os.replace
            updater.os.replace = lambda a, b: (_ for _ in ()).throw(PermissionError(13, "Permission denied", str(a)))
            try:
                res = updater.update()
            finally:
                updater.os.replace = real_replace
            assert not res["updated"] and "antivirus" in res["error"] and "still in place" in res["error"]
        finally:
            updater.ROOT, updater.VERSION_FILE, updater._get, updater.shutil.copy2 = saved


def test_automatic_updates_switch_and_launcher():
    import importlib.machinery
    import importlib.util
    import tempfile
    import types
    import updater
    with tempfile.TemporaryDirectory() as tmp:
        real = updater.SETTINGS_FILE
        updater.SETTINGS_FILE = Path(tmp) / "data" / "settings.json"
        try:
            assert updater.auto_enabled()  # on by default, like Life Control Center
            updater.set_auto(False)
            assert not updater.auto_enabled()
            updater.set_auto(True)
            assert updater.auto_enabled() and json.loads(updater.SETTINGS_FILE.read_text()) == {"auto_update": True}
        finally:
            updater.SETTINGS_FILE = real

    # The launcher installs an update before starting, but an update problem never stops RMT opening.
    path = str(Path(__file__).resolve().parent.parent / "launcher.pyw")
    spec = importlib.util.spec_from_loader("launcher", importlib.machinery.SourceFileLoader("launcher", path))
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    fake = types.ModuleType("updater")
    real_updater = sys.modules["updater"]
    sys.modules["updater"] = fake
    try:
        fake.auto_enabled = lambda: True
        fake.update = lambda: {"updated": True, "error": None}
        assert launcher.install_update() is True
        fake.update = lambda: {"updated": False, "error": "offline"}
        assert launcher.install_update() is False
        fake.update = lambda: 1 / 0
        assert launcher.install_update() is False
        fake.auto_enabled = lambda: False
        fake.update = lambda: (_ for _ in ()).throw(AssertionError("must not update when switched off"))
        assert launcher.install_update() is False
    finally:
        sys.modules["updater"] = real_updater


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("all RMT tests passed")
