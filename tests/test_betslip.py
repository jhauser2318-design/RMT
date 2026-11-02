"""Pretend bets: odds math, parlays, house rules, settling from final scores, the pretend bankroll.
No internet needed: game results are faked.

Run:  python tests/test_betslip.py   (from the RMT folder)
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["RMT_DEMO"] = "0"

from backend import betslip  # noqa: E402

START = "2026-10-20T00:20Z"  # long over


def leg(market, side, price, point=None, game="g1", **extra):
    return {"game_id": game, "league": "nfl", "game": "BUF @ KC", "start": START, "market": market, "side": side,
            "price": price, "point": point, "book": "DraftKings", "label": f"{side} {market}", **extra}


def final(home, away, gid="g1", state="post"):
    return {gid: {"id": gid, "state": state, "home": {"score": str(home)}, "away": {"score": str(away)}}}


def fresh():
    tmp = tempfile.mkdtemp()
    betslip.FILE = Path(tmp) / "data" / "bets.json"


def test_odds_math():
    assert betslip.decimal(+150) == 2.5 and round(betslip.decimal(-110), 4) == 1.9091 and betslip.decimal(100) == 2.0
    assert betslip.american(2.5) == 150 and betslip.american(1.5) == -200
    assert round(betslip.implied(-110) * 100, 1) == 52.4
    for bad in (0, 50, -99):
        try:
            betslip.decimal(bad)
        except betslip.BetError:
            pass
        else:
            raise AssertionError(bad)


def test_parlay_and_singles_quotes():
    q = betslip.quote([leg("ml", "home", -110), leg("ml", "away", +150, game="g2")], 10, "parlay")
    assert q["decimal"] == round(1.9091 * 2.5, 4) or abs(q["decimal"] - 4.7727) < 0.001
    assert q["payout"] == 47.73 and q["to_win"] == 37.73 and q["american"] == 377
    assert q["chance"] == round(100 / 1.9091 / 2.5, 1)
    s = betslip.quote([leg("ml", "home", -110), leg("ml", "away", +150, game="g2")], 10, "singles")
    assert s["stake"] == 20 and s["each"] == [9.09, 15.0] and s["to_win"] == 24.09
    for bad in (([], 10, "parlay"), ([leg("ml", "home", -110)], 10, "parlay"), ([leg("ml", "home", -110)], 0, "singles")):
        try:
            betslip.quote(*bad)
        except betslip.BetError:
            pass
        else:
            raise AssertionError(bad)


def test_house_rules():
    both = [leg("spread", "home", -110, -2.5, line_key="spread"), leg("spread", "away", -110, 2.5, line_key="spread")]
    notes = betslip.conflicts(both)
    assert any(n.startswith("Both sides") for n in notes) and any("Same-game" in n for n in notes)
    fresh()
    try:
        betslip.place(both, 10, "parlay")
    except betslip.BetError as e:
        assert "Both sides" in str(e)
    else:
        raise AssertionError("both sides of one bet can't be parlayed")
    assert betslip.conflicts([leg("ml", "home", -110), leg("ml", "away", 150, game="g2")]) == []
    try:
        betslip.place([leg("ml", "home", -110)] * 16, 1, "singles")
    except betslip.BetError as e:
        assert "Up to 15" in str(e)
    try:
        betslip.place([leg("ml", "home", -110)], 5000, "singles")
    except betslip.BetError as e:
        assert "more than your pretend balance" in str(e)


def test_settles_from_final_scores_and_bankroll():
    fresh()
    games = {}
    betslip._finished_games = lambda league, start: games
    # KC (home) wins 27-24: ML home won, KC -2.5 won (by 3), over 50.5 won (51), under lost
    betslip.place([leg("ml", "home", -150), leg("spread", "home", -110, -2.5, game="g1", line_key="spread")], 10, "parlay")
    betslip.place([leg("total", "under", -110, 50.5)], 20, "singles")
    betslip.place([leg("spread", "away", -110, 3.0, line_key="spread")], 10, "singles")  # BUF +3 pushes on a 3-point loss
    betslip.place([leg("player_pass_yds", "Over", -115, 274.5, player="Patrick Mahomes")], 10, "singles")
    r = betslip.all_bets()
    assert r["summary"]["balance"] == 950 and all(b["status"] == "open" for b in r["bets"])  # games not over yet

    games.update(final(27, 24))
    r = betslip.all_bets()
    by = {b["legs"][0]["market"] if b["kind"] == "single" else "parlay": b for b in r["bets"]}
    parlay = by["parlay"]
    assert parlay["status"] == "won" and parlay["payout"] == round(10 * (1 + 100 / 150) * (1 + 100 / 110), 2)
    assert by["total"]["status"] == "lost" and by["total"]["payout"] == 0
    assert by["spread"]["status"] == "push" and by["spread"]["payout"] == 10
    prop = by["player_pass_yds"]
    assert prop["status"] == "open"  # props are marked by hand

    r = betslip.mark(prop["id"], 0, "won")
    s = r["summary"]
    expected = 1000 - 50 + parlay["payout"] + 10 + round(10 * (1 + 100 / 115), 2)
    assert abs(s["balance"] - expected) < 0.01, (s, expected)
    assert s["record"] == "2-1" and s["open_stake"] == 0
    assert abs(s["profit"] - (parlay["payout"] - 10 - 20 + 0 + round(10 * (1 + 100 / 115), 2) - 10)) < 0.01

    assert betslip.reset()["summary"]["balance"] == 1000 and betslip.all_bets()["bets"] == []


def test_parlay_with_a_push_pays_the_rest():
    fresh()
    games = final(20, 17)
    betslip._finished_games = lambda league, start: games
    betslip.place([leg("spread", "away", -110, 3.0, line_key="spread"), leg("ml", "home", +120, game="g2")], 10, "parlay")
    games.update(final(31, 10, gid="g2"))
    b = betslip.all_bets()["bets"][0]
    assert [x["result"] for x in b["legs"]] == ["push", "won"]
    assert b["status"] == "won" and b["payout"] == 22.0  # the pushed leg drops out: 10 × 2.20


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("all pretend-bet tests passed")
