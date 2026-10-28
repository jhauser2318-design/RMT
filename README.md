<p align="center"><img src="frontend/logo.svg" width="140" alt="RMT logo"></p>

# RMT: Risky Money Time

One app with two sides, **📈 Trading** and **🎲 Betting**, plus an AI chat that works across both.

It runs on your own computer and opens in your web browser, the same way Life Control Center does.

### 📈 Trading
- **Live crypto**: Bitcoin, Ethereum, Solana and more stream live from Coinbase (no key needed). The Crypto ribbon shows **⚡ LIVE** and each price flashes green or red as it ticks.
- **Real-time stocks (free, optional)**: paste free Alpaca keys under ⚙ → Live data and stock prices become real-time. Your watchlist, SPY, VOO, QQQ and the hottest names (30 in all) stream live, marked ⚡.
- **Stock ribbons**: scrolling tickers for Indexes & Futures, Mega Caps, Day-Trader Favorites, ETFs, Crypto, and Commodities & FX. Each one shows the price, the % change and a mini chart. Hover over a ribbon to pause it.
- **My Watchlist**: add your own tickers (e.g. `AAPL, TSLA, BTC-USD`) to get your own ribbon at the top.
- **Headlines** from CNBC, MarketWatch, Yahoo Finance, Seeking Alpha, Investing.com, Nasdaq and Benzinga. Click any ticker on a ribbon, or type one, to see news about just that stock.
- **Trading Talk**: the hottest posts on r/wallstreetbets, r/stocks, r/investing, r/options, r/Daytrading and r/StockMarket.
- **YouTube**: **🔥 Popular** shows the most-watched stock and investing advice videos of the week from popular channels (Graham Stephan, Andrei Jikh, Humphrey Yang, Minority Mindset, Financial Education, Ticker Symbol: YOU, Meet Kevin, Warrior Trading, Humbled Trader), with view counts. Tabs for 📈 Investing, ⚡ Day trading and 📰 Market news (CNBC, Bloomberg, Yahoo Finance, WSJ). With an optional key, Popular also includes the most-viewed advice from all of YouTube.

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

## Install it (Windows, one time)

1. Download RMT: **[RMT ZIP](https://github.com/jhauser2318-design/RMT/archive/refs/heads/main.zip)**. Open your **Downloads** folder, right-click the ZIP and choose **Extract All… → Extract**.
2. Double-click **`INSTALL.bat`** in the extracted folder. It:
   - installs Python for you if it's missing,
   - copies RMT to **`C:\Users\<your name>\RMT`**,
   - asks for your Anthropic API key, or reuses the one from Life Control Center automatically,
   - puts an **RMT** icon on your Desktop and in the Start menu, then opens RMT.
3. From then on, just **double-click RMT on your Desktop**. It opens in its own window (no browser tabs). Closing the window closes RMT.

### Keeping it up to date
- **Data:** the **⟳** button at the top refreshes everything right now. Next to it, **Auto** sets how often prices, scores and odds update by themselves: off, 15 seconds, 30 seconds, 1 minute or 5 minutes.
- **New versions of RMT install themselves**, like Life Control Center: every time you open RMT it checks for a newer version and installs it first (a quick "✨ RMT was updated" note tells you what changed). You never need to download it again. To turn this off, click **⚙** and untick **Update automatically when RMT opens**; then a dot on ⚙ tells you when an update is ready and **Update now** installs it. Your keys are never touched.

*(Mac / Linux, or to see the server's messages: run `./start.sh` or `start.bat`, then open http://localhost:8050.)*

## Keys

Your keys live in the **`.env`** file in `C:\Users\<your name>\RMT`. Open it in Notepad to add or change them, then close and reopen RMT.

| Key | What it's for | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | The **Ask RMT** chat. Required for the chat; everything else works without it. | https://console.anthropic.com → API Keys (you can reuse your Life Control Center key) |
| `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY` | Real-time stock prices. Optional. Easiest: paste them under ⚙ → Live data. | https://alpaca.markets → sign up → Paper account → API Keys → Generate (free) |
| `ODDS_API_KEY` | Odds from many sportsbooks side by side. Optional. | https://the-odds-api.com (free: 500 requests a month) |
| `YOUTUBE_API_KEY` | Search all of YouTube by ticker or topic. Optional. | Google Cloud Console → enable **YouTube Data API v3** → Credentials |

| `GITHUB_TOKEN` | Only if the RMT repository on GitHub is **private**: lets the Update button download new versions. | github.com → Settings → Developer settings → Fine-grained token with read access to RMT |

Want **truly live** stock prices, crypto and odds for free? See the plan in [docs/LIVE_DATA_PLAN.md](docs/LIVE_DATA_PLAN.md).

## Good to know
- **Costs:** everything in RMT is free except the AI chat, which costs a few cents per question. See [docs/LIVE_DATA_PLAN.md](docs/LIVE_DATA_PLAN.md#what-it-costs).
- **Where the data comes from:** crypto streams live from Coinbase. Otherwise RMT reads the sites' public feeds: Yahoo Finance for prices, RSS for headlines, Reddit's public listings, YouTube channel feeds, and ESPN's scoreboard for games, odds and standings. Nothing needs a login.
- **"Sample data" badge:** if RMT can't reach a source (no internet, or a site is down), it shows made-up sample numbers and the badge in the top-right corner says **Sample data** instead of **LIVE**. Never bet or trade on sample numbers.
- Prices can be delayed up to ~15 minutes. Without `ODDS_API_KEY` you get one sportsbook's line per game (usually ESPN BET or DraftKings).
- To follow different YouTube channels, edit the `YOUTUBE_CHANNELS` lists in `backend/news.py`. The tickers on the ribbons are in `backend/markets.py`.
- The chat uses Claude Opus 5.5 by default. To use a cheaper model, set `RMT_MODEL=claude-sonnet-5-5` in `.env`.

## For developers
- Backend: FastAPI (`backend/`). Frontend: plain HTML/CSS/JS (`frontend/`), no build step.
- Tests (no internet needed): `python tests/test_parsers.py`
- `RMT_DEMO=1` always shows sample data.

> RMT is for information and entertainment, not financial or betting advice. Only risk what you can afford to lose. Gambling problem? Call 1-800-GAMBLER.
