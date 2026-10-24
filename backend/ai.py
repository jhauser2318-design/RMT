"""“Ask RMT”: an AI chat for stock questions, sports stats and betting research.

Claude answers using RMT's own live data (prices, headlines, games and odds,
standings) and searches the web for anything else, like a player's season
stats or injury news. Your API key stays on your computer.
"""
import json
import os
from datetime import datetime

import anthropic

from . import markets, news, sports

MAX_ROUNDS = 8

TOOLS = [
    {"name": "get_quotes", "description": "Current price, change and % change for stock, ETF, index (^GSPC), futures (ES=F) or crypto (BTC-USD) symbols, in Yahoo Finance format.",
     "input_schema": {"type": "object", "properties": {"symbols": {"type": "array", "items": {"type": "string"}, "maxItems": 30}},
                      "required": ["symbols"]}},
    {"name": "get_market_news", "description": "Latest market headlines from CNBC, MarketWatch, Yahoo Finance and others. Give a ticker or topic to get news about it, or leave it empty for the top stories.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
    {"name": "get_trading_talk", "description": "The most upvoted posts right now on r/wallstreetbets, r/stocks, r/investing, r/options, r/Daytrading and r/StockMarket.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_games", "description": "Games with scores, status and betting odds (moneyline, spread, total; several sportsbooks when available) for a league.",
     "input_schema": {"type": "object", "properties": {
         "league": {"type": "string", "enum": ["all", *sports.LEAGUES]},
         "date": {"type": "string", "description": "YYYYMMDD. Omit for today / this week."}},
         "required": ["league"]}},
    {"name": "get_standings", "description": "Current standings (wins, losses, etc.) for a league.",
     "input_schema": {"type": "object", "properties": {"league": {"type": "string", "enum": list(sports.LEAGUES)}},
                      "required": ["league"]}},
    {"name": "search_sports", "description": "Find players and teams on ESPN by name; returns links to their stats pages.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
]
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6}

SYSTEM = """You are the assistant inside RMT ("Risky Money Time"), an app for day traders, investors and sports bettors.

You help with two things:
- Markets: prices, movers, news, what traders are talking about, how to read a setup.
- Sports betting: games and odds, line shopping across sportsbooks, and stats (player and team stats, trends, injuries, head-to-head).

How to answer:
- Use the RMT tools first for prices, headlines, games, odds and standings; use web search for stats, injuries and anything the tools don't cover. Never make up a number: if you can't find it, say so.
- Lead with the answer. Keep it tight and scannable: short paragraphs, bullets or a small table for stats and odds.
- Say when a number is from (e.g. "as of today's line at DraftKings", "2025-26 season").
- American odds: explain implied probability when it helps (e.g. -150 ≈ 60%).
- You can give your read on a trade or bet when asked, with the reasoning and the main risk. Never promise a result. No lectures: one short line about risk is enough, only when someone is clearly about to risk money.
"""


def _run_tool(name: str, args: dict):
    if name == "get_quotes":
        found, live = markets.quotes(args.get("symbols") or [])
        return {"live": live, "quotes": [{k: q[k] for k in ("symbol", "name", "price", "change", "pct")} for q in found]}
    if name == "get_market_news":
        res = news.headlines(args.get("query", ""), limit=15)
        return {"live": res["live"], "items": [{k: i[k] for k in ("title", "source", "link", "time")} for i in res["items"]]}
    if name == "get_trading_talk":
        res = news.trading_talk()
        return {"live": res["live"], "items": [{k: i[k] for k in ("title", "source", "score", "comments", "link")} for i in res["items"][:20]]}
    if name == "get_games":
        res = sports.games(args.get("league", "all"), args.get("date", ""))
        slim = []
        for g in res["games"][:40]:
            slim.append({"game": g["name"], "league": g["league_name"], "start": g["start"], "status": g["detail"],
                         "home": f'{g["home"]["name"]} {g["home"]["record"]} {g["home"]["score"]}'.strip(),
                         "away": f'{g["away"]["name"]} {g["away"]["record"]} {g["away"]["score"]}'.strip(),
                         "odds": g.get("odds"), "books": g.get("books", [])[:8], "best_prices": g.get("best")})
        return {"live": res["live"], "games": slim}
    if name == "get_standings":
        return sports.standings(args.get("league", ""))
    if name == "search_sports":
        return sports.search(args.get("query", ""))
    raise ValueError(f"Unknown tool {name}")


def _client() -> anthropic.Anthropic:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key or key.startswith("sk-ant-your"):
        raise RuntimeError("Add your Anthropic API key to the .env file (ANTHROPIC_API_KEY=...) and restart RMT to use the chat.")
    return anthropic.Anthropic(api_key=key)


def chat(history: list[dict]) -> dict:
    """history: [{"role": "user"|"assistant", "content": "text"}, ...], ending with the user's question."""
    client = _client()
    model = os.getenv("RMT_MODEL", "").strip() or "claude-opus-5-5"
    system = SYSTEM + f"\nToday is {datetime.now().strftime('%A, %B %d, %Y')}."
    messages = [{"role": m["role"], "content": m["content"]} for m in history[-20:]
                if m.get("role") in ("user", "assistant") and m.get("content")]
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    if not messages:
        raise ValueError("Ask a question first.")

    used, sources = [], []
    for _ in range(MAX_ROUNDS):
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            messages=messages,
            tools=[*TOOLS, WEB_SEARCH],
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            # If a safety check declines (e.g. a false positive), the API retries on another model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        for block in response.content:
            if block.type == "text":
                for c in getattr(block, "citations", None) or []:
                    url = getattr(c, "url", None)
                    if url and url not in (s["url"] for s in sources):
                        sources.append({"url": url, "title": getattr(c, "title", "") or url})
            elif block.type == "server_tool_use":
                used.append("web search")
        if response.stop_reason == "refusal":
            return {"reply": "I can't help with that one. Try asking it a different way.", "sources": [], "used": used}
        if response.stop_reason == "pause_turn":  # a long web search: let it keep going
            messages.append({"role": "assistant", "content": response.content})
            continue
        if response.stop_reason != "tool_use":
            text = "\n\n".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason == "max_tokens":
                text += "\n\n_(Answer cut off. Ask me to continue.)_"
            return {"reply": text or "(No answer.)", "sources": sources[:8], "used": sorted(set(used))}

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            used.append(block.name.replace("_", " "))
            try:
                out = _run_tool(block.name, block.input if isinstance(block.input, dict) else {})
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out, default=str)[:60000]})
            except Exception as e:  # noqa: BLE001 (tell Claude, let it work around it)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})
    return {"reply": "That took too many steps. Try a narrower question.", "sources": sources[:8], "used": sorted(set(used))}


def friendly_error(e: Exception) -> tuple[int, str]:
    if isinstance(e, (RuntimeError, ValueError)):
        return 400, str(e)
    if isinstance(e, anthropic.AuthenticationError):
        return 401, "Your Anthropic API key was rejected. Check ANTHROPIC_API_KEY in the .env file."
    if isinstance(e, anthropic.PermissionDeniedError):
        return 403, "Your Anthropic account can't use this model or feature. Check your plan and credit at console.anthropic.com."
    if isinstance(e, anthropic.NotFoundError):
        return 400, "That Claude model wasn't found. Check RMT_MODEL in the .env file."
    if isinstance(e, anthropic.RateLimitError):
        return 429, "Too many requests to Claude right now. Wait a few seconds and try again."
    if isinstance(e, anthropic.BadRequestError):
        return 400, f"Claude couldn't take that request: {e.message}"
    if isinstance(e, anthropic.APIStatusError):
        return 502, "Claude's servers had a problem. Try again in a moment."
    if isinstance(e, anthropic.APIConnectionError):
        return 502, "Couldn't reach Claude. Check your internet connection."
    return 500, f"Something went wrong: {e}"
