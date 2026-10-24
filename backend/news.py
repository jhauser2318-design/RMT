"""Market news, trading chatter and YouTube videos from popular sources.

Everything is read from the sites' public RSS feeds and Reddit's public
listings, the same way a news reader app does, so nothing breaks when a
site redesigns its pages. Sources that can't be reached are skipped.
"""
import html
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import demo
from .fetch import cached, demo_mode, get_json, get, parse_feed

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

# Popular finance / trading channels. Edit freely: the id is the part after
# /channel/ in a channel's address.
YOUTUBE_CHANNELS = [
    ("CNBC Television", "UCrp_UI8XtuYfpiqluWLD7Lw"),
    ("Bloomberg Television", "UCIALMKvObZNtJ6AmdCLP7Lg"),
    ("Yahoo Finance", "UCEAZeUIeJs0IjQiqTCdVSIg"),
    ("Wall Street Journal", "UCK7tptUDHh-RYDsdxO1-5QQ"),
    ("Graham Stephan", "UCV6KDgJskWaEckne5aPA0aQ"),
    ("Meet Kevin", "UCUvvj5lwue7PspotMDjk5UA"),
    ("Andrei Jikh", "UCGy7SkBjcIAgTiwkXEtPnYg"),
]

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


def _yt_search(query: str, key: str) -> list[dict]:
    data = get_json("https://www.googleapis.com/youtube/v3/search", {
        "part": "snippet", "q": query, "type": "video", "maxResults": 24,
        "order": "relevance", "relevanceLanguage": "en", "key": key,
    })
    out = []
    for it in data.get("items", []):
        sn = it["snippet"]
        vid = it["id"]["videoId"]
        out.append({"title": _clean(sn["title"]), "link": f"https://www.youtube.com/watch?v={vid}",
                    "video_id": vid, "source": sn["channelTitle"],
                    "image": sn["thumbnails"].get("medium", {}).get("url", ""),
                    "time": 0, "published": sn.get("publishedAt", "")})
    return out


def youtube(query: str = "") -> dict:
    """Latest videos from popular finance channels, or a search (needs a key)."""
    if demo_mode():
        return {"live": False, "items": demo.videos(), "searchable": False}
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if query and key:
        try:
            items = cached(f"yt:{query.lower()}", 900, lambda: _yt_search(query, key))
            return {"live": True, "items": items, "searchable": True}
        except Exception:  # noqa: BLE001 (fall back to the channel feeds)
            pass
    feeds = [(n, f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}") for n, cid in YOUTUBE_CHANNELS]
    items = _many(feeds)
    if query:
        words = query.lower().split()
        items = [i for i in items if all(w in i["title"].lower() for w in words)]
    items = items[:36]
    for i in items:
        if i.get("video_id") and not i.get("image"):
            i["image"] = f"https://i.ytimg.com/vi/{i['video_id']}/mqdefault.jpg"
    if not items and not query:
        return {"live": False, "items": demo.videos(), "searchable": bool(key)}
    return {"live": True, "items": items, "searchable": bool(key)}
