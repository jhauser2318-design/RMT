"""RMT web server. The desktop icon starts it (launcher.pyw); start.bat / start.sh work too."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from . import ai, fetch, markets, news, sports  # noqa: E402 (after .env is loaded)

sys.path.insert(0, str(ROOT))
import updater  # noqa: E402

app = FastAPI(title="RMT: Risky Money Time")
FRONTEND = ROOT / "frontend"

# Desktop mode: the open window checks in every 15 seconds. When it's been
# closed for a few minutes, the server stops so nothing keeps running.
IDLE_LIMIT = int(os.getenv("RMT_IDLE_LIMIT", "180"))
_last_ping = time.time()


def _watch_idle():
    while True:
        time.sleep(15)
        if time.time() - _last_ping > IDLE_LIMIT:
            os._exit(0)


if os.getenv("RMT_DESKTOP") == "1":
    threading.Thread(target=_watch_idle, daemon=True).start()


@app.get("/api/app/info")
def app_info():
    v = updater.installed()
    return {"pid": os.getpid(), "version": v.get("sha", "")[:7], "summary": v.get("summary", ""),
            "updated_at": v.get("updated_at", ""), "desktop": os.getenv("RMT_DESKTOP") == "1"}


@app.post("/api/app/ping")
def app_ping():
    global _last_ping
    _last_ping = time.time()
    return {"ok": True}


@app.get("/api/app/update")
def app_update_check():
    return updater.check()


@app.post("/api/app/update")
def app_update():
    result = updater.update()
    if result["updated"] and os.getenv("RMT_DESKTOP") == "1":
        # Start the new version: a fresh launcher waits for this server to stop, then starts one.
        python = Path(sys.executable).with_name("pythonw.exe")
        subprocess.Popen([str(python if python.is_file() else sys.executable), str(ROOT / "launcher.pyw"), "--restart"],
                         cwd=ROOT, creationflags=(0x00000008 | 0x00000200) if os.name == "nt" else 0,
                         start_new_session=os.name != "nt")
        threading.Timer(1.0, lambda: os._exit(0)).start()
        result["restarting"] = True
    return result


@app.post("/api/refresh")
def refresh(what: str = "all"):
    """Forget saved results so the next load downloads everything fresh.
    (Multi-sportsbook odds are kept for 10 minutes to stay inside the free plan.)"""
    prefixes = {"markets": ["q:", "feed:", "reddit:", "yt:"], "sports": ["espn:", "standings:", "search:"]}
    for prefix in prefixes.get(what, prefixes["markets"] + prefixes["sports"]):
        fetch.forget(prefix)
    return {"ok": True}


@app.get("/api/markets/ribbons")
def get_ribbons(watch: str = ""):
    return markets.ribbons([s for s in watch.upper().split(",") if s.strip()][:30])


@app.get("/api/markets/quotes")
def get_quotes(symbols: str):
    found, live = markets.quotes(symbols.split(","))
    return {"live": live, "quotes": found}


@app.get("/api/markets/news")
def get_news(q: str = ""):
    return news.headlines(q)


@app.get("/api/markets/talk")
def get_talk(sort: str = "hot"):
    return news.trading_talk(sort)


@app.get("/api/markets/videos")
def get_videos(q: str = ""):
    return news.youtube(q)


@app.get("/api/sports/leagues")
def get_leagues():
    return sports.leagues()


@app.get("/api/sports/games")
def get_games(league: str = "all", date: str = ""):
    return sports.games(league, date)


@app.get("/api/sports/standings")
def get_standings(league: str):
    return sports.standings(league)


@app.get("/api/sports/search")
def get_search(q: str):
    return sports.search(q)


class ChatIn(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
def post_chat(body: ChatIn):
    try:
        return ai.chat(body.messages)
    except Exception as e:  # noqa: BLE001
        status, msg = ai.friendly_error(e)
        raise HTTPException(status_code=status, detail=msg)


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="static")
