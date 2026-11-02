"""YouTube: Sign in with Google (PKCE), the official API, and what happens when YouTube's
free feeds fail. A fake Google stands in for the real one, so no internet is needed.

Run:  python tests/test_youtube.py   (from the RMT folder)
"""
import base64
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["RMT_DEMO"] = "0"
os.environ["YOUTUBE_API_KEY"] = ""

from backend import fetch, news, youtube  # noqa: E402

TMP = Path(tempfile.mkdtemp())
youtube.TOKEN_FILE = TMP / "youtube_token.json"
news.LAST_FILE = TMP / "youtube_last.json"
calls = []
google = {"code_ok": True, "verifier": None, "subs": ["UCsub1", "UCsub2"], "quota": False}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_open(req):
    url = req.full_url
    calls.append((url, dict(req.header_items()), req.data))
    if url == youtube.TOKEN:
        form = dict(urllib.parse.parse_qsl(req.data.decode()))
        if form["grant_type"] == "authorization_code":
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
            assert challenge == google["challenge"] and form["redirect_uri"] == youtube.REDIRECT
            return Resp(json.dumps({"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600}).encode())
        assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "RT1"
        return Resp(json.dumps({"access_token": "AT2", "expires_in": 3600}).encode())
    assert req.get_header("Authorization", "").startswith("Bearer AT"), "API calls must carry the sign-in"
    path = urllib.parse.urlparse(url).path.rsplit("/", 1)[1]
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    if google["quota"]:
        raise urllib.error.HTTPError(url, 403, "quota", {}, io.BytesIO(json.dumps({"error": {"errors": [{"reason": "quotaExceeded"}]}}).encode()))
    if path == "channels" and q.get("mine"):
        return Resp(json.dumps({"items": [{"snippet": {"title": "Jack's Channel"}}]}).encode())
    if path == "channels":
        return Resp(json.dumps({"items": [{"id": c, "contentDetails": {"relatedPlaylists": {"uploads": "UU" + c[2:]}}}
                                          for c in q["id"].split(",")]}).encode())
    if path == "subscriptions":
        if q.get("pageToken") == "p2":
            return Resp(json.dumps({"items": [{"snippet": {"resourceId": {"channelId": google["subs"][1]}}}]}).encode())
        return Resp(json.dumps({"items": [{"snippet": {"resourceId": {"channelId": google["subs"][0]}}}], "nextPageToken": "p2"}).encode())
    if path == "playlistItems":
        cid = "UC" + q["playlistId"][2:]
        return Resp(json.dumps({"items": [{"snippet": {"title": f"New from {cid}", "channelTitle": cid, "channelId": cid,
                                                       "publishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                       "resourceId": {"videoId": "v" + cid}}}]}).encode())
    if path == "videos":
        return Resp(json.dumps({"items": [{"id": v, "statistics": {"viewCount": "1234"}} for v in q["id"].split(",")]}).encode())
    if path == "search":
        return Resp(json.dumps({"items": []}).encode())
    raise AssertionError(url)


youtube._open = fake_open


def configure():
    os.environ["YOUTUBE_CLIENT_ID"] = "123-abc.apps.googleusercontent.com"
    os.environ["YOUTUBE_CLIENT_SECRET"] = "GOCSPX-secret"


def sign_in():
    configure()
    url = youtube.login_url()
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    google["challenge"] = q["code_challenge"]
    return q


def test_sign_in_with_pkce_and_refresh():
    youtube.sign_out()
    fetch._cache.clear()
    os.environ["YOUTUBE_CLIENT_ID"] = ""
    try:
        youtube.login_url()
    except youtube.YouTubeError as e:
        assert "client ID" in str(e)
    q = sign_in()
    assert q["code_challenge_method"] == "S256" and q["scope"].endswith("youtube.readonly") and q["access_type"] == "offline"
    assert q["redirect_uri"] == "http://127.0.0.1:8050/api/youtube/callback"
    try:
        youtube.finish_login("code", "not-the-state")  # a link RMT didn't start
    except youtube.YouTubeError as e:
        assert "expired or didn't come from RMT" in str(e)
    assert youtube.finish_login("code", q["state"]) == "Jack's Channel"
    assert youtube.signed_in() and youtube.status()["name"] == "Jack's Channel"
    try:
        youtube.finish_login("code", q["state"])  # each sign-in link works once
    except youtube.YouTubeError:
        pass
    tok = json.loads(youtube.TOKEN_FILE.read_text())
    tok["expires_at"] = 0  # the hour is up: RMT refreshes on its own
    youtube.TOKEN_FILE.write_text(json.dumps(tok))
    youtube.get("videos", {"part": "statistics", "id": "x"})
    assert calls[-1][1]["Authorization"] == "Bearer AT2"


def test_subscriptions_tab():
    fetch._cache.clear()
    assert youtube.signed_in()
    r = news.youtube_videos(tab="subs")
    assert r["signed_in"] and sorted(v["video_id"] for v in r["items"]) == ["vUCsub1", "vUCsub2"]  # both pages of subs
    assert r["items"][0]["views"] == 1234 and r["items"][0]["link"].endswith("watch?v=" + r["items"][0]["video_id"])


def test_feeds_down_signed_in_uses_the_api():
    fetch._cache.clear()
    news._last.clear()
    news.get = lambda url, *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO(b"")))
    r = news.youtube_videos(tab="investing")
    assert r["live"] and len(r["items"]) == len(news.YOUTUBE_CHANNELS["investing"]) and not r["note"]
    assert all(v["views"] == 1234 for v in r["items"])


def test_feeds_down_not_signed_in_shows_last_videos_and_says_why():
    youtube.sign_out()
    fetch._cache.clear()
    # The feeds worked once (and RMT remembered), then broke.
    cid = news.YOUTUBE_CHANNELS["news"][0][1]
    news._last.clear()
    news._remember(cid, [{"title": "Market close", "link": "https://youtu.be/1", "video_id": "1", "time": time.time(),
                          "source": "CNBC Television", "views": 10, "image": ""}])
    news._last.clear()  # comes back from disk
    r = news.youtube_videos(tab="news")
    assert [v["title"] for v in r["items"]] == ["Market close"]
    assert "known YouTube problem" in r["note"] and "Sign in with Google" in r["note"]
    r = news.youtube_videos(tab="subs")
    assert r["items"] == [] and "Sign in with Google" in r["note"]


def test_quota_message():
    sign_in()
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(youtube.login_url()).query))
    google["challenge"] = q["code_challenge"]
    youtube.finish_login("code", q["state"])
    fetch._cache.clear()
    google["quota"] = True
    try:
        youtube.get("videos", {"part": "statistics", "id": "x"})
    except youtube.YouTubeError as e:
        assert "daily limit" in str(e) and "daily limit" in youtube.status()["error"]
    finally:
        google["quota"] = False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("all YouTube tests passed")
