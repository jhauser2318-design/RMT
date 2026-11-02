"""Market news, trading chatter and YouTube videos from popular sources.

Everything is read from the sites' public RSS feeds and Reddit's public
listings, the same way a news reader app does, so nothing breaks when a
site redesigns its pages. Sources that can't be reached are skipped.
"""
import html
import os
import json
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from pathlib import Path

from . import demo, youtube
from .fetch import cached, demo_mode, get, get_json, parse_feed

NEWS_FEEDS = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC Markets", "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("Seeking Alpha", "https://seekingalpha.com/market_currents.xml"),
    ("Investing.com", "https://www.investing.com/rss/news_25.rss"),
    ("Nasdaq", "https://www.nasdaq.com/feed/rssoutbound?category=Markets"),
    ("Benzinga", "https://www.benzinga.com/feed"),
]

SUBREDDITS = ["wallstreetbets", "stocks", "investing", "options", "Daytrading", "StockMarket"]

# YouTube channels, by tab. Edit freely: the id is the part after /channel/ in a
# channel's address. "Popular" ranks the investing and day-trading channels'
# videos from the last week by views.
YOUTUBE_CHANNELS = {
    "investing": [
        ("Graham Stephan", "UCV6KDgJskWaEckne5aPA0aQ"),
        ("Andrei Jikh", "UCGy7SkBjcIAgTiwkXEtPnYg"),
        ("Humphrey Yang", "UCFBpVaKCC0ajGps1vf0AgBg"),
        ("Minority Mindset", "UCT3EznhW_CNFcfOlyDNTLLw"),
        ("Financial Education", "UCnMn36GT_H0X-w5_ckLtlgQ"),
        ("Ticker Symbol: YOU", "UC7kCeZ53sli_9XwuQeFxLqw"),
        ("Meet Kevin", "UCUvvj5lwue7PspotMDjk5UA"),
    ],
    "trading": [
        ("Ross Cameron - Warrior Trading", "UCBayuhgYpKNbhJxfExYkPfA"),
        ("Humbled Trader", "UCcIvNGMBSQWwo1v3n-ZRBCw"),
        ("Meet Kevin", "UCUvvj5lwue7PspotMDjk5UA"),
    ],
    "news": [
        ("CNBC Television", "UCrp_UI8XtuYfpiqluWLD7Lw"),
        ("Bloomberg Television", "UCIALMKvObZNtJ6AmdCLP7Lg"),
        ("Yahoo Finance", "UCEAZeUIeJs0IjQiqTCdVSIg"),
        ("Wall Street Journal", "UCK7tptUDHh-RYDsdxO1-5QQ"),
    ],
}
POPULAR_DAYS = 7
# With a YOUTUBE_API_KEY, "Popular" also searches all of YouTube for these, most viewed this week.
POPULAR_SEARCH = "stock market investing advice"

_TAG = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return html.unescape(_TAG.sub("", s or "")).strip()


def _feed(name: str, url: str) -> list[dict]:
    try:
        items = cached(f"feed:{url}", 300, lambda: parse_feed(get(url)))
    except Exception:  # noqa: BLE001 (a dead feed is skipped)
        return []
    return [{**i, "title": _clean(i["title"]), "summary": _clean(i["summary"])[:280],
             "source": i.get("source") or name} for i in items if i["title"]]


def _many(feeds) -> list[dict]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        lists = pool.map(lambda f: _feed(*f), feeds)
    seen, out = set(), []
    for item in sorted((i for lst in lists for i in lst), key=lambda i: -i["time"]):
        key = item["title"].lower()[:80]
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def headlines(query: str = "", limit: int = 60) -> dict:
    """Top market headlines, or news about one ticker/topic (via Google News)."""
    if demo_mode():
        return {"live": False, "items": demo.news(query)}
    if query:
        q = urllib.parse.quote(f"{query} stock")
        feeds = [("Google News", f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"),
                 ("Yahoo Finance", f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(query)}&region=US&lang=en-US")]
    else:
        feeds = NEWS_FEEDS
    items = _many(feeds)[:limit]
    return {"live": True, "items": items} if items else {"live": False, "items": demo.news(query)}


def _subreddit(name: str, sort: str) -> list[dict]:
    def load():
        data = get_json(f"https://www.reddit.com/r/{name}/{sort}.json", {"limit": 25, "raw_json": 1})
        posts = []
        for child in data["data"]["children"]:
            p = child["data"]
            if p.get("stickied"):
                continue
            posts.append({
                "title": p["title"],
                "link": "https://www.reddit.com" + p["permalink"],
                "time": p.get("created_utc", 0),
                "score": p.get("score", 0),
                "comments": p.get("num_comments", 0),
                "flair": p.get("link_flair_text") or "",
                "source": f"r/{name}",
                "summary": (p.get("selftext") or "")[:280],
            })
        return posts
    try:
        return cached(f"reddit:{name}:{sort}", 300, load)
    except Exception:  # noqa: BLE001
        return []


def trading_talk(sort: str = "hot") -> dict:
    """The most popular posts on the big trading subreddits right now."""
    if demo_mode():
        return {"live": False, "items": demo.reddit()}
    sort = sort if sort in ("hot", "top", "new", "rising") else "hot"
    with ThreadPoolExecutor(max_workers=6) as pool:
        lists = pool.map(lambda s: _subreddit(s, sort), SUBREDDITS)
    items = sorted((p for lst in lists for p in lst), key=lambda p: -p["score"])[:60]
    return {"live": True, "items": items} if items else {"live": False, "items": demo.reddit()}


# Last videos that loaded per channel, so a YouTube feed outage doesn't empty the panel.
LAST_FILE = Path(__file__).resolve().parent.parent / "data" / "youtube_last.json"
_last: dict[str, dict] = {}
_last_lock = threading.Lock()


def _remember(cid: str, items: list[dict]) -> None:
    with _last_lock:
        if not _last and LAST_FILE.is_file():
            try:
                _last.update(json.loads(LAST_FILE.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                pass
        _last[cid] = {"at": time.time(), "items": items[:15]}
        try:
            LAST_FILE.parent.mkdir(exist_ok=True)
            LAST_FILE.write_text(json.dumps(_last), encoding="utf-8")
        except OSError:
            pass


def _recall(cid: str) -> list[dict]:
    with _last_lock:
        if not _last and LAST_FILE.is_file():
            try:
                _last.update(json.loads(LAST_FILE.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                pass
        return list((_last.get(cid) or {}).get("items", []))


def _yt_channel(name: str, cid: str) -> tuple[list[dict], bool]:
    """(videos, came from the live feed?) for one channel."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    try:
        items = cached(f"feed:{url}", 300, lambda: parse_feed(get(url)))
    except Exception:  # noqa: BLE001 (YouTube's feeds fail on and off)
        return [], False
    items = [{**i, "title": _clean(i["title"]), "summary": _clean(i["summary"])[:280], "source": i.get("source") or name}
             for i in items if i["title"]]
    if items:
        _remember(cid, items)
    return items, bool(items)


def _channel_videos(tab: str) -> tuple[list[dict], dict]:
    """Videos for a tab's channels, and how they were fetched: {"failed", "api", "stale"} counts."""
    if tab == "popular":
        channels = list(dict.fromkeys(YOUTUBE_CHANNELS["investing"] + YOUTUBE_CHANNELS["trading"]))
    else:
        channels = YOUTUBE_CHANNELS.get(tab, YOUTUBE_CHANNELS["investing"])
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda c: _yt_channel(*c), channels))
    items = [i for lst, _ in results for i in lst]
    failed = [cid for (name, cid), (_, ok) in zip(channels, results) if not ok]
    how = {"failed": len(failed), "api": 0, "stale": 0}
    if failed and youtube.available():  # the official API, when signed in (or with an API key)
        try:
            got = youtube.channel_videos(failed)
            items += got
            how["api"] = len({v["source"] for v in got})
            for cid in failed:
                _remember(cid, [v for v in got if v.get("channel_id") == cid] or _recall(cid))
            failed = []
        except youtube.YouTubeError:
            pass
    for cid in failed:  # still nothing: the last videos that did load
        old = _recall(cid)
        if old:
            items += old
            how["stale"] += 1
    return list({i["link"]: i for i in items}.values()), how


def _note(how: dict) -> str:
    if not how.get("failed"):
        return ""
    if how.get("api"):
        return ""
    if how.get("stale"):
        return ("YouTube's free channel feeds aren't answering right now (a known YouTube problem), so some videos "
                "are from the last time they loaded. Sign in with Google under ⚙ → YouTube for a reliable connection.")
    return ("YouTube's free channel feeds aren't answering right now (a known YouTube problem). "
            "Sign in with Google under ⚙ → YouTube for a reliable connection.")


def youtube_videos(query: str = "", tab: str = "popular") -> dict:
    """Videos for a tab: "popular" (most-viewed advice this week), "investing", "trading", "news",
    or "subs" (your subscriptions, when signed in). A query filters by title, or searches all
    of YouTube through the API."""
    if demo_mode():
        return {"live": False, "items": demo.videos(), "searchable": False, "signed_in": False}
    tab = tab if tab in ("popular", "investing", "trading", "news", "subs") else "popular"
    base = {"searchable": youtube.available(), "signed_in": youtube.signed_in(), "note": ""}
    if query and youtube.available():
        try:
            return {**base, "live": True, "items": youtube.search(f"{query} stock")}
        except youtube.YouTubeError as e:
            base["note"] = str(e)
    if tab == "subs" and not query:
        if not youtube.signed_in():
            return {**base, "live": False, "items": [], "note": "Sign in with Google under ⚙ → YouTube to see your subscriptions."}
        try:
            subs = youtube.subscriptions()
            items = youtube.channel_videos(subs[:60], per_channel=3)
        except youtube.YouTubeError as e:
            return {**base, "live": False, "items": [], "note": str(e)}
        items.sort(key=lambda i: -i["time"])
        return {**base, "live": True, "items": items[:48],
                "note": "" if subs else "You're not subscribed to any channels on YouTube yet."}
    if query:  # no API: look in every tab's channels
        items, how = [], {"failed": 0}
        for t in ("investing", "trading", "news"):
            got, h = _channel_videos(t)
            items += got
            how["failed"] += h["failed"]
            how["stale"] = how.get("stale", 0) + h["stale"]
        words = query.lower().split()
        items = [i for i in items if all(w in i["title"].lower() for w in words)]
        items = list({i["link"]: i for i in items}.values())
        items.sort(key=lambda i: -i["time"])
    elif tab == "popular":
        items, how = _channel_videos("popular")
        week_ago = time.time() - POPULAR_DAYS * 86400
        items = [i for i in items if i["time"] >= week_ago and i.get("views")]
        if youtube.available():
            try:
                items += youtube.search(POPULAR_SEARCH, popular_days=POPULAR_DAYS)
            except youtube.YouTubeError:
                pass
        items = list({i["link"]: i for i in items}.values())
        items.sort(key=lambda i: -(i.get("views") or 0))
    else:
        items, how = _channel_videos(tab)
        items.sort(key=lambda i: -i["time"])
    items = items[:36]
    for i in items:
        if i.get("video_id") and not i.get("image"):
            i["image"] = f"https://i.ytimg.com/vi/{i['video_id']}/mqdefault.jpg"
    note = base["note"] or _note(how)
    if not items and not query:
        return {**base, "live": False, "items": demo.videos(), "note": note or "No videos right now."}
    return {**base, "live": True, "items": items, "note": note}

