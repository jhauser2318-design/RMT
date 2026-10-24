# Plan: free, live, real-time data for RMT

_Written October 2026. Free plans change often, so check each provider's pricing page before you sign up. Numbers marked "reported" come from third-party reviews, not the provider itself._

## The honest picture

| What | Truly real-time for free? | Notes |
|---|---|---|
| **Crypto prices** | ✅ Yes | Exchanges stream every trade for free, with no key. |
| **US stock prices** | ⚠️ Mostly | Free real-time feeds come from **one exchange (IEX)**, not the whole market. The price is real, but volume is a slice, and thinly traded stocks update less often. True full-market (SIP) real-time costs money everywhere. |
| **Index values** (S&P 500, Nasdaq, Dow) | ❌ Usually delayed | Exchanges license index values. Workaround: track the ETFs instead (SPY, QQQ, DIA, IWM), which *are* real-time on free IEX feeds. |
| **Futures** (ES, NQ, oil, gold) | ❌ Delayed 10–15 min | CME data isn't free anywhere. Keep Yahoo (delayed) for these. |
| **Live scores** | ✅ Near-real-time | ESPN and the official NHL and MLB feeds update within seconds to tens of seconds. Free, no key. |
| **Betting odds** | ⚠️ Limited | Free tiers exist, but each gives only a few hundred to a few thousand requests per month or day. With smart caching that's plenty for one person. |
| **Player stats** | ✅ Yes (after the game / between plays) | ESPN, the NHL/MLB official feeds, and the AI chat's web search. |
| **News, Reddit, YouTube** | ✅ Yes | RSS feeds and Reddit update within minutes. YouTube's free API key gives 10,000 units a day. |

## Recommended free setup

### 📈 Stocks
1. **Alpaca (free plan)**: the main real-time source.
   - Real-time US stocks from the IEX exchange, **streamed** (prices arrive the moment they trade, no polling).
   - Free limits (from Alpaca's docs): **30 symbols** streamed at once, **200 requests/minute**.
   - RMT would stream your **watchlist plus the Day-Trader Favorites** live, and fill in everything else with requests every few seconds.
   - Sign up: alpaca.markets → create an account (a paper trading account is enough, no deposit) → API Keys.
2. **Finnhub (free plan)**: second source plus company news.
   - Reported: **60 requests/minute** and **50 symbols** streamed. Adds company news, earnings dates and analyst ratings per ticker.
   - Sign up: finnhub.io → Get free API key.
3. **Yahoo Finance (what RMT uses today)**: kept for indexes, futures, FX and as a backup. No key, delayed up to ~15 minutes for some markets.

### 🪙 Crypto ✅ built
- **Coinbase public stream**: every BTC, ETH, SOL… trade, in real time, free, no account or key. The Crypto ribbon shows **⚡ LIVE** while it's streaming, and coins in your watchlist (anything ending in `-USD`, like `PEPE-USD`) stream too.

### 🏈 Scores and stats
- **ESPN** (what RMT uses today): all 12 leagues. Poll every **15 seconds for live games** and every few minutes otherwise.
- **NHL official feed** (api-web.nhle.com) and **MLB Stats API** (statsapi.mlb.com): free, no key, with live play-by-play and box scores. Unofficial and undocumented, so RMT keeps ESPN as the fallback.
- **BALLDONTLIE** (NBA and more): reported free tier of ~5 requests/minute for teams, players and games. Detailed box scores and injuries are paid.

### 🎲 Odds
Use two free services and spend their requests carefully:
1. **ESPN's built-in line** (today): one sportsbook per game, free and unlimited. This is the baseline for every game.
2. **The Odds API (free: 500 credits a month)**: DraftKings, FanDuel, BetMGM, Caesars and ~40 books side by side.
   - A call costs *markets × regions* credits. Moneyline + spread + total in the US = **3 credits**, so about 165 calls a month.
   - RMT's plan: only fetch when you open a league (never for "All sports" at once), cache 10 minutes, and show how many credits are left.
3. **Odds-API.io (free tier)**: reported 100 requests an hour, with 2 sportsbooks. Used to refresh lines more often between The Odds API calls.

## What RMT needs to change (build plan)

**Step 1: a data-source layer** (foundation)
- Each kind of data (stock quote, crypto quote, scores, odds) gets a ranked list of sources. RMT uses the best one that has a key and is working, and falls back down the list automatically.
- A **Data sources** panel in ⚙ settings shows each source as 🟢 live / 🟡 delayed / 🔴 not connected, when it last updated, and how much free quota is left this month.
- Paste keys right in that panel instead of editing `.env` by hand.

**Step 2: streaming instead of refreshing**
- RMT's server holds the live streams (Alpaca, Finnhub, Coinbase) open and pushes each new price to the window instantly. The ribbons tick in real time with a green/red flash.
- The auto-refresh setting stays for things that can't stream (news, odds, scores).

**Step 3: live games**
- Live games refresh every 15 seconds automatically; finished and upcoming games much less often.
- NHL and MLB games get play-by-play from the official feeds.

**Step 4: odds budget**
- Track The Odds API credits from its response headers. Warn at 80%. Above that, fall back to ESPN lines plus Odds-API.io.

**Step 5 (optional, later): upgrades worth paying for**
If free isn't enough, these are the first upgrades worth considering (reported prices, verify first):
- **The Odds API, 20,000 credits for ~$30/month**: line shopping across every game, refreshed often.
- **Alpaca's paid data plan**: full-market (SIP) real-time stocks with no 30-symbol limit.

## What it costs

**Short version: everything RMT needs can run for $0 a month.** The only thing that costs money by default is the AI chat, and only when you use it.

### Free forever (no card needed)
| Service | What RMT gets | Free limit |
|---|---|---|
| Coinbase stream | Live crypto | Unlimited, no key |
| Yahoo Finance, ESPN, RSS news, Reddit, NHL/MLB feeds | Prices (delayed), scores, odds line, news | No key; just be polite with refresh rates |
| Alpaca | Real-time stocks (IEX) | 30 streamed symbols, 200 requests/min |
| Finnhub | Quotes, company news | ~60 requests/min (reported) |
| The Odds API | Many sportsbooks side by side | 500 credits/month (~165 lookups) |
| Odds-API.io | More odds lookups | Reported ~100 requests/hour |
| YouTube Data API | Video search | 10,000 units/day (a search costs 100, so ~100 searches/day) |

### If you ever want to pay for more (reported prices, monthly; check each site first)
| Upgrade | Price | Worth it? |
|---|---|---|
| **The Odds API**: 20,000 credits | **~$30** | ✅ Best value if you bet a lot. Line shopping across every game, refreshed every few minutes. |
| **BALLDONTLIE ALL-STAR** (NBA box scores, injuries) | **~$10** | 👍 Cheap if you want deep NBA stats in the app. The AI chat can already look most of this up. |
| **Massive (formerly Polygon) Starter** | ~$29 | ❌ Still 15-minute delayed. Not worth it over free Alpaca. |
| **Finnhub Basic** | ~$50 | ❌ Not needed; the free plan covers what RMT uses. |
| **Alpaca Algo Trader Plus** (whole-market real-time stocks, options) | **~$99** | Only if you're actively day trading and need every exchange's trades. |
| **Massive Advanced** (real-time stocks) | ~$199 | ❌ Alpaca does this for half the price. |
| **BALLDONTLIE GOAT / ALL-ACCESS** | ~$40 / ~$160–300 | ❌ Overkill for personal use. |

### The AI chat (Claude), pay as you go
You only pay when you ask a question. Rough cost per question (a typical question looks up 1–3 things and may search the web):

| Model (set `RMT_MODEL` in `.env`) | Per question | 20 questions a day for a month |
|---|---|---|
| **Claude Opus 5.5** (default, smartest) | ~10–30¢ | ~$60–180 |
| **Claude Sonnet 5.5** (`claude-sonnet-5-5`) | ~5–15¢ | ~$30–90 |
| **Claude Haiku 5.5** (`claude-haiku-5-5`) | ~1–2¢ | ~$6–12 |

Web searches inside an answer add about 1¢ each. RMT turns on "prompt caching", which bills the repeated part of each round at about 10%, so real costs should land toward the low end. You can set a monthly spending limit at console.anthropic.com → Billing.

## What you need to do

1. Make free accounts and copy the keys:
   - **Alpaca**: alpaca.markets → sign up → Paper account → *API Keys* → Generate (copy both the key and the secret).
   - **Finnhub**: finnhub.io → *Get free API key*.
   - **The Odds API**: the-odds-api.com → *Get API key* (free plan).
   - *(Optional)* **Odds-API.io**: odds-api.io → free plan.
   - *(Optional)* **YouTube Data API**: Google Cloud Console → enable *YouTube Data API v3* → *Credentials* → API key.
2. Paste them into RMT's `.env` file (or the Data sources panel once Step 1 is built).
3. Tell me which step to build next. With the crypto stream done, Alpaca (real-time stocks) is the biggest upgrade.

Sources used for this plan: Alpaca's market-data docs, and third-party comparisons of Finnhub, The Odds API, Odds-API.io, BALLDONTLIE and the NHL/MLB feeds. All listed in the chat where this plan was written.
