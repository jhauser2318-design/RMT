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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("all live sports tests passed")
