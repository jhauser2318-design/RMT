<p align="center"><img src="frontend/logo.svg" width="140" alt="RMT logo"></p>

# RMT: Risky Money Time

One app with two sides, **📈 Trading** and **🎲 Betting**, plus an AI chat that works across both.

It runs on your own computer and opens in your web browser, the same way Life Control Center does.

### 📈 Trading
- **Stock ribbons**: scrolling tickers for Indexes & Futures, Mega Caps, Day-Trader Favorites, ETFs, Crypto, and Commodities & FX. Each one shows the price, the % change and a mini chart. Hover over a ribbon to pause it.
- **My Watchlist**: add your own tickers (e.g. `AAPL, TSLA, BTC-USD`) to get your own ribbon at the top.
- **Headlines** from CNBC, MarketWatch, Yahoo Finance, Seeking Alpha, Investing.com, Nasdaq and Benzinga. Click any ticker on a ribbon, or type one, to see news about just that stock.
- **Trading Talk**: the hottest posts on r/wallstreetbets, r/stocks, r/investing, r/options, r/Daytrading and r/StockMarket.
- **YouTube**: the newest videos from CNBC, Bloomberg, Yahoo Finance, WSJ, Graham Stephan, Meet Kevin and Andrei Jikh. Search all of YouTube with an optional key.

### 🎲 Betting
- **Every game** in the NFL, college football, NBA, college basketball, WNBA, MLB, NHL, Premier League, La Liga, Champions League, MLS and UFC, with live scores.
- **Odds on every game**: moneyline, spread and total. Switch between American odds, decimal odds and win %.
- **Compare sportsbooks** (optional free key): DraftKings, FanDuel, BetMGM, Caesars and more side by side, with the best price highlighted.
- **Lines & Scores ribbon**: every game's line, scrolling across the top. Click one to jump to the game.
- **Stats**: search any player or team, and see standings for every league.

### ✨ Ask RMT (AI chat)
Ask anything. *"What's Mahomes' passer rating in his last 3 games?"*, *"Where's the value in tonight's NBA slate?"*, *"Why is NVDA down today?"*.
It uses RMT's live prices, headlines, games and odds, and searches the web for stats and injury news. Every game card has an **Ask RMT** button that writes the question for you.

---

## Start it

**Windows:** double-click **`start.bat`** in the `RMT` folder. The first run takes a minute while it installs what it needs. Your browser then opens **http://localhost:8050**.

**Mac / Linux:** run `./start.sh`, then open **http://localhost:8050**.

The first run creates a file named **`.env`** in the `RMT` folder. Open it in Notepad to add your keys:

| Key | What it's for | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | The **Ask RMT** chat. Required for the chat; everything else works without it. | https://console.anthropic.com → API Keys (you can reuse your Life Control Center key) |
| `ODDS_API_KEY` | Odds from many sportsbooks side by side. Optional. | https://the-odds-api.com (free: 500 requests a month) |
| `YOUTUBE_API_KEY` | Search all of YouTube by ticker or topic. Optional. | Google Cloud Console → enable **YouTube Data API v3** → Credentials |

Save the file, then close and reopen RMT.

## Good to know
- **Where the data comes from:** RMT reads the sites' public feeds: Yahoo Finance for prices, RSS for headlines, Reddit's public listings, YouTube channel feeds, and ESPN's scoreboard for games, odds and standings. Nothing needs a login.
- **"Sample data" badge:** if RMT can't reach a source (no internet, or a site is down), it shows made-up sample numbers and the badge in the top-right corner says **Sample data** instead of **LIVE**. Never bet or trade on sample numbers.
- Prices can be delayed up to ~15 minutes. Without `ODDS_API_KEY` you get one sportsbook's line per game (usually ESPN BET or DraftKings).
- To follow different YouTube channels, edit the `YOUTUBE_CHANNELS` list in `backend/news.py`. The tickers on the ribbons are in `backend/markets.py`.
- The chat uses Claude Opus 5.5 by default. To use a cheaper model, set `RMT_MODEL=claude-sonnet-5-5` in `.env`.

## For developers
- Backend: FastAPI (`backend/`). Frontend: plain HTML/CSS/JS (`frontend/`), no build step.
- Tests (no internet needed): `python tests/test_parsers.py`
- `RMT_DEMO=1` always shows sample data.

> RMT is for information and entertainment, not financial or betting advice. Only risk what you can afford to lose. Gambling problem? Call 1-800-GAMBLER.
