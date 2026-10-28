"""Games, betting odds, standings and stats search.

Games, scores and one sportsbook's line per game come from ESPN's public
scoreboard data (no key needed). With an ODDS_API_KEY from the-odds-api.com,
each game also gets moneyline, spread and total from many US sportsbooks,
and the best price for each side is highlighted.
"""
import re
from concurrent.futures import ThreadPoolExecutor

from datetime import datetime

from . import demo, odds
from .fetch import cached, demo_mode, get_json

LEAGUES = {
    # id: (name, ESPN path, the-odds-api sport key, emoji)
    "nfl": ("NFL", "football/nfl", "americanfootball_nfl", "🏈"),
    "ncaaf": ("College Football", "football/college-football", "americanfootball_ncaaf", "🏈"),
    "nba": ("NBA", "basketball/nba", "basketball_nba", "🏀"),
    "ncaab": ("College Basketball", "basketball/mens-college-basketball", "basketball_ncaab", "🏀"),
    "mlb": ("MLB", "baseball/mlb", "baseball_mlb", "⚾"),
    "nhl": ("NHL", "hockey/nhl", "icehockey_nhl", "🏒"),
    "ufc": ("UFC", "mma/ufc", "mma_mixed_martial_arts", "🥊"),
}

ESPN = "https://site.api.espn.com/apis/site/v2/sports/{}/scoreboard"
STANDINGS = "https://site.api.espn.com/apis/v2/sports/{}/standings"
ODDS = "https://api.the-odds-api.com/v4/sports/{}/odds"


def leagues() -> list[dict]:
    return [{"id": k, "name": v[0], "emoji": v[3]} for k, v in LEAGUES.items()]


def _num(v):
    """American odds as a number: "+150" → 150, "EVEN" → 100, missing → None."""
    if v in (None, "", "OFF"):
        return None
    if str(v).upper() == "EVEN":
        return 100.0
    try:
        return float(str(v).replace("+", ""))
    except ValueError:
        return None


def _side(c: dict) -> dict:
    team = c.get("team") or c.get("athlete") or {}
    recs = c.get("records") or []
    logo = team.get("logo") or (team.get("logos") or [{}])[0].get("href", "") or (team.get("flag") or {}).get("href", "")
    return {
        "name": team.get("displayName") or team.get("fullName") or team.get("name", "?"),
        "short": team.get("shortDisplayName") or team.get("displayName", "?"),
        "abbr": team.get("abbreviation") or team.get("shortName") or "",
        "logo": logo,
        "color": team.get("color") or "",
        "record": recs[0].get("summary", "") if recs else "",
        "score": c.get("score") if isinstance(c.get("score"), str) else "",
        "winner": bool(c.get("winner")),
    }


def _espn_odds(comp: dict) -> dict | None:
    lst = comp.get("odds") or []
    if not lst:
        return None
    o = lst[0]
    home, away = o.get("homeTeamOdds") or {}, o.get("awayTeamOdds") or {}
    ml = o.get("moneyline") or {}

    def close(side, key="odds"):
        part = (ml.get(side) or {}).get("close") or (ml.get(side) or {}).get("open") or {}
        return _num(part.get(key))

    return {
        "provider": (o.get("provider") or {}).get("name", "Sportsbook"),
        "spread": o.get("details") or "",
        "total": o.get("overUnder"),
        "home_ml": _num(home.get("moneyLine")) if home.get("moneyLine") is not None else close("home"),
        "away_ml": _num(away.get("moneyLine")) if away.get("moneyLine") is not None else close("away"),
        "draw_ml": _num((o.get("drawOdds") or {}).get("moneyLine")),
    }


def _parse_espn(league: str, data: dict) -> list[dict]:
    games = []
    for ev in data.get("events", []):
        for i, comp in enumerate(ev.get("competitions", [])[:12]):  # UFC: one card, many fights
            cs = comp.get("competitors", [])
            if len(cs) < 2:
                continue
            home = next((c for c in cs if c.get("homeAway") == "home"), cs[0])
            away = next((c for c in cs if c is not home), cs[1])
            st = (comp.get("status") or ev.get("status") or {}).get("type", {})
            bc = comp.get("broadcasts") or []
            games.append({
                "id": f"{league}-{ev['id']}-{i}",
                "league": league,
                "league_name": LEAGUES[league][0],
                "emoji": LEAGUES[league][3],
                "name": ev.get("shortName") or ev.get("name", ""),
                "start": comp.get("date") or ev.get("date"),
                "state": st.get("state", "pre"),
                "detail": st.get("shortDetail") or st.get("detail", ""),
                "venue": (comp.get("venue") or {}).get("fullName", ""),
                "broadcast": ", ".join(n for b in bc for n in b.get("names", [])),
                "home": _side(home),
                "away": _side(away),
                "odds": _espn_odds(comp),
                "books": [],
                "link": next((l["href"] for l in ev.get("links", []) if "gamecast" in str(l.get("rel"))), ""),
            })
    return games


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _same_team(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a and b) and (a == b or a in b or b in a)


def _best(books: list[dict]) -> dict:
    best = {}
    for k in ("home_ml", "away_ml", "draw_ml", "home_spread_price", "away_spread_price", "over_price", "under_price"):
        vals = [(b[k], b["book"]) for b in books if b.get(k) is not None]
        if vals:
            price, book = max(vals)  # higher American odds always pay more
            best[k] = {"price": price, "book": book}
    return best


def _league_games(league: str, date: str = "", espn_ttl: float = 60, odds_viewing: bool = True,
                  odds_force: bool = False) -> list[dict]:
    path = LEAGUES[league][1]
    params = {"dates": date} if date else {}
    params["limit"] = 300 if league in ("ncaaf", "ncaab") else 100
    if league in ("ncaaf", "ncaab"):
        params["groups"] = "80" if league == "ncaaf" else "50"  # FBS / Division I: every game, not just Top 25
    try:
        data = cached(f"espn:{league}:{date}", espn_ttl, lambda: get_json(ESPN.format(path), params))
        games = _parse_espn(league, data)
    except Exception:  # noqa: BLE001
        games = []
    lines, fetched_at = odds.lines(league, LEAGUES[league][2], viewing=odds_viewing, force=odds_force)
    for line in lines:
        game = next((g for g in games if _same_team(g["home"]["name"], line["home"])
                     and _same_team(g["away"]["name"], line["away"])), None)
        if game is None:
            if date:
                continue  # another day's game
            game = {"id": f"{league}-odds-{_norm(line['home'])}-{_norm(line['away'])}", "league": league,
                    "league_name": LEAGUES[league][0], "emoji": LEAGUES[league][3],
                    "name": f"{line['away']} @ {line['home']}", "start": line["start"], "state": "pre",
                    "detail": "", "venue": "", "broadcast": "", "odds": None, "link": "",
                    "home": {"name": line["home"], "short": line["home"], "abbr": "", "logo": "", "record": "", "score": "", "winner": False, "color": ""},
                    "away": {"name": line["away"], "short": line["away"], "abbr": "", "logo": "", "record": "", "score": "", "winner": False, "color": ""}}
            games.append(game)
        game["books"] = line["books"]
        game["odds_event_id"] = line.get("event_id", "")
        game["best"] = _best(line["books"])
        game["odds_at"] = fetched_at
        # Fetched after kickoff = live, in-play prices.
        game["odds_live"] = game["state"] == "in" and fetched_at > _epoch(game.get("start"))
    return games


def _epoch(iso: str | None) -> float:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def games(league: str = "all", date: str = "", force_odds: bool = False, spend_odds: bool = True) -> dict:
    """Games for one league (or every league), soonest and live first."""
    ids = list(LEAGUES) if league == "all" else [league] if league in LEAGUES else []
    if demo_mode():
        return {"live": False, "games": demo.games(ids), "multi_book": False}
    # "All sports" never spends odds credits: it shows what each league last fetched.
    # spend_odds=False (the AI chat) does the same for one league.
    viewing = league != "all" and spend_odds
    with ThreadPoolExecutor(max_workers=12) as pool:
        lists = list(pool.map(lambda l: _league_games(l, date, odds_viewing=viewing, odds_force=force_odds), ids))
    out = [g for lst in lists for g in lst]
    if not out:
        return {"live": False, "games": demo.games(ids), "multi_book": False}
    return {"live": True, "games": sort_games(out), "multi_book": bool(odds.key()), "odds_budget": odds.budget()}


def sort_games(games: list[dict]) -> list[dict]:
    order = {"in": 0, "pre": 1, "post": 2}
    return sorted(games, key=lambda g: (order.get(g["state"], 1), g["start"] or ""))


def standings(league: str) -> dict:
    """League standings tables (wins, losses, etc.) from ESPN."""
    if league not in LEAGUES:
        return {"live": False, "groups": []}
    if demo_mode():
        return {"live": False, "groups": demo.standings(league)}

    def load():
        data = get_json(STANDINGS.format(LEAGUES[league][1]))
        groups = []

        def walk(node, title):
            for child in node.get("children", []):
                walk(child, child.get("name") or title)
            entries = (node.get("standings") or {}).get("entries")
            if entries:
                cols, rows = [], []
                for e in entries:
                    stats = {s.get("abbreviation") or s.get("name"): s.get("displayValue") for s in e.get("stats", [])}
                    if not cols:
                        want = ["W", "L", "T", "OTL", "PCT", "GB", "GP", "D", "PTS", "STRK", "DIFF", "PF", "PA"]
                        cols = [c for c in want if c in stats]
                    t = e.get("team", {})
                    rows.append({"team": t.get("displayName", "?"), "logo": (t.get("logos") or [{}])[0].get("href", ""),
                                 "stats": [stats.get(c, "") for c in cols]})
                groups.append({"name": node.get("name") or title, "columns": cols, "rows": rows})
        walk(data, LEAGUES[league][0])
        return groups
    try:
        return {"live": True, "groups": cached(f"standings:{league}", 1800, load)}
    except Exception:  # noqa: BLE001
        return {"live": False, "groups": demo.standings(league)}


def search(query: str) -> dict:
    """Players and teams matching the query, with links to their ESPN pages."""
    query = (query or "").strip()
    if not query:
        return {"live": True, "items": []}
    if demo_mode():
        return {"live": False, "items": demo.search(query)}

    def load():
        data = get_json("https://site.web.api.espn.com/apis/search/v2", {"query": query, "limit": 10})
        found = []

        def walk(node):  # the result layout varies by sport, so look for anything with a name and a page
            if isinstance(node, dict):
                name = node.get("displayName")
                link = node.get("link")
                web = link.get("web") if isinstance(link, dict) else link if isinstance(link, str) else ""
                if name and web and web.startswith("http"):
                    img = node.get("image")
                    found.append({"name": name, "link": web, "type": node.get("type", ""),
                                  "detail": node.get("subtitle") or node.get("description") or node.get("sport", ""),
                                  "image": img.get("default", "") if isinstance(img, dict) else img or ""})
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(data)
        seen, out = set(), []
        for f in found:
            if f["link"] not in seen and f["type"] in ("player", "team", ""):
                seen.add(f["link"])
                out.append(f)
        return out[:15]
    try:
        return {"live": True, "items": cached(f"search:{query.lower()}", 900, load)}
    except Exception:  # noqa: BLE001
        return {"live": False, "items": demo.search(query)}
