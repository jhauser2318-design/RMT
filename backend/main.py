"""RMT web server. Start it with start.bat / start.sh, then open http://localhost:8050"""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from . import ai, markets, news, sports  # noqa: E402 (after .env is loaded)

app = FastAPI(title="RMT: Risky Money Time")
FRONTEND = ROOT / "frontend"


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
