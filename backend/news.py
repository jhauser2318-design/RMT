"""Market news, trading chatter and YouTube videos from popular sources.

Everything is read from the sites' public RSS feeds and Reddit's public
listings, the same way a news reader app does, so nothing breaks when a
site redesigns its pages. Sources that can't be reached are skipped.
"""
import html
import os
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import demo
from .fetch import _when as fetch_when
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


def _yt_get(path: str, params: dict, key: str) -> dict:
    return get_json(f"https://www.googleapis.com/youtube/v3/{path}", {**params, "key": key})


def _yt_search(query: str, key: str, popular: bool = False) -> list[dict]:
    params = {"part": "snippet", "q": query, "type": "video", "maxResults": 24, "relevanceLanguage": "en",
              "order": "viewCount" if popular else "relevance"}
    if popular:
        since = time.gmtime(time.time() - POPULAR_DAYS * 86400)
        params["publishedAfter"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", since)
    data = _yt_get("search", params, key)
    out = []
    for it in data.get("items", []):
        sn = it["snippet"]
        vid = it["id"]["videoId"]
        out.append({"title": _clean(sn["title"]), "link": f"https://www.youtube.com/watch?v={vid}",
                    "video_id": vid, "source": sn["channelTitle"],
                    "image": sn["thumbnails"].get("medium", {}).get("url", ""),
                    "time": fetch_when(sn.get("publishedAt", "")), "views": None})
    if out:  # view counts: one cheap extra request for all of them
        stats = _yt_get("videos", {"part": "statistics", "id": ",".join(v["video_id"] for v in out)}, key)
        views = {v["id"]: int(v.get("statistics", {}).get("viewCount", 0)) for v in stats.get("items", [])}
        for v in out:
            v["views"] = views.get(v["video_id"])
    return out


def _channel_videos(tab: str) -> list[dict]:
    if tab == "popular":
        channels = list(dict.fromkeys(YOUTUBE_CHANNELS["investing"] + YOUTUBE_CHANNELS["trading"]))
    else:
        channels = YOUTUBE_CHANNELS.get(tab, YOUTUBE_CHANNELS["investing"])
    return _many([(n, f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}") for n, cid in channels])


def youtube(query: str = "", tab: str = "popular") -> dict:
    """Videos for a tab: "popular" (most-viewed advice this week), "investing", "trading" or "news".
    A query filters them by title, or searches all of YouTube with a YOUTUBE_API_KEY."""
    if demo_mode():
        return {"live": False, "items": demo.videos(), "searchable": False}
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    tab = tab if tab in ("popular", "investing", "trading", "news") else "popular"
    if query and key:
        try:
            items = cached(f"yt:{query.lower()}", 900, lambda: _yt_search(f"{query} stock", key))
            return {"live": True, "items": items, "searchable": True}
        except Exception:  # noqa: BLE001 (fall back to the channel feeds)
            pass
    if query:  # look in every tab's channels
        items = [i for t in YOUTUBE_CHANNELS for i in _channel_videos(t)]
        words = query.lower().split()
        items = [i for i in items if all(w in i["title"].lower() for w in words)]
        items = list({i["link"]: i for i in items}.values())
        items.sort(key=lambda i: -i["time"])
    elif tab == "popular":
        week_ago = time.time() - POPULAR_DAYS * 86400
        items = [i for i in _channel_videos("popular") if i["time"] >= week_ago and i.get("views")]
        if key:
            try:
                items += cached("yt:popular", 3600, lambda: _yt_search(POPULAR_SEARCH, key, popular=True))
            except Exception:  # noqa: BLE001 (the channel feeds still work)
                pass
        items = list({i["link"]: i for i in items}.values())
        items.sort(key=lambda i: -(i.get("views") or 0))
    else:
        items = _channel_videos(tab)
    items = items[:36]
    for i in items:
        if i.get("video_id") and not i.get("image"):
            i["image"] = f"https://i.ytimg.com/vi/{i['video_id']}/mqdefault.jpg"
    if not items and not query:
        return {"live": False, "items": demo.videos(), "searchable": bool(key)}
    return {"live": True, "items": items, "searchable": bool(key)}
