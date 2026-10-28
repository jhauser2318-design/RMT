"""Downloading from the web, with a short memory so pages refresh cheaply.

Every source (quotes, news, odds) is fetched through here. Results are kept
for a few seconds to minutes, so many browser refreshes cost one download.
"""
import json
import os
import ssl
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36 RMT/0.1")

_ctx = None
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def demo_mode() -> bool:
    return os.getenv("RMT_DEMO", "0").strip() in ("1", "true", "yes")


def _ssl() -> ssl.SSLContext:
    global _ctx
    if _ctx is None:
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(cafile=certifi.where())
        except Exception:  # noqa: BLE001 (certifi missing: the computer's store alone)
            pass
        _ctx = ctx
    return _ctx


def get(url: str, params: dict | None = None, timeout: float = 10, headers: dict | None = None) -> bytes:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl()) as res:
        return res.read()


def get_json(url: str, params: dict | None = None, timeout: float = 10, headers: dict | None = None):
    return json.loads(get(url, params, timeout, headers))


def cached(key: str, ttl: float, fn):
    """fn()'s result, reused for ttl seconds. Failures are not cached."""
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _lock:
        _cache[key] = (now, value)
    return value


def forget(prefix: str) -> None:
    """Drop saved results whose key starts with prefix (the Refresh button)."""
    with _lock:
        for key in [k for k in _cache if k.startswith(prefix)]:
            del _cache[key]


def _text(el, *names):
    for n in names:
        found = el.find(n)
        if found is not None:
            if found.text and found.text.strip():
                return found.text.strip()
            if found.get("href"):
                return found.get("href")
    return ""


def _when(raw: str) -> float:
    if not raw:
        return 0
    try:
        return parsedate_to_datetime(raw).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def _views(entry) -> int | None:
    """YouTube feeds carry each video's view count in media:group/media:community/media:statistics."""
    stats = entry.find(f".//{MEDIA}statistics")
    try:
        return int(stats.get("views")) if stats is not None else None
    except (TypeError, ValueError):
        return None


ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"
YT = "{http://www.youtube.com/xml/schemas/2015}"


def parse_feed(data: bytes) -> list[dict]:
    """Items from an RSS or Atom feed: title, link, time, summary, image."""
    root = ET.fromstring(data)
    items = []
    for it in root.iter("item"):  # RSS 2.0
        # (Not `a or b`: an element with no children counts as False.)
        img = next((e for e in (it.find(f"{MEDIA}content"), it.find(f"{MEDIA}thumbnail"),
                                it.find("enclosure")) if e is not None), None)
        items.append({
            "title": _text(it, "title"),
            "link": _text(it, "link"),
            "time": _when(_text(it, "pubDate")),
            "summary": _text(it, "description")[:400],
            "source": _text(it, "source"),
            "image": img.get("url") if img is not None else "",
        })
    for it in root.iter(f"{ATOM}entry"):  # Atom (YouTube, Reddit)
        link = it.find(f"{ATOM}link")
        thumb = it.find(f".//{MEDIA}thumbnail")
        items.append({
            "title": _text(it, f"{ATOM}title"),
            "link": link.get("href") if link is not None else "",
            "time": _when(_text(it, f"{ATOM}published", f"{ATOM}updated")),
            "summary": _text(it, f".//{MEDIA}description", f"{ATOM}content")[:400],
            "source": _text(it, f"{ATOM}author/{ATOM}name"),
            "image": thumb.get("url") if thumb is not None else "",
            "video_id": _text(it, f"{YT}videoId"),
            "views": _views(it),
        })
    return items
