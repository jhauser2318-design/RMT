"""Your YouTube account (Sign in with Google) and the official YouTube Data API.

Why: YouTube's free channel feeds (videos.xml) have been failing on and off
since late 2025, which leaves the YouTube panel empty. Signed in, RMT uses the
official API instead, which is reliable, and adds a "My subscriptions" tab.

Setup (once, in your own Google Cloud project; see ⚙ → YouTube for the steps):
YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET from an OAuth client of type
"Desktop app". Sign-in uses Google's flow for desktop apps: a browser
window, a one-time code sent back to RMT on this computer
(http://127.0.0.1:8050/api/youtube/callback), PKCE, and read-only access
(youtube.readonly). The tokens stay in data/youtube_token.json on this PC.

Quota: the API gives each Google project 10,000 units a day. Lists cost 1
unit, a search 100; RMT caches results so normal use stays far below that.
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .fetch import UA, _ssl, cached

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "data" / "youtube_token.json"
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3/"
SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
REDIRECT = "http://127.0.0.1:8050/api/youtube/callback"

_lock = threading.Lock()
_pending: dict[str, tuple[str, float]] = {}  # state -> (PKCE verifier, when)
_last_error = {"text": ""}


class YouTubeError(Exception):
    pass


def client() -> tuple[str, str]:
    return os.getenv("YOUTUBE_CLIENT_ID", "").strip(), os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()


def api_key() -> str:
    return os.getenv("YOUTUBE_API_KEY", "").strip()


def _load() -> dict:
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _store(tok: dict) -> None:
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tok), encoding="utf-8")


def signed_in() -> bool:
    return bool(_load().get("refresh_token")) and all(client())


def available() -> bool:
    """Can RMT use the official API (signed in, or an API key)?"""
    return signed_in() or bool(api_key())


def _open(req: urllib.request.Request):
    """Every request to Google goes through here (tests swap in a fake Google)."""
    return urllib.request.urlopen(req, timeout=15, context=_ssl())


def _post(url: str, form: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(),
                                 headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with _open(req) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("error_description") or ""
        except Exception:  # noqa: BLE001
            detail = ""
        raise YouTubeError(f"Google refused the sign-in ({e.code}{': ' + detail if detail else ''}).") from e


def login_url() -> str:
    cid, secret = client()
    if not (cid and secret):
        raise YouTubeError("Add your Google OAuth client ID and secret under ⚙ → YouTube first.")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    with _lock:
        now = time.time()
        for s in [s for s, (_, t) in _pending.items() if now - t > 900]:
            del _pending[s]
        _pending[state] = (verifier, now)
    return AUTH + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})


def finish_login(code: str, state: str) -> str:
    """Google sent the person back with a one-time code: trade it for tokens. Returns the channel name."""
    with _lock:
        pending = _pending.pop(state or "", None)
    if not pending or time.time() - pending[1] > 900:
        raise YouTubeError("That sign-in link expired or didn't come from RMT. Click Sign in with Google again.")
    cid, secret = client()
    tok = _post(TOKEN, {"client_id": cid, "client_secret": secret, "code": code, "code_verifier": pending[0],
                        "grant_type": "authorization_code", "redirect_uri": REDIRECT})
    if not tok.get("refresh_token"):
        raise YouTubeError("Google didn't give RMT a lasting sign-in. Remove RMT's access in your Google account and try again.")
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    _store(tok)
    cached_name = ""
    try:
        me = get("channels", {"part": "snippet", "mine": "true"})
        cached_name = ((me.get("items") or [{}])[0].get("snippet") or {}).get("title", "")
    except YouTubeError:
        pass
    tok["name"] = cached_name
    _store(tok)
    return cached_name


def sign_out() -> None:
    try:
        TOKEN_FILE.unlink()
    except FileNotFoundError:
        pass


def _access_token() -> str:
    with _lock:
        tok = _load()
        if not tok.get("refresh_token"):
            raise YouTubeError("Not signed in to YouTube.")
        if tok.get("access_token") and tok.get("expires_at", 0) > time.time():
            return tok["access_token"]
        cid, secret = client()
        new = _post(TOKEN, {"client_id": cid, "client_secret": secret, "refresh_token": tok["refresh_token"],
                            "grant_type": "refresh_token"})
        tok.update(access_token=new["access_token"], expires_at=time.time() + int(new.get("expires_in", 3600)) - 60)
        _store(tok)
        return tok["access_token"]


def get(path: str, params: dict) -> dict:
    """GET from the YouTube Data API, signed in if possible, else with the API key."""
    headers = {"User-Agent": UA, "Accept": "application/json"}
    params = dict(params)
    if signed_in():
        headers["Authorization"] = f"Bearer {_access_token()}"
    elif api_key():
        params["key"] = api_key()
    else:
        raise YouTubeError("Sign in with Google (⚙ → YouTube) to use the YouTube API.")
    req = urllib.request.Request(API + path + "?" + urllib.parse.urlencode(params), headers=headers)
    try:
        with _open(req) as res:
            _last_error["text"] = ""
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        reason = ""
        try:
            reason = (json.loads(e.read()).get("error") or {}).get("errors", [{}])[0].get("reason", "")
        except Exception:  # noqa: BLE001
            pass
        text = {"quotaExceeded": "YouTube's daily limit for your Google project is used up; it resets at midnight Pacific.",
                "accessNotConfigured": "The YouTube Data API isn't turned on in your Google project (APIs & Services → Library).",
                "forbidden": "Google didn't allow that request."}.get(reason, f"YouTube answered with an error ({e.code}).")
        if e.code == 401:
            text = "Your YouTube sign-in expired. Sign in with Google again under ⚙ → YouTube."
        _last_error["text"] = text
        raise YouTubeError(text) from e
    except urllib.error.URLError as e:
        _last_error["text"] = f"Couldn't reach YouTube ({e.reason})."
        raise YouTubeError(_last_error["text"]) from e


def status() -> dict:
    cid, secret = client()
    return {"configured": bool(cid and secret), "signed_in": signed_in(), "name": _load().get("name", ""),
            "api_key": bool(api_key()), "error": _last_error["text"], "redirect": REDIRECT}


# ---------- videos ----------

def _video(snippet: dict, vid: str) -> dict:
    from datetime import datetime
    try:
        when = datetime.fromisoformat(snippet.get("publishedAt", "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        when = 0
    thumbs = snippet.get("thumbnails") or {}
    return {"title": snippet.get("title", ""), "link": f"https://www.youtube.com/watch?v={vid}", "video_id": vid,
            "channel_id": snippet.get("channelId") or snippet.get("videoOwnerChannelId", ""),
            "source": snippet.get("channelTitle") or snippet.get("videoOwnerChannelTitle", ""),
            "image": (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url", ""),
            "time": when, "views": None}


def with_views(videos: list[dict]) -> list[dict]:
    """Fill in view counts: one request per 50 videos (1 unit)."""
    ids = [v["video_id"] for v in videos if v.get("video_id")]
    views = {}
    for i in range(0, len(ids), 50):
        data = get("videos", {"part": "statistics", "id": ",".join(ids[i:i + 50])})
        views.update({x["id"]: int(x.get("statistics", {}).get("viewCount", 0)) for x in data.get("items", [])})
    for v in videos:
        if v.get("video_id") in views:
            v["views"] = views[v["video_id"]]
    return videos


def channel_videos(channel_ids: list[str], per_channel: int = 6) -> list[dict]:
    """Newest uploads of these channels through the API (their uploads playlists)."""
    def load():
        uploads = {}
        for i in range(0, len(channel_ids), 50):
            data = get("channels", {"part": "contentDetails", "id": ",".join(channel_ids[i:i + 50])})
            for c in data.get("items", []):
                uploads[c["id"]] = c["contentDetails"]["relatedPlaylists"]["uploads"]
        out = []
        for cid in channel_ids:
            if cid not in uploads:
                continue
            try:
                data = get("playlistItems", {"part": "snippet", "playlistId": uploads[cid], "maxResults": per_channel})
            except YouTubeError:
                continue
            for it in data.get("items", []):
                sn = it.get("snippet", {})
                vid = (sn.get("resourceId") or {}).get("videoId")
                if vid:
                    out.append(_video(sn, vid))
        return with_views(out)
    return cached(f"ytapi:ch:{','.join(sorted(channel_ids))}:{per_channel}", 1800, load)


def subscriptions() -> list[str]:
    """The channel IDs you're subscribed to (up to 200)."""
    def load():
        ids, token = [], None
        for _ in range(4):
            params = {"part": "snippet", "mine": "true", "maxResults": 50, "order": "relevance"}
            if token:
                params["pageToken"] = token
            data = get("subscriptions", params)
            ids += [it["snippet"]["resourceId"]["channelId"] for it in data.get("items", [])]
            token = data.get("nextPageToken")
            if not token:
                break
        return ids
    return cached("ytapi:subs", 6 * 3600, load)


def search(query: str, popular_days: int | None = None) -> list[dict]:
    """A YouTube search (100 units, so cached an hour); most viewed first when popular_days is set."""
    params = {"part": "snippet", "q": query, "type": "video", "maxResults": 24, "relevanceLanguage": "en",
              "order": "viewCount" if popular_days else "relevance"}
    if popular_days:
        params["publishedAfter"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - popular_days * 86400))

    def load():
        data = get("search", params)
        return with_views([_video(it["snippet"], it["id"]["videoId"]) for it in data.get("items", [])
                           if (it.get("id") or {}).get("videoId")])
    return cached(f"ytapi:search:{query.lower()}:{popular_days}", 3600, load)
