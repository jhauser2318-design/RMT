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
        out.append({"home": ev["home_team"], "away": ev["away_team"], "start": ev["commence_time"], "books": books})
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
