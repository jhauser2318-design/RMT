"""Odds from many sportsbooks (The Odds API), spent carefully.

Each lookup costs credits: moneyline + spread + total in the US = 3 credits
(free plan: 500 a month; $30 plan: 20,000). The Odds API reports what's
left on every answer, so RMT spreads the rest evenly over the days left in
the month, across the leagues you actually look at:
  - free plan, mid-month, one league: about every 2 hours;
  - $30 plan: every few minutes.
The odds include games in progress (live, in-play lines).
"All sports" never spends credits: it shows whatever each league last fetched.
"Update odds now" (one league) spends 3 credits on the spot.
"""
import calendar
import json
import os
import re
import threading
import time
from datetime import datetime, timezone

from .fetch import get_with_headers

ODDS = "https://api.the-odds-api.com/v4/sports/{}/odds"
COST = 3                 # markets (h2h, spreads, totals) × regions (us)
MIN_GAP = 2 * 60         # never more often than every 2 minutes per league
MAX_GAP = 6 * 3600       # ...and at least every 6 hours while you're looking
UNKNOWN_GAP = 30 * 60    # before the first answer tells us the balance

_lock = threading.Lock()
_lines: dict[str, tuple[float, list]] = {}   # league -> (fetched at, lines)
_viewed: dict[str, float] = {}               # league -> last time someone looked at it
_budget = {"remaining": None, "used": None, "at": 0.0}


def key() -> str:
    return os.getenv("ODDS_API_KEY", "").strip()


def _seconds_left_in_month(now: float) -> float:
    d = datetime.fromtimestamp(now, timezone.utc)
    last_day = calendar.monthrange(d.year, d.month)[1]
    end = datetime(d.year, d.month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return max((end - d).total_seconds(), 3600)


def gap(now: float | None = None) -> float:
    """Seconds between lookups for each league, so the credits last the month."""
    now = now or time.time()
    remaining = _budget["remaining"]
    if remaining is None:
        return UNKNOWN_GAP
    if remaining < COST:
        return float("inf")  # out of credits until the month resets
    viewed = sum(1 for t in _viewed.values() if now - t < 24 * 3600) or 1
    per_league = _seconds_left_in_month(now) / (remaining // COST) * viewed
    return min(max(per_league, MIN_GAP), MAX_GAP)


def budget() -> dict:
    g = gap()
    return {"remaining": _budget["remaining"], "used": _budget["used"],
            "every_min": None if g == float("inf") else round(g / 60), "configured": bool(key())}


def test_key(k: str) -> tuple[bool, str]:
    """Check a key with the free sports-list request; it also reports the credits left."""
    try:
        _, headers = get_with_headers("https://api.the-odds-api.com/v4/sports", {"apiKey": k})
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None)
        if code in (401, 403):
            return False, "The Odds API didn't accept the key. Copy it again from your email or account page."
        return False, f"Couldn't reach The Odds API ({getattr(e, 'reason', e)})."
    rem = headers.get("x-requests-remaining")
    if rem is not None:
        _budget.update(remaining=int(float(rem)), used=int(float(headers.get("x-requests-used") or 0)), at=time.time())
    left = f" {int(float(rem))} credits left this month." if rem is not None else ""
    return True, f"✅ Key works.{left}"


def _parse(data: list) -> list[dict]:
    out = []
    for ev in data:
        books = []
        for bm in ev.get("bookmakers", []):
            row = {"book": bm.get("title", bm.get("key"))}
            for m in bm.get("markets", []):
                for oc in m.get("outcomes", []):
                    side = "home" if oc["name"] == ev["home_team"] else "away" if oc["name"] == ev["away_team"] else None
                    if m["key"] == "h2h":
                        row[f"{side}_ml" if side else "draw_ml"] = oc.get("price")
                    elif m["key"] == "spreads" and side:
                        row[f"{side}_spread"] = oc.get("point")
                        row[f"{side}_spread_price"] = oc.get("price")
                    elif m["key"] == "totals":
                        row["total"] = oc.get("point")
                        row["over_price" if oc["name"] == "Over" else "under_price"] = oc.get("price")
            books.append(row)
        out.append({"home": ev["home_team"], "away": ev["away_team"], "start": ev["commence_time"], "books": books,
                    "event_id": ev.get("id", "")})
    return out


def _fetch(league: str, sport_key: str) -> list[dict]:
    body, headers = get_with_headers(ODDS.format(sport_key), {
        "apiKey": key(), "regions": "us", "markets": "h2h,spreads,totals", "oddsFormat": "american"})
    rem, used = headers.get("x-requests-remaining"), headers.get("x-requests-used")
    with _lock:
        if rem is not None:
            _budget.update(remaining=int(float(rem)), used=int(float(used or 0)), at=time.time())
        lines = _parse(json.loads(body))
        _lines[league] = (time.time(), lines)
    return lines


def lines(league: str, sport_key: str, viewing: bool = True, force: bool = False) -> tuple[list[dict], float]:
    """(lines, when fetched). Fetches only when someone is viewing this league and it's due
    by the budget (or force=True for "Update odds now")."""
    if not key():
        return [], 0.0
    now = time.time()
    if viewing:
        _viewed[league] = now
    fetched_at, cached = _lines.get(league, (0.0, []))
    due = now - fetched_at >= gap(now)
    if viewing and (force or due):
        try:
            return _fetch(league, sport_key), time.time()
        except Exception:  # noqa: BLE001 (keep showing the last lines)
            pass
    return cached, fetched_at


# ---------- "More bets": player props, halves/quarters/periods, alternate lines, team totals ----------
# Only fetched when you open them for a game. The Odds API bills each market that returns
# prices, per region, so a group costs at most as many credits as it has markets.

EVENT_ODDS = "https://api.the-odds-api.com/v4/sports/{}/events/{}/odds"

_FOOTBALL = {
    "Player props": ["player_pass_yds", "player_pass_tds", "player_rush_yds", "player_receptions",
                     "player_reception_yds", "player_anytime_td"],
    "1st half": ["h2h_h1", "spreads_h1", "totals_h1"],
    "1st quarter": ["h2h_q1", "spreads_q1", "totals_q1"],
    "Alternate lines": ["alternate_spreads", "alternate_totals"],
    "Team totals": ["team_totals"],
}
_BASKETBALL = {
    "Player props": ["player_points", "player_rebounds", "player_assists", "player_threes",
                     "player_points_rebounds_assists"],
    "1st half": ["h2h_h1", "spreads_h1", "totals_h1"],
    "1st quarter": ["h2h_q1", "spreads_q1", "totals_q1"],
    "Alternate lines": ["alternate_spreads", "alternate_totals"],
    "Team totals": ["team_totals"],
}
MARKET_GROUPS = {
    "nfl": _FOOTBALL,
    "ncaaf": _FOOTBALL,
    "nba": _BASKETBALL,
    "ncaab": {k: v for k, v in _BASKETBALL.items() if k != "1st quarter"},  # college basketball plays halves
    "mlb": {
        "Player props": ["batter_home_runs", "batter_hits", "batter_total_bases", "batter_rbis", "pitcher_strikeouts"],
        "First 5 innings": ["h2h_1st_5_innings", "spreads_1st_5_innings", "totals_1st_5_innings"],
        "Alternate lines": ["alternate_spreads", "alternate_totals"],
        "Team totals": ["team_totals"],
    },
    "nhl": {
        "Player props": ["player_points", "player_goal_scorer_anytime", "player_shots_on_goal", "player_assists"],
        "1st period": ["h2h_p1", "spreads_p1", "totals_p1"],
        "Alternate lines": ["alternate_spreads", "alternate_totals"],
        "Team totals": ["team_totals"],
    },
    "ufc": {},
}

LABELS = {
    "player_pass_yds": "Passing yards", "player_pass_tds": "Passing TDs", "player_rush_yds": "Rushing yards",
    "player_receptions": "Receptions", "player_reception_yds": "Receiving yards", "player_anytime_td": "Anytime TD",
    "player_points": "Points", "player_rebounds": "Rebounds", "player_assists": "Assists", "player_threes": "3-pointers made",
    "player_points_rebounds_assists": "Pts + Reb + Ast", "batter_home_runs": "Home runs", "batter_hits": "Hits",
    "batter_total_bases": "Total bases", "batter_rbis": "RBIs", "pitcher_strikeouts": "Pitcher strikeouts",
    "player_goal_scorer_anytime": "Anytime goal", "player_shots_on_goal": "Shots on goal",
    "h2h_h1": "1st half moneyline", "spreads_h1": "1st half spread", "totals_h1": "1st half total",
    "h2h_q1": "1st quarter moneyline", "spreads_q1": "1st quarter spread", "totals_q1": "1st quarter total",
    "h2h_p1": "1st period moneyline", "spreads_p1": "1st period spread", "totals_p1": "1st period total",
    "h2h_1st_5_innings": "First 5 moneyline", "spreads_1st_5_innings": "First 5 run line",
    "totals_1st_5_innings": "First 5 total", "alternate_spreads": "Alternate spreads",
    "alternate_totals": "Alternate totals", "team_totals": "Team totals",
}

_more: dict[tuple, tuple[float, dict]] = {}
MORE_TTL = 120  # a double click doesn't pay twice


def groups(league: str) -> list[dict]:
    return [{"name": n, "markets": len(m)} for n, m in MARKET_GROUPS.get(league, {}).items()]


def _parse_event(ev: dict) -> list[dict]:
    """{market: {(player or team, side, line): {book: price}}} → rows with the best price first."""
    found: dict[str, dict[tuple, dict]] = {}
    for bm in ev.get("bookmakers", []):
        book = bm.get("title", bm.get("key"))
        for m in bm.get("markets", []):
            for oc in m.get("outcomes", []):
                who = oc.get("description") or ""  # props: the player; otherwise empty
                k = (who, oc.get("name", ""), oc.get("point"))
                found.setdefault(m["key"], {}).setdefault(k, {})[book] = oc.get("price")
    markets = []
    for key, rows in found.items():
        out = []
        for (who, side, point), prices in rows.items():
            best_book, best = max(prices.items(), key=lambda kv: kv[1] if kv[1] is not None else -10 ** 9)
            out.append({"player": who, "side": side, "point": point, "best": {"price": best, "book": best_book},
                        "books": [{"book": b, "price": p} for b, p in sorted(prices.items())]})
        out.sort(key=lambda r: (r["player"], r["side"] not in ("Over", "Yes"), r["side"], r["point"] if r["point"] is not None else 0))
        markets.append({"key": key, "label": LABELS.get(key, key.replace("_", " ").title()), "rows": out})
    order = list(LABELS)
    markets.sort(key=lambda m: order.index(m["key"]) if m["key"] in order else len(order))
    return markets


def more_bets(league: str, sport_key: str, event_id: str, group: str, force: bool = False) -> dict:
    """One group of extra markets for one game. Spends credits (at most one per market in the group)."""
    if not key():
        raise OddsError("Add an Odds API key under ⚙ → Live data first.")
    if not re.fullmatch(r"[A-Za-z0-9]{1,64}", event_id or ""):
        raise OddsError("That game has no odds ID; refresh the page and try again.")
    markets = MARKET_GROUPS.get(league, {}).get(group)
    if not markets:
        raise OddsError("Those bets aren't available for this league.")
    cache_key = (event_id, group)
    hit = _more.get(cache_key)
    if hit and not force and time.time() - hit[0] < MORE_TTL:
        return {**hit[1], "cached": True}
    if _budget["remaining"] is not None and _budget["remaining"] < len(markets):
        raise OddsError(f"Only {_budget['remaining']} odds credits left this month; this needs up to {len(markets)}.")
    try:
        body, headers = get_with_headers(EVENT_ODDS.format(sport_key, event_id), {
            "apiKey": key(), "regions": "us", "markets": ",".join(markets), "oddsFormat": "american"})
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None)
        if code in (401, 403):
            raise OddsError("Your Odds API plan doesn't include these bets, or the key was refused.") from e
        if code == 404:
            raise OddsError("The sportsbooks aren't offering these for this game (yet).") from e
        if code == 422:
            raise OddsError("These bets aren't offered for this game.") from e
        if code == 429:
            raise OddsError("Out of odds credits (or too many requests). Try again later.") from e
        raise OddsError(f"Couldn't reach The Odds API ({getattr(e, 'reason', e)}).") from e
    rem, last = headers.get("x-requests-remaining"), headers.get("x-requests-last")
    with _lock:
        if rem is not None:
            _budget.update(remaining=int(float(rem)), used=int(float(headers.get("x-requests-used") or 0)), at=time.time())
    result = {"markets": _parse_event(json.loads(body)), "fetched_at": time.time(),
              "cost": int(float(last)) if last is not None else None, "budget": budget()}
    _more[cache_key] = (time.time(), result)
    return result


class OddsError(Exception):
    pass
