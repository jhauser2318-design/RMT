"""Sample data, shown when the live sources can't be reached (or RMT_DEMO=1).

The page labels it "Sample data" so it's never mistaken for real prices
or real odds.
"""
import hashlib
import math
import random
import time
from datetime import datetime, timedelta, timezone

BASE = {
    "^GSPC": 6050, "^IXIC": 19800, "^DJI": 44100, "^RUT": 2350, "^VIX": 16.2, "ES=F": 6065,
    "NQ=F": 21500, "YM=F": 44250, "^TNX": 4.21, "DX-Y.NYB": 103.4, "AAPL": 238, "MSFT": 432,
    "NVDA": 141, "GOOGL": 178, "AMZN": 214, "META": 598, "TSLA": 352, "AVGO": 231, "BRK-B": 468,
    "JPM": 247, "LLY": 802, "V": 316, "WMT": 92, "XOM": 113, "NFLX": 905, "COST": 948, "AMD": 126,
    "PLTR": 71, "SMCI": 34, "COIN": 298, "MSTR": 362, "HOOD": 41, "SOFI": 15.6, "RIVN": 13.1,
    "GME": 28.4, "AMC": 4.6, "MARA": 21.3, "RIOT": 11.8, "NIO": 4.4, "ARM": 142, "RDDT": 163,
    "IONQ": 38, "SPY": 603, "VOO": 552, "QQQ": 521, "IWM": 233, "DIA": 441, "TQQQ": 83, "SQQQ": 7.6,
    "SOXL": 29, "ARKK": 61, "XLF": 49, "XLE": 92, "TLT": 92, "GLD": 243, "BTC-USD": 98200,
    "ETH-USD": 3420, "SOL-USD": 214, "XRP-USD": 2.31, "DOGE-USD": 0.38, "ADA-USD": 1.02,
    "AVAX-USD": 44, "LINK-USD": 23.5, "CL=F": 70.2, "GC=F": 2650, "SI=F": 30.8, "NG=F": 3.2,
    "HG=F": 4.12, "EURUSD=X": 1.05, "JPY=X": 154.2, "GBPUSD=X": 1.27,
}


def _rng(*parts) -> random.Random:
    seed = int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)
    return random.Random(seed)


def quote(symbol: str) -> dict:
    # Changes a little every minute so the ribbon looks alive.
    r = _rng(symbol, int(time.time() // 60))
    base = BASE.get(symbol, 20 + _rng(symbol).random() * 180)
    pct = r.gauss(0, 2.4 if symbol in ("GME", "AMC", "MSTR", "SMCI", "COIN") else 1.1)
    price = base * (1 + pct / 100)
    walk, spark = base, []
    for i in range(40):
        walk += (price - base) / 40 + r.gauss(0, base * 0.0015)
        spark.append(round(walk, 4))
    return {"symbol": symbol, "name": symbol, "price": round(price, 4), "change": round(price - base, 4),
            "pct": round(pct, 2), "currency": "USD", "spark": spark}


def _ago(minutes: float) -> float:
    return time.time() - minutes * 60


def news(query: str = "") -> list[dict]:
    q = query.upper() or "Stocks"
    rows = [
        ("CNBC", f"{q} rally extends as traders price in a December rate cut"),
        ("MarketWatch", "Here's what to watch as megacap earnings hit this week"),
        ("Yahoo Finance", "Nvidia's next leg: what options traders are betting on"),
        ("Seeking Alpha", "Small caps break out: is the Russell 2000 finally leading?"),
        ("Benzinga", "Unusual options activity spotted in Palantir, Coinbase and SoFi"),
        ("Investing.com", "Oil slips as inventories build; gold holds near record"),
        ("CNBC Markets", "Bitcoin pushes toward six figures as ETF inflows surge"),
        ("Nasdaq", "Pre-market movers: Tesla, AMD, Rivian and more"),
        ("MarketWatch", "The 10-year yield is the number every trader is watching"),
        ("Yahoo Finance", "Retail traders pile into leveraged ETFs at record pace"),
    ]
    return [{"title": t, "link": "https://finance.yahoo.com", "time": _ago(i * 23 + 4), "source": s,
             "summary": "Sample headline. Live headlines appear when RMT can reach the news sites.", "image": ""}
            for i, (s, t) in enumerate(rows)]


def reddit() -> list[dict]:
    rows = [
        ("wallstreetbets", "YOLO update: all in on 0DTE SPY calls 🚀", 18400, 2900, "YOLO"),
        ("Daytrading", "My rules after 3 years: never trade the first 15 minutes", 4200, 610, "Advice"),
        ("stocks", "What's everyone's highest-conviction pick for 2027?", 3100, 1800, "Discussion"),
        ("options", "Explain like I'm 5: why IV crush ate my earnings play", 2600, 420, "Education"),
        ("investing", "Index funds vs. picking stocks: 10-year results", 2200, 980, "Discussion"),
        ("StockMarket", "Fed minutes takeaways in one chart", 1900, 300, "News"),
        ("wallstreetbets", "Loss porn: -92% on NVDA puts, AMA", 9600, 1500, "Loss"),
        ("Daytrading", "VWAP + volume: the only two indicators I use", 1500, 270, "Strategy"),
    ]
    return [{"title": t, "link": f"https://www.reddit.com/r/{s}", "time": _ago(i * 41 + 9), "score": sc,
             "comments": c, "flair": f, "source": f"r/{s}", "summary": ""}
            for i, (s, t, sc, c, f) in enumerate(rows)]


def videos() -> list[dict]:
    rows = [
        ("CNBC Television", "Market close: stocks end higher led by chips"),
        ("Bloomberg Television", "Bloomberg Markets: the open"),
        ("Yahoo Finance", "Top trending tickers right now"),
        ("Graham Stephan", "The stock market is about to change"),
        ("Meet Kevin", "Live: Fed decision reaction"),
        ("Andrei Jikh", "How I'd invest $10,000 right now"),
    ]
    return [{"title": t, "link": "https://www.youtube.com/results?search_query=" + t.replace(" ", "+"),
             "source": s, "image": "", "time": _ago(i * 95 + 30), "video_id": ""} for i, (s, t) in enumerate(rows)]


TEAMS = {
    "nfl": [("Kansas City Chiefs", "KC"), ("Buffalo Bills", "BUF"), ("Philadelphia Eagles", "PHI"),
            ("Detroit Lions", "DET"), ("Baltimore Ravens", "BAL"), ("San Francisco 49ers", "SF"),
            ("Dallas Cowboys", "DAL"), ("Green Bay Packers", "GB"), ("Miami Dolphins", "MIA"), ("Cincinnati Bengals", "CIN")],
    "nba": [("Boston Celtics", "BOS"), ("Denver Nuggets", "DEN"), ("Los Angeles Lakers", "LAL"),
            ("Oklahoma City Thunder", "OKC"), ("New York Knicks", "NY"), ("Golden State Warriors", "GS"),
            ("Milwaukee Bucks", "MIL"), ("Dallas Mavericks", "DAL")],
    "nhl": [("Edmonton Oilers", "EDM"), ("Florida Panthers", "FLA"), ("New York Rangers", "NYR"),
            ("Colorado Avalanche", "COL"), ("Toronto Maple Leafs", "TOR"), ("Dallas Stars", "DAL")],
    "ncaaf": [("Georgia Bulldogs", "UGA"), ("Ohio State Buckeyes", "OSU"), ("Texas Longhorns", "TEX"),
              ("Oregon Ducks", "ORE"), ("Alabama Crimson Tide", "ALA"), ("Notre Dame Fighting Irish", "ND")],
    "mlb": [("Los Angeles Dodgers", "LAD"), ("New York Yankees", "NYY"), ("Atlanta Braves", "ATL"), ("Houston Astros", "HOU")],
}
NAMES = {"nfl": ("NFL", "🏈"), "nba": ("NBA", "🏀"), "nhl": ("NHL", "🏒"), "ncaaf": ("College Football", "🏈"),
         "mlb": ("MLB", "⚾")}
BOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN BET", "BetRivers"]


def _ml_from_spread(spread: float) -> tuple[int, int]:
    p = 1 / (1 + math.exp(spread / 5.5))  # chance the home side wins, from the spread
    def american(prob):
        return int(round(-100 * prob / (1 - prob))) if prob >= 0.5 else int(round(100 * (1 - prob) / prob))
    return american(p), american(1 - p)


def games(ids: list[str]) -> list[dict]:
    out = []
    now = datetime.now(timezone.utc)
    for lg in ids:
        if lg not in TEAMS:
            continue
        r = _rng(lg, now.date().isoformat())
        teams = TEAMS[lg][:]
        r.shuffle(teams)
        for i in range(0, len(teams) - 1, 2):
            (hn, ha), (an, aa) = teams[i], teams[i + 1]
            state = ["in", "pre", "pre", "post"][(i // 2) % 4]
            spread = round(r.uniform(-9, 9) * 2) / 2 or -1.5
            if lg in ("mlb", "nhl"):
                spread = -1.5 if spread < 0 else 1.5
            total = {"nfl": 45.5, "ncaaf": 52.5, "nba": 224.5, "nhl": 6.5, "mlb": 8.5}[lg] + r.choice([-3, -1, 0, 1, 2])
            hml, aml = _ml_from_spread(spread)
            start = now + timedelta(hours={"in": -1, "pre": 3 + i, "post": -5}[state])
            hs, as_ = (str(r.randint(10, 31)), str(r.randint(7, 28))) if state != "pre" else ("", "")
            books = []
            for b in BOOKS:
                j = r.choice([-10, -5, 0, 5, 10])
                books.append({"book": b, "home_ml": hml + j, "away_ml": aml - j, "home_spread": spread,
                              "home_spread_price": -110 + r.choice([-5, 0, 5]), "away_spread": -spread,
                              "away_spread_price": -110 + r.choice([-5, 0, 5]), "total": total,
                              "over_price": -110 + r.choice([-5, 0, 5]), "under_price": -110 + r.choice([-5, 0, 5])})
            from .sports import _best
            fav = ha if spread < 0 else aa
            out.append({
                "id": f"{lg}-demo-{i}", "league": lg, "league_name": NAMES[lg][0], "emoji": NAMES[lg][1],
                "name": f"{aa} @ {ha}", "start": start.isoformat(), "state": state,
                "detail": {"in": "Q3 8:42" if lg in ("nfl", "ncaaf", "nba") else "2nd", "pre": "Scheduled", "post": "Final"}[state],
                "venue": "", "broadcast": r.choice(["ESPN", "FOX", "CBS", "NBC", "Prime Video", "TNT"]),
                "home": {"name": hn, "short": hn.split()[-1], "abbr": ha, "logo": "", "color": "", "record": f"{r.randint(3, 9)}-{r.randint(1, 6)}", "score": hs, "winner": state == "post" and int(hs) > int(as_)},
                "away": {"name": an, "short": an.split()[-1], "abbr": aa, "logo": "", "color": "", "record": f"{r.randint(3, 9)}-{r.randint(1, 6)}", "score": as_, "winner": state == "post" and int(as_) > int(hs)},
                "odds": {"provider": "Sample book", "spread": f"{fav} {-abs(spread)}", "total": total, "home_ml": hml, "away_ml": aml, "draw_ml": None},
                "books": books, "best": _best(books), "link": "",
            })
    return out


def standings(league: str) -> list[dict]:
    teams = TEAMS.get(league, TEAMS["nfl"])
    r = _rng("standings", league)
    rows = []
    for name, _ in teams:
        w = r.randint(2, 10)
        l = r.randint(1, 8)
        rows.append({"team": name, "logo": "", "stats": [str(w), str(l), f"{w / (w + l):.3f}"[1:]]})
    rows.sort(key=lambda x: -int(x["stats"][0]))
    return [{"name": f"{NAMES.get(league, ('League',))[0]} (sample)", "columns": ["W", "L", "PCT"], "rows": rows}]


def search(query: str) -> list[dict]:
    q = query.replace(" ", "+")
    return [{"name": f"Search ESPN for “{query}”", "link": f"https://www.espn.com/search/_/q/{q}",
             "type": "", "detail": "Live search appears when RMT can reach ESPN", "image": ""}]


STOCK_NAMES = {"AAPL": "Apple Inc.", "MSFT": "Microsoft Corporation", "NVDA": "NVIDIA Corporation", "TSLA": "Tesla, Inc.",
         "AMZN": "Amazon.com, Inc.", "GOOGL": "Alphabet Inc.", "META": "Meta Platforms, Inc.", "AMD": "Advanced Micro Devices",
         "PLTR": "Palantir Technologies", "SPY": "SPDR S&P 500 ETF", "VOO": "Vanguard S&P 500 ETF", "QQQ": "Invesco QQQ Trust"}


def stock_search(query: str) -> list[dict]:
    q = query.strip().upper()
    hits = [s for s, n in STOCK_NAMES.items() if s.startswith(q) or q in n.upper()] or ([q] if q.isalpha() and len(q) <= 5 else [])
    return [{"symbol": s, "name": STOCK_NAMES.get(s, s), "exchange": "Sample", "type": "ETF" if s in ("SPY", "VOO", "QQQ") else "Stock"}
            for s in hits[:8]]


def stock_chart(symbol: str, rng: str) -> dict:
    n = {"1d": 78, "5d": 130, "1mo": 150, "6mo": 126, "ytd": 200, "1y": 252, "5y": 260}.get(rng, 78)
    step = {"1d": 300, "5d": 900, "1mo": 3600, "6mo": 86400, "ytd": 86400, "1y": 86400, "5y": 604800}.get(rng, 300)
    q = quote(symbol)
    r = _rng(symbol, rng)
    price, pts, now = q["price"], [], int(time.time())
    for i in range(n):
        pts.append([now - (n - i) * step, round(price, 4)])
        price *= 1 + r.gauss(0.0004, 0.006 if rng in ("1d", "5d") else 0.015)
    scale = q["price"] / pts[-1][1]
    pts = [[t, round(p * scale, 4)] for t, p in pts]
    return {"symbol": symbol, "range": rng, "points": pts, "prev_close": q["price"] - q["change"] if rng == "1d" else None,
            "meta": {}}


def stock_details(symbol: str) -> dict:
    q = quote(symbol)
    return {"symbol": symbol, "name": STOCK_NAMES.get(symbol, symbol) + " (sample)", "exchange": "Sample data", "currency": "USD",
            "type": "", "stats": [{"label": "Previous close", "value": f"{q['price'] - q['change']:,.2f}"},
                                  {"label": "Market cap", "value": "—"}],
            "profile": {}, "full_stats": False}
