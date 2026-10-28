"""Pretend bets: a DraftKings-style bet slip and parlay builder, with no real money.

Bets are saved in data/bets.json with a pretend bankroll (starting at $1,000).
Moneyline, spread and total legs settle themselves from the final score
(ESPN); player props and other extra markets are marked won/lost by hand.

Odds math (American odds):
  decimal = 1 + odds/100 for +odds, 1 + 100/|odds| for -odds
  parlay decimal = product of the legs' decimals (a pushed leg counts as 1.0)
  payout = stake × decimal; to win = payout − stake
"""
import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import sports

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "data" / "bets.json"
START_BANKROLL = 1000.0
MAX_LEGS = 15
AUTO = {"ml", "spread", "total"}  # markets RMT can settle from the final score

_lock = threading.Lock()


class BetError(Exception):
    pass


# ---------- odds math ----------

def decimal(american: float) -> float:
    a = float(american)
    if a == 0 or -100 < a < 100:
        raise BetError("Those odds don't look right.")
    return 1 + a / 100 if a > 0 else 1 + 100 / -a


def american(dec: float) -> int:
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))


def implied(american_odds: float) -> float:
    return 1 / decimal(american_odds)


def quote(legs: list[dict], stake: float, kind: str = "parlay") -> dict:
    """What a slip pays: for a parlay, one bet; for singles, the same stake on each leg."""
    if not legs:
        raise BetError("Add a pick to your bet slip first.")
    if stake <= 0:
        raise BetError("Enter a stake.")
    if kind == "parlay":
        if len(legs) < 2:
            raise BetError("A parlay needs at least 2 picks.")
        dec = 1.0
        chance = 1.0
        for leg in legs:
            dec *= decimal(leg["price"])
            chance *= implied(leg["price"])
        payout = stake * dec
        return {"kind": "parlay", "stake": round(stake, 2), "decimal": round(dec, 4), "american": american(dec),
                "payout": round(payout, 2), "to_win": round(payout - stake, 2), "chance": round(chance * 100, 1)}
    payouts = [stake * decimal(leg["price"]) for leg in legs]
    return {"kind": "singles", "stake": round(stake * len(legs), 2), "payout": round(sum(payouts), 2),
            "to_win": round(sum(payouts) - stake * len(legs), 2), "each": [round(p - stake, 2) for p in payouts]}


def conflicts(legs: list[dict]) -> list[str]:
    """Problems a real sportsbook would refuse or price differently."""
    notes = []
    seen = {}
    games = {}
    for leg in legs:
        key = (leg.get("game_id"), leg.get("market"), leg.get("player", ""), leg.get("line_key", ""))
        if key in seen and seen[key] != leg.get("side"):
            notes.append(f"Both sides of the same bet ({leg.get('label')}) can't be in one parlay.")
        seen.setdefault(key, leg.get("side"))
        games.setdefault(leg.get("game_id"), []).append(leg)
    if any(len(v) > 1 for v in games.values()):
        notes.append("Same-game parlay: real sportsbooks price these lower because the picks are related, "
                      "so a real payout would be smaller than shown.")
    return notes


# ---------- the saved bets ----------

def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 (first use, or a damaged file)
        return {"start": START_BANKROLL, "bets": []}


def _save(data: dict) -> None:
    FILE.parent.mkdir(exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(FILE)


def _clean_leg(leg: dict) -> dict:
    try:
        price = float(leg["price"])
        decimal(price)
    except (KeyError, TypeError, ValueError):
        raise BetError("One of the picks has no price.")
    point = leg.get("point")
    out = {k: str(leg.get(k, ""))[:120] for k in ("game_id", "league", "game", "start", "market", "side", "label",
                                                   "book", "player", "line_key")}
    out.update(price=price, point=float(point) if point not in (None, "") else None, result="open")
    if out["market"] in AUTO and out["side"] not in ("home", "away", "over", "under"):
        raise BetError("That pick is missing which side it's on.")
    return out


def place(legs: list[dict], stake: float, kind: str) -> list[dict]:
    if len(legs) > MAX_LEGS:
        raise BetError(f"Up to {MAX_LEGS} picks per slip.")
    clean = [_clean_leg(leg) for leg in legs]
    if kind == "parlay":
        bad = [n for n in conflicts(clean) if n.startswith("Both sides")]
        if bad:
            raise BetError(bad[0])
    with _lock:
        data = _load()
        balance = summary(data)["balance"]
        q = quote(clean, stake, kind)
        if q["stake"] > balance + 1e-9:
            raise BetError(f"That's more than your pretend balance (${balance:,.2f}).")
        now = time.time()
        made = []
        groups = [clean] if kind == "parlay" else [[leg] for leg in clean]
        for group in groups:
            bq = quote(group, stake, "parlay" if len(group) > 1 else "singles")
            made.append({"id": uuid.uuid4().hex[:10], "placed": now, "kind": "parlay" if len(group) > 1 else "single",
                         "stake": round(stake, 2), "legs": group, "status": "open",
                         "decimal": bq.get("decimal") or round(decimal(group[0]["price"]), 4),
                         "potential": round(stake * (bq.get("decimal") or decimal(group[0]["price"])), 2),
                         "payout": 0.0})
        data["bets"] = made + data["bets"]
        _save(data)
    return made


def _grade(leg: dict, game: dict) -> str:
    """won / lost / push for a moneyline, spread or total leg of a finished game."""
    try:
        h, a = float(game["home"]["score"]), float(game["away"]["score"])
    except (KeyError, TypeError, ValueError):
        return "open"
    mine, theirs = (h, a) if leg["side"] in ("home", "over") else (a, h)
    if leg["market"] == "ml":
        return "won" if mine > theirs else "lost" if mine < theirs else "push"
    if leg["market"] == "spread":
        diff = mine + (leg["point"] or 0) - theirs
        return "won" if diff > 0 else "lost" if diff < 0 else "push"
    total = h + a
    if leg["point"] is None:
        return "open"
    if total == leg["point"]:
        return "push"
    return "won" if (total > leg["point"]) == (leg["side"] == "over") else "lost"


def _finished_games(league: str, start_iso: str) -> dict:
    """ESPN's games around a start time, by id (the day before covers US evenings in UTC)."""
    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except ValueError:
        return {}
    found = {}
    for day in (start, start - timedelta(days=1)):
        for g in sports._league_games(league, day.strftime("%Y%m%d"), odds_viewing=False):
            found[g["id"]] = g
    return found


def _rollup(bet: dict) -> None:
    results = [leg["result"] for leg in bet["legs"]]
    if "lost" in results:
        bet["status"], bet["payout"] = "lost", 0.0
    elif "open" in results:
        bet["status"] = "open"
    elif all(r == "push" for r in results):
        bet["status"], bet["payout"] = "push", bet["stake"]
    else:
        dec = 1.0
        for leg in bet["legs"]:
            if leg["result"] == "won":
                dec *= decimal(leg["price"])
        bet["status"], bet["payout"] = "won", round(bet["stake"] * dec, 2)


def settle_finished(data: dict) -> bool:
    """Grade open moneyline/spread/total legs whose games are over. True if anything changed."""
    changed = False
    now = datetime.now(timezone.utc)
    cache: dict[tuple, dict] = {}
    for bet in data["bets"]:
        if bet["status"] != "open":
            continue
        for leg in bet["legs"]:
            if leg["result"] != "open" or leg["market"] not in AUTO or leg["league"] not in sports.LEAGUES:
                continue
            try:
                if datetime.fromisoformat(leg["start"].replace("Z", "+00:00")) > now - timedelta(hours=2):
                    continue  # not over yet
            except ValueError:
                continue
            key = (leg["league"], leg["start"][:10])
            if key not in cache:
                cache[key] = _finished_games(leg["league"], leg["start"])
            game = cache[key].get(leg["game_id"])
            if game and game["state"] == "post":
                leg["result"] = _grade(leg, game)
                changed = changed or leg["result"] != "open"
        before = bet["status"]
        _rollup(bet)
        changed = changed or bet["status"] != before
    return changed


def summary(data: dict) -> dict:
    staked = sum(b["stake"] for b in data["bets"])
    returned = sum(b["payout"] for b in data["bets"] if b["status"] in ("won", "push"))
    settled = [b for b in data["bets"] if b["status"] != "open"]
    profit = sum(b["payout"] - b["stake"] for b in settled)
    wins = sum(1 for b in settled if b["status"] == "won")
    losses = sum(1 for b in settled if b["status"] == "lost")
    return {"start": data["start"], "balance": round(data["start"] - staked + returned, 2),
            "open_stake": round(sum(b["stake"] for b in data["bets"] if b["status"] == "open"), 2),
            "profit": round(profit, 2), "record": f"{wins}-{losses}"}


def all_bets(settle: bool = True) -> dict:
    with _lock:
        data = _load()
        if settle and settle_finished(data):
            _save(data)
    return {"bets": data["bets"], "summary": summary(data)}


def mark(bet_id: str, leg_index: int, result: str) -> dict:
    """Mark a leg (e.g. a player prop) won / lost / push by hand."""
    if result not in ("won", "lost", "push", "open"):
        raise BetError("Mark it won, lost or push.")
    with _lock:
        data = _load()
        bet = next((b for b in data["bets"] if b["id"] == bet_id), None)
        if not bet or not 0 <= leg_index < len(bet["legs"]):
            raise BetError("That bet isn't there anymore.")
        bet["legs"][leg_index]["result"] = result
        _rollup(bet)
        _save(data)
    return all_bets(settle=False)


def reset(start: float = START_BANKROLL) -> dict:
    with _lock:
        _save({"start": float(start), "bets": []})
    return all_bets(settle=False)
