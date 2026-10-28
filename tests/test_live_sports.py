"""Live scores and the odds credit budget. No internet needed: every download is faked.

Run:  python tests/test_live_sports.py   (from the RMT folder)
"""
import copy
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["RMT_DEMO"] = "0"

from backend import fetch, live_sports, odds, sports  # noqa: E402

NOW_ISO = datetime.fromtimestamp(time.time() - 3600, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")  # kicked off an hour ago


def board(home_score="14", detail="Q2 3:10"):
    return {"events": [{
        "id": "1", "shortName": "BUF @ KC", "date": NOW_ISO,
        "competitions": [{"date": NOW_ISO, "status": {"type": {"state": "in", "shortDetail": detail}},
                          "competitors": [
                              {"homeAway": "home", "score": home_score, "team": {"displayName": "Kansas City Chiefs", "abbreviation": "KC"}},
                              {"homeAway": "away", "score": "7", "team": {"displayName": "Buffalo Bills", "abbreviation": "BUF"}}],
                          "odds": [{"provider": {"name": "ESPN BET"}, "details": "KC -2.5", "overUnder": 47.5}]}]}]}


ODDS_LIVE = [{"home_team": "Kansas City Chiefs", "away_team": "Buffalo Bills", "commence_time": NOW_ISO,
              "bookmakers": [{"title": "DraftKings", "markets": [
                  {"key": "h2h", "outcomes": [{"name": "Kansas City Chiefs", "price": -400}, {"name": "Buffalo Bills", "price": 310}]}]}]}]

calls = {"odds": 0}


def setup(remaining="497", espn=None):
    fetch._cache.clear()
    odds._lines.clear()
    odds._viewed.clear()
    odds._budget.update(remaining=None, used=None, at=0.0)
    os.environ["ODDS_API_KEY"] = "k"
    calls["odds"] = 0

    def fake_odds(url, params=None, timeout=10):
        calls["odds"] += 1
        assert params["markets"] == "h2h,spreads,totals" and params["regions"] == "us"
        return json.dumps(ODDS_LIVE).encode(), {"x-requests-remaining": remaining, "x-requests-used": "3"}
    odds.get_with_headers = fake_odds
    state = {"board": espn or board()}
    sports.get_json = lambda url, params=None, timeout=10: state["board"] if "scoreboard" in url else (_ for _ in ()).throw(OSError())
    return state


def test_budget_spreads_credits_over_the_month():
    setup()
    assert odds.gap() == odds.UNKNOWN_GAP  # nothing known before the first answer
    now = datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc).timestamp()  # ~16 days left
    odds._budget["remaining"] = 500                     # free plan: 166 lookups left
    odds._viewed.update(nfl=now)
    free = odds.gap(now)
    assert 2 * 3600 < free < 3 * 3600, free / 3600      # one league: about every 2-3 hours
    odds._viewed.update(nba=now)
    assert 4 * 3600 < odds.gap(now) < 5 * 3600          # two leagues share it: about every 4.6 hours
    odds._viewed.update(nhl=now, mlb=now)
    assert odds.gap(now) == odds.MAX_GAP                # four leagues: capped at every 6 hours
    odds._budget["remaining"] = 20000                   # $30 plan
    assert 12 * 60 < odds.gap(now) < 16 * 60            # four leagues: every ~14 minutes
    odds._viewed.clear()
    odds._viewed.update(nfl=now)
    assert 3 * 60 < odds.gap(now) < 4 * 60              # one league: every ~3.5 minutes
    odds._budget["remaining"] = 2
    assert odds.gap(now) == float("inf")                # out of credits: no more lookups this month


def test_all_sports_never_spends_credits():
    setup()
    sports.games("all")
    assert calls["odds"] == 0
    res = sports.games("nfl")                           # picking a league fetches once
    assert calls["odds"] == 1 and res["odds_budget"]["remaining"] == 497
    sports.games("nfl")
    assert calls["odds"] == 1                           # not due again yet
    res = sports.games("all")                           # all sports shows what NFL last fetched, for free
    assert calls["odds"] == 1 and next(g for g in res["games"] if g["league"] == "nfl")["books"]
    sports.games("nfl", force_odds=True)                # "Update odds now"
    assert calls["odds"] == 2


def test_live_odds_label():
    setup()
    g = sports.games("nfl")["games"][0]
    assert g["state"] == "in" and g["odds_live"] is True        # fetched after kickoff
    assert g["best"]["away_ml"] == {"price": 310, "book": "DraftKings"}
    odds._lines["nfl"] = (time.time() - 7200, odds._lines["nfl"][1])  # fetched before kickoff
    g = sports.games("all")["games"][0]
    assert g["odds_live"] is False


def test_watcher_pushes_only_changes():
    state = setup()
    w = live_sports.ScoreWatcher(leagues=["nfl"])
    assert w.poll(["nfl"], ttl=0) == []                 # first look: nothing to push, the page has it
    assert "nfl" in w.live_leagues
    assert w.poll(["nfl"], ttl=0) == []                 # nothing changed
    state["board"] = board(home_score="21", detail="Q2 0:45")
    fetch._cache.clear()
    changed = w.poll(["nfl"], ttl=0)
    assert len(changed) == 1 and changed[0]["home"]["score"] == "21" and changed[0]["detail"] == "Q2 0:45"
    assert calls["odds"] == 0                           # live scores never spend odds credits
    final = copy.deepcopy(board(home_score="28"))
    final["events"][0]["competitions"][0]["status"]["type"].update(state="post", shortDetail="Final")
    state["board"] = final
    fetch._cache.clear()
    assert w.poll(["nfl"], ttl=0)[0]["state"] == "post"
    assert "nfl" not in w.live_leagues                  # no more live games: back to every 5 minutes


def test_leagues_are_the_ones_bet_on():
    assert list(sports.LEAGUES) == ["nfl", "ncaaf", "nba", "ncaab", "mlb", "nhl", "ufc"]  # no soccer, no WNBA


def test_odds_key_check_reads_credits():
    import io
    import urllib.error
    setup()
    odds.get_with_headers = lambda url, params=None, timeout=10: (b"[]", {"x-requests-remaining": "500", "x-requests-used": "0"})
    assert odds.test_key("good") == (True, "✅ Key works. 500 credits left this month.")
    assert odds.budget()["remaining"] == 500

    def refuse(url, params=None, timeout=10):
        raise urllib.error.HTTPError(url, 401, "no", {}, io.BytesIO(b""))
    odds.get_with_headers = refuse
    ok, msg = odds.test_key("bad")
    assert not ok and "didn't accept the key" in msg


def test_save_key_endpoint():
    import tempfile
    from fastapi import HTTPException
    from backend import main, settings
    with tempfile.TemporaryDirectory() as tmp:
        real = settings.ENV, settings.ROOT, dict(main.KEY_TESTS)
        settings.ENV, settings.ROOT = Path(tmp) / ".env", Path(tmp)
        main.KEY_TESTS["ODDS_API_KEY"] = lambda k: (k == "good", "✅ Key works." if k == "good" else "bad key")
        try:
            try:
                main.save_key(main.KeyIn(name="ODDS_API_KEY", value="nope"))
            except HTTPException as e:
                assert e.status_code == 400 and e.detail == "bad key" and not settings.ENV.exists()  # bad keys never saved
            res = main.save_key(main.KeyIn(name="ODDS_API_KEY", value=" good "))
            assert res["ok"] and "ODDS_API_KEY=good" in settings.ENV.read_text()
            assert main.which_keys()["ODDS_API_KEY"] is True
            try:
                main.save_key(main.KeyIn(name="ALPACA_KEY_ID", value="x"))  # has its own form
            except HTTPException as e:
                assert e.status_code == 400
            else:
                raise AssertionError("only keys with a test can be set here")
        finally:
            settings.ENV, settings.ROOT = real[0], real[1]
            main.KEY_TESTS.clear()
            main.KEY_TESTS.update(real[2])
            os.environ["ODDS_API_KEY"] = ""


EVENT = {"id": "evt123", "home_team": "Kansas City Chiefs", "away_team": "Buffalo Bills", "bookmakers": [
    {"title": "DraftKings", "markets": [
        {"key": "player_pass_yds", "outcomes": [
            {"name": "Over", "description": "Patrick Mahomes", "price": -115, "point": 274.5},
            {"name": "Under", "description": "Patrick Mahomes", "price": -105, "point": 274.5}]},
        {"key": "player_anytime_td", "outcomes": [{"name": "Yes", "description": "Travis Kelce", "price": 120}]}]},
    {"title": "FanDuel", "markets": [
        {"key": "player_pass_yds", "outcomes": [
            {"name": "Over", "description": "Patrick Mahomes", "price": -110, "point": 274.5}]}]},
]}


def test_more_bets_props_best_price_and_credits():
    import io
    import urllib.error
    setup()
    asked = []

    def fake(url, params=None, timeout=10):
        asked.append((url, params))
        return json.dumps(EVENT).encode(), {"x-requests-remaining": "490", "x-requests-used": "10", "x-requests-last": "2"}
    odds.get_with_headers = fake
    odds._more.clear()
    groups = {g["name"]: g["markets"] for g in odds.groups("nfl")}
    assert groups["Player props"] == 6 and "1st quarter" in groups and odds.groups("ncaab") and odds.groups("ufc") == []
    r = odds.more_bets("nfl", "americanfootball_nfl", "evt123", "Player props")
    url, params = asked[0]
    assert url.endswith("/sports/americanfootball_nfl/events/evt123/odds") and params["markets"].startswith("player_pass_yds,")
    assert r["cost"] == 2 and r["budget"]["remaining"] == 490
    pass_yds = next(m for m in r["markets"] if m["key"] == "player_pass_yds")
    assert pass_yds["label"] == "Passing yards"
    over = next(x for x in pass_yds["rows"] if x["side"] == "Over")
    assert over["player"] == "Patrick Mahomes" and over["point"] == 274.5
    assert over["best"] == {"price": -110, "book": "FanDuel"} and len(over["books"]) == 2  # -110 beats -115
    assert [m["key"] for m in r["markets"]] == ["player_pass_yds", "player_anytime_td"]

    assert odds.more_bets("nfl", "americanfootball_nfl", "evt123", "Player props")["cached"] and len(asked) == 1  # no double charge
    odds.more_bets("nfl", "americanfootball_nfl", "evt123", "Player props", force=True)
    assert len(asked) == 2

    for bad_id in ("../x", "", "a b"):
        try:
            odds.more_bets("nfl", "americanfootball_nfl", bad_id, "Player props")
        except odds.OddsError:
            pass
        else:
            raise AssertionError(f"{bad_id!r} must be refused")

    odds._budget["remaining"] = 4  # 1st quarter needs up to 3: fine; props need up to 6: not
    odds._more.clear()
    try:
        odds.more_bets("nfl", "americanfootball_nfl", "evt123", "Player props")
    except odds.OddsError as e:
        assert "credits left" in str(e)
    else:
        raise AssertionError("should stop before spending credits it doesn't have")

    def not_on_plan(url, params=None, timeout=10):
        raise urllib.error.HTTPError(url, 401, "no", {}, io.BytesIO(b""))
    odds.get_with_headers = not_on_plan
    odds._budget["remaining"] = 400
    try:
        odds.more_bets("nfl", "americanfootball_nfl", "evt123", "1st quarter")
    except odds.OddsError as e:
        assert "plan doesn't include" in str(e)


def test_games_carry_the_odds_event_id():
    setup()
    ODDS_LIVE[0]["id"] = "abc999"
    try:
        g = sports.games("nfl")["games"][0]
    finally:
        del ODDS_LIVE[0]["id"]
    assert g["odds_event_id"] == "abc999"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("all live sports tests passed")
