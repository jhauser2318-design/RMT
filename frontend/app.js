// RMT front end: stock ribbons, news, trading talk, YouTube, games & odds,
// stats and the "Ask RMT" chat. Talks only to the RMT server (/api/...).

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(`rmt.${k}`)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(`rmt.${k}`, JSON.stringify(v)); } catch { /* private mode */ } },
};

async function api(path, body, method = body ? "POST" : "GET") {
  // X-RMT marks requests from RMT's own window; the server refuses changes without it.
  const res = await fetch(`/api${path}`, method === "GET" ? {} : {
    method, headers: { "Content-Type": "application/json", "X-RMT": "1" }, body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (res.status === 405) {  // an older RMT is still running behind this newer window
    throw new Error("RMT needs a restart to finish updating: close every RMT window, wait a few seconds, and open RMT again.");
  }
  if (!res.ok) throw new Error(data?.detail || `Request failed (${res.status})`);
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function timeAgo(t) {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function fmtPrice(p) {
  if (p == null) return "-";
  const d = p >= 1000 ? 0 : p >= 1 ? 2 : 4;
  return p.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
}

const dir = (v) => (v > 0 ? "up" : v < 0 ? "down" : "flat");
const fmtPct = (v) => `${v > 0 ? "▲" : v < 0 ? "▼" : ""} ${Math.abs(v).toFixed(2)}%`;

function spark(points, up) {
  if (!points || points.length < 2) return "";
  const min = Math.min(...points), max = Math.max(...points), span = max - min || 1;
  const d = points.map((p, i) => `${(i / (points.length - 1) * 54).toFixed(1)},${(18 - (p - min) / span * 16).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 54 20"><polyline points="${d}" fill="none" stroke="${up ? "#2bf27f" : "#ff4d6a"}" stroke-width="1.6"/></svg>`;
}

function badge(live) {
  const b = $("#data-badge");
  b.hidden = false;
  b.className = `badge ${live ? "live" : "sample"}`;
  b.textContent = live ? "LIVE" : "Sample data";
  b.title = live ? "" : "Couldn't reach the live sources, so you're seeing made-up sample data.";
}

// A ribbon scrolls forever: the items are drawn twice and the track slides by half.
function ribbonHTML(label, inner, count, id = "") {
  return `<div class="ribbon" data-id="${esc(id)}"><div class="ribbon-label">${esc(label)}</div>
    <div class="ribbon-track" style="--dur:${Math.max(25, count * 4.5)}s">${inner}${inner}</div></div>`;
}

/* ============================ TRADING ============================ */

let watch = store.get("watch", []);
let tickerFilter = "";

async function loadRibbons() {
  try {
    const data = await api(`/markets/ribbons?watch=${encodeURIComponent(watch.join(","))}`);
    badge(data.live);
    stamp();
    const groups = data.ribbons.filter((r) => r.items.length);
    const tick = (q) => `${q.streaming ? `<span class="bolt" title="Live">⚡</span>` : ""}<span class="tick-sym">${esc(q.label)}</span>
        <span class="tick-px">${fmtPrice(q.price)}</span>
        <span class="tick-ch ${dir(q.pct)}">${fmtPct(q.pct)}</span>
        ${spark(q.spark, q.pct >= 0)}`;
    const layout = groups.map((r) => `${r.id}:${r.items.map((q) => q.symbol).join(",")}`).join("|");
    if ($("#ribbons").dataset.layout === layout) {
      // Same tickers as before: just update the numbers, so the ribbons keep scrolling smoothly.
      const bySym = Object.fromEntries(groups.flatMap((r) => r.items).map((q) => [q.symbol, q]));
      $$("#ribbons .tick").forEach((el) => { if (bySym[el.dataset.sym]) el.innerHTML = tick(bySym[el.dataset.sym]); });
      return;
    }
    $("#ribbons").dataset.layout = layout;
    $("#ribbons").innerHTML = groups.map((r) => ribbonHTML(r.name, r.items.map((q) => `
      <span class="tick" data-sym="${esc(q.symbol)}" title="${esc(q.name)}: click for news &amp; videos">${tick(q)}</span>`).join(""), r.items.length, r.id)).join("");
    showStreamStatus();
  } catch (e) {
    $("#ribbons").innerHTML = `<div class="empty">Couldn't load prices: ${esc(e.message)}</div>`;
  }
}

function renderWatch() {
  $("#watch-chips").innerHTML = watch.map((s) => `<button class="chip" data-unwatch="${esc(s)}">${esc(s)}<span class="x">✕</span></button>`).join("");
}

function newsHTML(items) {
  return items.map((i) => `<li>
      <a class="title" href="${esc(i.link)}" target="_blank" rel="noopener">${esc(i.title)}</a>
      ${i.summary ? `<div class="summary">${esc(i.summary)}</div>` : ""}
      <div class="meta"><span class="src">${esc(i.source)}</span><span>${timeAgo(i.time)}</span></div>
    </li>`).join("") || `<li class="empty">No headlines found.</li>`;
}

function videosHTML(items, searchable) {
  return items.map((v) => `<a class="video" href="${esc(v.link)}" target="_blank" rel="noopener">
      <div class="thumb" style="${v.image ? `background-image:url('${esc(v.image)}')` : ""}">${v.image ? "" : "▶"}</div>
      <div class="vt">${esc(v.title)}</div>
      <div class="vm">${esc(v.source)}${v.views != null ? ` · <span class="views">${fmtViews(v.views)}</span>` : ""}${v.time ? ` · ${timeAgo(v.time)}` : ""}</div></a>`).join("")
    || `<div class="empty">No matching videos from the followed channels.${searchable ? "" : " Add a YOUTUBE_API_KEY to search all of YouTube."}</div>`;
}

async function loadNews() {
  const list = $("#news");
  list.innerHTML = `<li class="empty">Loading headlines…</li>`;
  $("#news-filter").hidden = !tickerFilter;
  $("#news-filter").innerHTML = `News for <b>${esc(tickerFilter)}</b> <button data-clear="news">✕ show all</button>`;
  try {
    const data = await api(`/markets/news?q=${encodeURIComponent(tickerFilter)}`);
    list.innerHTML = newsHTML(data.items);
  } catch (e) { list.innerHTML = `<li class="empty">${esc(e.message)}</li>`; }
}

async function loadTalk() {
  const list = $("#talk");
  list.innerHTML = `<li class="empty">Loading…</li>`;
  try {
    const data = await api(`/markets/talk?sort=${$("#talk-sort").value}`);
    list.innerHTML = data.items.map((p) => `<li>
      <a class="title" href="${esc(p.link)}" target="_blank" rel="noopener">${esc(p.title)}</a>
      <div class="meta"><span class="src">${esc(p.source)}</span>
        ${p.flair ? `<span class="flair">${esc(p.flair)}</span>` : ""}
        <span>⬆ ${(p.score || 0).toLocaleString()}</span><span>💬 ${(p.comments || 0).toLocaleString()}</span>
        <span>${timeAgo(p.time)}</span></div>
    </li>`).join("") || `<li class="empty">Nothing right now.</li>`;
  } catch (e) { list.innerHTML = `<li class="empty">${esc(e.message)}</li>`; }
}

let ytTab = store.get("ytTab", "popular");

function fmtViews(n) {
  if (n == null) return "";
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M views`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}K views`;
  return `${n} views`;
}

async function loadVideos(q = tickerFilter) {
  $$("#yt-tabs .chip").forEach((c) => c.classList.toggle("active", !q && c.dataset.ytTab === ytTab));
  const box = $("#videos");
  box.innerHTML = `<div class="empty">Loading videos…</div>`;
  $("#yt-filter").hidden = !q;
  $("#yt-filter").innerHTML = `Videos for <b>${esc(q)}</b> <button data-clear="yt">✕ show latest</button>
    · <a href="https://www.youtube.com/results?search_query=${encodeURIComponent(`${q} stock`)}" target="_blank" rel="noopener">search on YouTube ↗</a>`;
  try {
    const data = await api(`/markets/videos?q=${encodeURIComponent(q)}&tab=${ytTab}`);
    box.innerHTML = videosHTML(data.items, data.searchable);
  } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

let marketsLoaded = false;
function showMarkets() {
  if (!marketsLoaded) {
    marketsLoaded = true;
    renderWatch();
    loadNews();
    loadTalk();
    loadVideos();
  }
  loadRibbons();
}

/* ============================ BETTING ============================ */

let leagues = [];
let league = store.get("league", "all");
let gamesData = { games: [] };
const openBooks = new Set();

function oddsFmt(american) {
  if (american == null || Number.isNaN(american)) return "-";
  const a = Number(american);
  const mode = $("#odds-format").value;
  if (mode === "decimal") return (a > 0 ? 1 + a / 100 : 1 + 100 / -a).toFixed(2);
  if (mode === "pct") return `${Math.round((a > 0 ? 100 / (a + 100) : -a / (-a + 100)) * 100)}%`;
  return a > 0 ? `+${a}` : `${a}`;
}

const pt = (n) => (n == null ? "" : n > 0 ? `+${n}` : `${n}`);

function localTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return `${sameDay ? "Today" : d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })} ${d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

function teamRow(t, ml, best, lost) {
  const logo = t.logo ? `<img class="team-logo" src="${esc(t.logo)}" alt="" loading="lazy">` : `<span class="team-logo ph">${esc((t.abbr || t.name).slice(0, 3))}</span>`;
  return `<div class="team-row ${lost ? "loser" : ""}">${logo}
    <span class="team-name">${esc(t.name)}<small>${esc(t.record)}</small></span>
    <span class="score">${esc(t.score)}</span>
    <span class="ml ${best ? "best" : ""}" title="Moneyline${best ? ` · best at ${esc(best)}` : ""}">${oddsFmt(ml)}</span></div>`;
}

function booksTable(g) {
  const b = g.best || {};
  const cell = (row, k, extra = "") => `<td class="${b[k] && b[k].price === row[k] ? "best" : ""}">${extra}${oddsFmt(row[k])}</td>`;
  const home = esc(g.home.abbr || "Home"), away = esc(g.away.abbr || "Away");
  return `<div class="books-wrap"><table class="books"><thead><tr><th>Book</th><th>${away}</th><th>${home}</th><th>${home} spread</th><th>Total</th></tr></thead><tbody>
    ${g.books.map((r) => `<tr><td>${esc(r.book)}</td>${cell(r, "away_ml")}${cell(r, "home_ml")}
      <td>${r.home_spread != null ? `${pt(r.home_spread)}<br><small>${oddsFmt(r.home_spread_price)}</small>` : "-"}</td>
      <td>${r.total != null ? `${r.total}<br><small>o${oddsFmt(r.over_price)} u${oddsFmt(r.under_price)}</small>` : "-"}</td></tr>`).join("")}
  </tbody></table></div>`;
}

function gameCard(g) {
  const o = g.odds || {};
  const best = g.best || {};
  const awayMl = best.away_ml?.price ?? o.away_ml;
  const homeMl = best.home_ml?.price ?? o.home_ml;
  const status = g.state === "pre" ? localTime(g.start) : g.detail;
  const lostAway = g.state === "post" && g.home.winner;
  const lostHome = g.state === "post" && g.away.winner;
  const b0 = g.books?.[0];
  const spread = o.spread || (b0?.home_spread != null ? `${g.home.abbr || g.home.short} ${pt(b0.home_spread)}` : "");
  const total = o.total ?? b0?.total;
  return `<div class="game ${g.state === "in" ? "is-live" : ""}" data-id="${esc(g.id)}">
    <div class="game-top"><span>${g.emoji} ${esc(g.league_name)}${g.broadcast ? ` · ${esc(g.broadcast)}` : ""}</span>
      <span class="status ${g.state === "in" ? "live" : ""}">${esc(status)}</span></div>
    ${teamRow(g.away, awayMl, best.away_ml?.book, lostAway)}
    ${teamRow(g.home, homeMl, best.home_ml?.book, lostHome)}
    <div class="line-row">
      ${spread ? `<span class="pill">Spread <b>${esc(spread)}</b></span>` : ""}
      ${total != null ? `<span class="pill">O/U <b>${esc(total)}</b></span>` : ""}
      ${o.draw_ml != null || best.draw_ml ? `<span class="pill">Draw <b>${oddsFmt(best.draw_ml?.price ?? o.draw_ml)}</b></span>` : ""}
      ${o.provider && !g.books?.length ? `<span class="pill">${esc(o.provider)}</span>` : ""}
      ${g.odds_live ? `<span class="pill live-odds" title="Prices fetched during the game ${esc(ago(g.odds_at))}">⚡ Live odds</span>`
        : g.state === "in" && (spread || total != null) ? `<span class="pill" title="The line from before kickoff">Pre-game line</span>` : ""}
      ${!spread && total == null && awayMl == null ? `<span class="pill">No line posted yet</span>` : ""}
    </div>
    <div class="game-actions">
      ${g.books?.length ? `<button class="btn" data-books="${esc(g.id)}">${openBooks.has(g.id) ? "Hide" : "Compare"} ${g.books.length} ${g.books.length === 1 ? "book" : "books"}</button>` : ""}
      <button class="btn-outline" data-ask-game="${esc(g.id)}">✨ Ask RMT</button>
      ${g.link ? `<a class="btn" href="${esc(g.link)}" target="_blank" rel="noopener">Gamecast ↗</a>` : ""}
    </div>
    ${openBooks.has(g.id) && g.books?.length ? booksTable(g) : ""}
  </div>`;
}

function visibleGames() {
  const state = $("#game-state").value;
  const find = $("#game-find").value.trim().toLowerCase();
  return gamesData.games.filter((g) => (!state || g.state === state)
    && (!find || `${g.home.name} ${g.away.name} ${g.home.abbr} ${g.away.abbr}`.toLowerCase().includes(find)));
}

function ago(t) {
  if (!t) return "never";
  const m = Math.round((Date.now() / 1000 - t) / 60);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
}

function renderGamesNote() {
  const note = $("#games-note");
  const live = gamesData.games.filter((g) => g.state === "in").length;
  const sp = streamInfo.sports || {};
  const parts = [];
  if (live) parts.push(`<span class="live-dot">●</span> <b>${live} live</b>${sp.status === "live" ? ` · scores update every ${sp.every || 15}s` : ""}`);
  const b = gamesData.odds_budget;
  if (gamesData.multi_book && b) {
    const fetched = Math.max(0, ...gamesData.games.map((g) => g.odds_at || 0));
    const credits = b.remaining != null ? `${b.remaining} odds credits left this month` : "";
    const every = b.every_min ? (b.every_min >= 60 ? `about every ${Math.round(b.every_min / 60)} h` : `about every ${b.every_min} min`) : "";
    parts.push(`Odds from many sportsbooks · updated ${ago(fetched)}${credits ? ` · ${credits}` : ""}${every ? `, refreshing ${every}` : ""}`);
    if (league !== "all") parts.push(`<button class="link-btn" id="odds-now" title="Uses 3 credits">↻ Update odds now</button>`);
    else parts.push(`<span class="muted">Pick a league to refresh its odds</span>`);
  } else if (gamesData.games.length) {
    parts.push("Showing one sportsbook's line per game. Add a free Odds API key under ⚙ → Live data to compare DraftKings, FanDuel, BetMGM and more side by side.");
  }
  note.hidden = !parts.length;
  note.innerHTML = parts.join(" · ");
}

// Pushed from the server: games whose score, clock or line just changed.
function applyGames(items) {
  const changed = [];
  for (const g of items) {
    const i = gamesData.games.findIndex((x) => x.id === g.id);
    if (i >= 0) {
      const old = gamesData.games[i];
      if (old.home.score !== g.home.score || old.away.score !== g.away.score) changed.push(g.id);
      gamesData.games[i] = { ...g, books: g.books?.length ? g.books : old.books, best: g.books?.length ? g.best : old.best };
    } else if ((league === "all" || g.league === league) && !$("#game-date").value) {
      gamesData.games.push(g);
    }
  }
  const order = { in: 0, pre: 1, post: 2 };
  gamesData.games.sort((a, b) => (order[a.state] ?? 1) - (order[b.state] ?? 1) || (a.start || "").localeCompare(b.start || ""));
  if ($("#sports").hidden) return;
  renderGames();
  for (const id of changed) document.querySelector(`.game[data-id="${CSS.escape(id)}"]`)?.classList.add("score-flash");
}

function renderGames() {
  const games = visibleGames();
  let html = games.map(gameCard).join("");
  if (league === "all") {  // group by league, keeping live-first order inside each
    const byLeague = {};
    games.forEach((g) => { (byLeague[g.league] ||= []).push(g); });
    html = Object.values(byLeague).map((lst) => `<h3 class="league-head">${lst[0].emoji} ${esc(lst[0].league_name)}</h3>${lst.map(gameCard).join("")}`).join("");
  }
  $("#games").innerHTML = html || `<div class="empty">No games match. Try another league or date.</div>`;
  renderGamesNote();

  const ticks = gamesData.games.slice(0, 60).map((g) => {
    const o = g.odds || {};
    const b0 = g.books?.[0];
    const line = o.spread || (b0?.home_spread != null ? `${g.home.abbr || g.home.short} ${pt(b0.home_spread)}` : "");
    const total = o.total ?? b0?.total;
    const score = g.state !== "pre" ? ` ${g.away.score}-${g.home.score}` : "";
    return `<span class="odd-tick" data-jump="${esc(g.id)}"><span class="lg">${g.emoji}</span>
      <span class="mu">${esc(g.away.abbr || g.away.short)} @ ${esc(g.home.abbr || g.home.short)}${esc(score)}</span>
      ${g.state === "in" ? `<span class="live">LIVE</span>` : ""}
      ${line ? `<span class="ln">${esc(line)}</span>` : ""}${total != null ? `<span>O/U ${esc(total)}</span>` : ""}</span>`;
  }).join("");
  if ($("#odds-ribbon").dataset.ticks !== ticks) {  // redraw only when a line or score changed
    $("#odds-ribbon").outerHTML = ticks
      ? ribbonHTML("Lines & Scores", ticks, gamesData.games.length).replace('class="ribbon"', 'class="ribbon" id="odds-ribbon"')
      : `<div class="ribbon" id="odds-ribbon"></div>`;
    $("#odds-ribbon").dataset.ticks = ticks;
  }
}

async function loadGames(quiet = false) {
  if (!quiet) $("#games").innerHTML = `<div class="empty">Loading games & odds…</div>`;
  const date = $("#game-date").value.replaceAll("-", "");
  try {
    gamesData = await api(`/sports/games?league=${league}&date=${date}`);
    badge(gamesData.live);
    stamp();
    renderGames();
  } catch (e) { $("#games").innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

function renderLeagues() {
  $("#league-chips").innerHTML = [{ id: "all", name: "All sports", emoji: "🔥" }, ...leagues]
    .map((l) => `<button class="chip ${l.id === league ? "active" : ""}" data-league="${l.id}">${l.emoji} ${esc(l.name)}</button>`).join("");
  $("#standings-league").innerHTML = leagues.filter((l) => l.id !== "ufc")
    .map((l) => `<option value="${l.id}" ${l.id === (league === "all" ? "nfl" : league) ? "selected" : ""}>${esc(l.name)}</option>`).join("");
}

async function loadStandings() {
  const box = $("#standings");
  box.innerHTML = `<div class="empty">Loading…</div>`;
  try {
    const data = await api(`/sports/standings?league=${$("#standings-league").value}`);
    box.innerHTML = data.groups.map((g) => `<table><caption>${esc(g.name)}</caption>
      <thead><tr><th>Team</th>${g.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
      <tbody>${g.rows.map((r) => `<tr><td>${r.logo ? `<img src="${esc(r.logo)}" alt="" loading="lazy">` : ""}${esc(r.team)}</td>
        ${r.stats.map((s) => `<td>${esc(s)}</td>`).join("")}</tr>`).join("")}</tbody></table>`).join("")
      || `<div class="empty">No standings for this league right now.</div>`;
  } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

let sportsLoaded = false;
async function showSports() {
  if (!sportsLoaded) {
    sportsLoaded = true;
    try { leagues = await api("/sports/leagues"); } catch { leagues = []; }
    renderLeagues();
    loadStandings();
  }
  loadGames();
}

/* ============================ CHAT ============================ */

let chat = store.get("chat", []);
const SUGGEST = {
  markets: ["What's moving the market today?", "What is r/wallstreetbets hyped about?", "Give me a quick read on NVDA"],
  sports: ["Best value bets on tonight's NBA games?", "Compare Jalen Hurts and Josh Allen this season", "Which NFL teams are hot against the spread?"],
};

function md(text) {
  // Small Markdown → HTML for chat answers. Everything is escaped first.
  const inline = (s) => esc(s)
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|\W)_([^_]+)_(?=\W|$)/g, "$1<i>$2</i>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  const lines = text.split("\n");
  let out = "", i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const body = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r));
      out += `<table><thead><tr>${cells(body[0]).map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${
        body.slice(1).map((r) => `<tr>${cells(r).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
      continue;
    }
    if (/^\s*([-*•]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*•]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*•]|\d+\.)\s+/, ""));
      out += `<${ordered ? "ol" : "ul"}>${items.map((it) => `<li>${inline(it)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`;
      continue;
    }
    if (/^#{1,6}\s/.test(line)) { out += `<h4>${inline(line.replace(/^#+\s/, ""))}</h4>`; i++; continue; }
    if (!line.trim()) { i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(\||[-*•]\s|\d+\.\s|#)/.test(lines[i])) para.push(lines[i++]);
    if (!para.length) para.push(lines[i++]);
    out += `<p>${para.map(inline).join("<br>")}</p>`;
  }
  return out;
}

function renderChat() {
  const log = $("#chat-log");
  if (!chat.length) {
    log.innerHTML = `<div class="msg bot"><p><b>Welcome to RMT.</b> Ask me about any stock, crypto, game, line or player.
      I use RMT's live prices, headlines and odds, and search the web for stats and injury news.</p></div>`;
  } else {
    log.innerHTML = chat.map((m) => m.role === "user"
      ? `<div class="msg user">${esc(m.content)}</div>`
      : `<div class="msg bot ${m.error ? "err" : ""}">${md(m.content)}
          ${m.used?.length ? `<div class="used">Used: ${m.used.map(esc).join(", ")}</div>` : ""}
          ${m.sources?.length ? `<div class="sources">${m.sources.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">↗ ${esc(s.title)}</a>`).join("")}</div>` : ""}
        </div>`).join("");
  }
  const mode = location.hash === "#sports" ? "sports" : "markets";
  $("#chat-suggest").innerHTML = chat.length ? "" : SUGGEST[mode].map((s) => `<button class="chip" data-suggest="${esc(s)}">${esc(s)}</button>`).join("");
  log.scrollTop = log.scrollHeight;
}

function openChat(prefill) {
  $("#chat").hidden = false;
  renderChat();
  if (prefill) $("#chat-input").value = prefill;
  $("#chat-input").focus();
}

async function sendChat(text) {
  text = text.trim();
  if (!text) return;
  chat.push({ role: "user", content: text });
  $("#chat-input").value = "";
  renderChat();
  $("#chat-log").insertAdjacentHTML("beforeend", `<div class="thinking"><span></span><span></span><span></span></div>`);
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  $("#chat-send").disabled = true;
  try {
    const history = chat.filter((m) => !m.error).map(({ role, content }) => ({ role, content }));
    const res = await api("/chat", { messages: history });
    chat.push({ role: "assistant", content: res.reply, sources: res.sources, used: res.used });
  } catch (e) {
    chat.push({ role: "assistant", content: e.message, error: true });
  }
  $("#chat-send").disabled = false;
  store.set("chat", chat.slice(-40));
  renderChat();
}

/* ============================ STOCK LOOKUP ============================ */

const stockPage = { symbol: "", quote: null, range: store.get("chartRange", "1d"), info: null };

// --- search box with suggestions ---
let ssTimer = null, ssItems = [], ssActive = -1;

function ssRender() {
  const list = $("#ss-list");
  list.hidden = !ssItems.length;
  $("#ss-input").setAttribute("aria-expanded", String(!list.hidden));
  list.innerHTML = ssItems.map((r, i) => `<button class="ss-item ${i === ssActive ? "active" : ""}" role="option" data-ss="${esc(r.symbol)}">
    <b>${esc(r.symbol)}</b><span>${esc(r.name)}</span><small>${esc(r.type)}${r.exchange ? ` · ${esc(r.exchange)}` : ""}</small></button>`).join("");
}

$("#ss-input").addEventListener("input", () => {
  clearTimeout(ssTimer);
  const q = $("#ss-input").value.trim();
  if (!q) { ssItems = []; ssRender(); return; }
  ssTimer = setTimeout(async () => {
    try { ssItems = await api(`/stock/search?q=${encodeURIComponent(q)}`); } catch { ssItems = []; }
    ssActive = ssItems.length ? 0 : -1;
    if ($("#ss-input").value.trim() === q) ssRender();
  }, 200);
});
$("#ss-input").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (!ssItems.length) return;
    ssActive = (ssActive + (e.key === "ArrowDown" ? 1 : -1) + ssItems.length) % ssItems.length;
    ssRender();
  } else if (e.key === "Enter") {
    e.preventDefault();
    const pick = ssItems[ssActive]?.symbol || $("#ss-input").value.trim().toUpperCase();
    if (pick) goStock(pick);
  } else if (e.key === "Escape") { ssItems = []; ssRender(); }
});
$("#ss-input").addEventListener("blur", () => setTimeout(() => { ssItems = []; ssRender(); }, 150));
$("#ss-list").addEventListener("mousedown", (e) => {
  const b = e.target.closest("[data-ss]");
  if (b) { e.preventDefault(); goStock(b.dataset.ss); }
});

function goStock(sym) {
  $("#ss-input").value = "";
  ssItems = [];
  ssRender();
  $("#ss-input").blur();
  location.hash = `stock/${encodeURIComponent(sym)}`;
}

// --- the page ---
function showStockPrice(q, flash = false) {
  if (!q || q.price == null) return;
  const prev = stockPage.quote?.price;
  stockPage.quote = q;
  const el = $("#st-price");
  el.textContent = fmtPrice(q.price);
  const ch = $("#st-change");
  ch.className = `st-change ${dir(q.pct)}`;
  ch.textContent = `${q.change >= 0 ? "+" : "−"}${fmtPrice(Math.abs(q.change))} (${fmtPct(q.pct).trim()}) today`;
  const live = $("#st-live");
  live.hidden = false;
  live.className = `badge ${q.streaming ? "live" : ""}`;
  live.textContent = q.streaming ? "LIVE" : q.realtime ? "Real-time" : "Delayed";
  live.title = q.streaming ? "Streaming live" : q.realtime ? "Real-time from Alpaca, refreshed" : "From Yahoo Finance, can be up to ~15 minutes behind";
  if (flash && prev != null && prev !== q.price) {
    el.classList.remove("flash-up", "flash-down");
    void el.offsetWidth;
    el.classList.add(q.price > prev ? "flash-up" : "flash-down");
  }
}

function stockLinks(sym, type) {
  const s = encodeURIComponent(sym);
  const links = [["Yahoo Finance", `https://finance.yahoo.com/quote/${s}`],
    ["TradingView", `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(sym.replace("-", "."))}`]];
  if (type === "Stock" || type === "ETF" || !type) {
    links.push(["Finviz", `https://finviz.com/quote.ashx?t=${encodeURIComponent(sym.replace("-", "."))}`],
      ["StockTwits", `https://stocktwits.com/symbol/${s}`]);
  }
  if (type === "Stock" || !type) links.push(["SEC filings", `https://www.sec.gov/edgar/search/#/q=${s}`]);
  return links.map(([n, u]) => `<a class="chip" href="${esc(u)}" target="_blank" rel="noopener">${esc(n)} ↗</a>`).join("");
}

async function openStock(sym) {
  sym = sym.toUpperCase();
  if (stockPage.symbol === sym && stockPage.info) return;
  Object.assign(stockPage, { symbol: sym, quote: null, info: null });
  window.scrollTo(0, 0);
  $("#st-name").textContent = sym;
  $("#st-sub").textContent = "Loading…";
  $("#st-price").textContent = "—";
  $("#st-change").textContent = "";
  $("#st-live").hidden = true;
  $("#st-stats").innerHTML = `<div class="empty">Loading…</div>`;
  $("#st-profile").innerHTML = "";
  $("#st-links").innerHTML = stockLinks(sym, "");
  $("#st-news").innerHTML = `<li class="empty">Loading news…</li>`;
  $("#st-videos").innerHTML = `<div class="empty">Loading videos…</div>`;
  $("#st-watch").textContent = watch.includes(sym) ? "★ On your watchlist" : "☆ Add to watchlist";
  loadChart();
  try {
    const info = await api(`/stock/info?symbol=${encodeURIComponent(sym)}`);
    if (stockPage.symbol !== sym) return;
    stockPage.info = info;
    $("#st-name").textContent = info.name;
    $("#st-sub").textContent = [info.symbol, info.type, info.exchange, info.currency !== "USD" ? info.currency : ""].filter(Boolean).join(" · ");
    showStockPrice(info.quote);
    $("#st-stats").innerHTML = info.stats.map((x) => `<div class="stat"><span>${esc(x.label)}</span><b>${esc(x.value)}</b></div>`).join("")
      || `<div class="empty">No stats available.</div>`;
    const note = $("#st-stats-note");
    note.hidden = info.full_stats;
    note.textContent = "Yahoo Finance didn't share the full stats (market cap, P/E, dividend…) just now. Use the links on the right for more.";
    const p = info.profile || {};
    $("#st-profile").innerHTML = [
      p.sector || p.industry ? `<p><b>${esc([p.sector, p.industry].filter(Boolean).join(" · "))}</b></p>` : "",
      p.employees ? `<p class="muted">${esc(p.employees)} employees</p>` : "",
      p.summary ? `<p class="summary-text">${esc(p.summary)}</p>` : "",
      p.website ? `<p><a href="${esc(p.website)}" target="_blank" rel="noopener">${esc(p.website.replace(/^https?:\/\//, ""))} ↗</a></p>` : "",
    ].join("") || `<p class="muted">No company profile for this one.</p>`;
    $("#st-links").innerHTML = stockLinks(sym, info.type);
  } catch (e) {
    $("#st-sub").textContent = e.message;
    $("#st-stats").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
  const q = sym.replace(/-USD$/, "").replace(/^\^/, "");
  api(`/markets/news?q=${encodeURIComponent(q)}`).then((d) => { if (stockPage.symbol === sym) $("#st-news").innerHTML = newsHTML(d.items.slice(0, 20)); })
    .catch((e) => { $("#st-news").innerHTML = `<li class="empty">${esc(e.message)}</li>`; });
  api(`/markets/videos?q=${encodeURIComponent(q)}`).then((d) => { if (stockPage.symbol === sym) $("#st-videos").innerHTML = videosHTML(d.items.slice(0, 12), d.searchable); })
    .catch((e) => { $("#st-videos").innerHTML = `<div class="empty">${esc(e.message)}</div>`; });
}

function closeStock() {
  stockPage.symbol = "";
  stockPage.info = null;
  api("/stock/close", {}).catch(() => {});  // free its live-stream slot
}

async function loadChart() {
  const sym = stockPage.symbol, rng = stockPage.range;
  $$("#st-ranges [data-range]").forEach((c) => c.classList.toggle("active", c.dataset.range === rng));
  $("#st-chart").innerHTML = `<div class="empty">Loading chart…</div>`;
  $("#st-range-change").textContent = "";
  try {
    const c = await api(`/stock/chart?symbol=${encodeURIComponent(sym)}&range=${rng}`);
    if (stockPage.symbol !== sym || stockPage.range !== rng) return;
    drawChart($("#st-chart"), c.points, c.prev_close, rng);
  } catch (e) { $("#st-chart").innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

// --- the price chart: one line, a crosshair + tooltip on hover ---
const CHART_UP = "#2bf27f", CHART_DOWN = "#ff4d6a";

function tickLabel(t, rng) {
  const d = new Date(t * 1000);
  if (rng === "1d") return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (rng === "5d") return d.toLocaleDateString([], { weekday: "short" });
  if (rng === "5y") return String(d.getFullYear());
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function hoverLabel(t, rng) {
  const d = new Date(t * 1000);
  const date = d.toLocaleDateString([], { weekday: rng === "5d" ? "short" : undefined, month: "short", day: "numeric", year: ["1y", "5y"].includes(rng) ? "numeric" : undefined });
  return ["1d", "5d", "1mo"].includes(rng) ? `${date}, ${d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : date;
}

function drawChart(el, pts, prevClose, rng) {
  if (!pts || pts.length < 2) { el.innerHTML = `<div class="empty">No chart data for this range.</div>`; return; }
  const W = Math.max(el.clientWidth, 300), H = 300, L = 8, R = 64, T = 14, B = 26;
  const base = prevClose ?? pts[0][1];
  const prices = pts.map((p) => p[1]).concat(prevClose != null ? [prevClose] : []);
  let lo = Math.min(...prices), hi = Math.max(...prices);
  const pad = (hi - lo || hi * 0.01 || 1) * 0.08;
  lo -= pad; hi += pad;
  // x by position, not time: no flat gaps over nights and weekends
  const x = (i) => L + (i / (pts.length - 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const last = pts[pts.length - 1][1];
  const color = last >= base ? CHART_UP : CHART_DOWN;
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
  const area = `${line}L${x(pts.length - 1).toFixed(1)},${H - B}L${x(0).toFixed(1)},${H - B}Z`;
  const grid = [0, 1, 2, 3].map((k) => {
    const v = lo + pad + (k / 3) * (hi - lo - 2 * pad);
    return `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="grid"/>
      <text x="${W - R + 8}" y="${(y(v) + 4).toFixed(1)}" class="axis">${fmtPrice(v)}</text>`;
  }).join("");
  const ticks = 5;
  const xlabels = Array.from({ length: ticks }, (_, k) => Math.round((k / (ticks - 1)) * (pts.length - 1))).map((i, k) =>
    `<text x="${x(i).toFixed(1)}" y="${H - 7}" class="axis" text-anchor="${k === 0 ? "start" : k === ticks - 1 ? "end" : "middle"}">${esc(tickLabel(pts[i][0], rng))}</text>`).join("");
  const prevLine = prevClose != null ? `<line x1="${L}" x2="${W - R}" y1="${y(prevClose).toFixed(1)}" y2="${y(prevClose).toFixed(1)}" class="prev"/>
    <text x="${L + 4}" y="${(y(prevClose) - 5).toFixed(1)}" class="axis">Prev close ${fmtPrice(prevClose)}</text>` : "";
  const chg = last - base, chgPct = (chg / base) * 100;
  $("#st-range-change").innerHTML = `<span class="${dir(chg)}">${chg >= 0 ? "+" : "−"}${fmtPrice(Math.abs(chg))} (${fmtPct(chgPct).trim()})</span> <span class="muted">${{ "1d": "today", "5d": "past 5 days", "1mo": "past month", "6mo": "past 6 months", ytd: "this year", "1y": "past year", "5y": "past 5 years" }[rng]}</span>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img"
      aria-label="${esc(stockPage.symbol)} price, ${esc(hoverLabel(pts[0][0], rng))} to ${esc(hoverLabel(pts[pts.length - 1][0], rng))}: ${fmtPrice(pts[0][1])} to ${fmtPrice(last)}">
    <defs><linearGradient id="st-fill" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="${color}" stop-opacity="0.22"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    ${grid}${prevLine}
    <path d="${area}" fill="url(#st-fill)"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    ${xlabels}
    <g class="cross" visibility="hidden"><line class="cross-line" y1="${T}" y2="${H - B}"/><circle r="4.5" fill="${color}" stroke="#0d1c14" stroke-width="2"/></g>
    <rect x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent" class="hit"/>
  </svg><div class="chart-tip" hidden></div>`;
  const svg = el.querySelector("svg"), cross = svg.querySelector(".cross"), tip = el.querySelector(".chart-tip");
  const move = (clientX) => {
    const r = svg.getBoundingClientRect();
    const px = ((clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(pts.length - 1, Math.round(((px - L) / (W - L - R)) * (pts.length - 1))));
    const [t, v] = pts[i];
    cross.setAttribute("visibility", "visible");
    cross.querySelector("line").setAttribute("x1", x(i)); cross.querySelector("line").setAttribute("x2", x(i));
    cross.querySelector("circle").setAttribute("cx", x(i)); cross.querySelector("circle").setAttribute("cy", y(v));
    const c = v - base;
    tip.hidden = false;
    tip.innerHTML = `<b>${fmtPrice(v)}</b> <span class="${dir(c)}">${fmtPct((c / base) * 100).trim()}</span><br><span class="muted">${esc(hoverLabel(t, rng))}</span>`;
    const left = (x(i) / W) * r.width;
    tip.style.left = `${Math.min(Math.max(left - tip.offsetWidth / 2, 0), r.width - tip.offsetWidth)}px`;
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; };
  svg.addEventListener("pointermove", (e) => move(e.clientX));
  svg.addEventListener("pointerleave", hide);
}

$("#st-ranges").addEventListener("click", (e) => {
  const b = e.target.closest("[data-range]");
  if (!b) return;
  stockPage.range = b.dataset.range;
  store.set("chartRange", stockPage.range);
  loadChart();
});
$("#stock-back").addEventListener("click", () => { if (history.length > 1) history.back(); else location.hash = "markets"; });
$("#st-watch").addEventListener("click", () => {
  const sym = stockPage.symbol;
  if (!watch.includes(sym)) {
    watch = [sym, ...watch].slice(0, 30);
    store.set("watch", watch);
    renderWatch();
    $("#ribbons").dataset.layout = "";  // redraw the ribbons with the new watchlist next time
  }
  $("#st-watch").textContent = "★ On your watchlist";
});
$("#st-ask").addEventListener("click", () => {
  const n = stockPage.info?.name || stockPage.symbol;
  openChat(`Give me a quick read on ${n} (${stockPage.symbol}): what's moving it lately, key numbers vs. peers, upcoming catalysts like earnings, and the main bull and bear case.`);
});
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (!$("#stock").hidden && stockPage.symbol) loadChart(); }, 250);
});

/* ============================ WIRING ============================ */

function showMode() {
  const stockSym = location.hash.startsWith("#stock/") ? decodeURIComponent(location.hash.slice(7)) : "";
  const mode = stockSym ? "stock" : location.hash === "#sports" ? "sports" : "markets";
  $$(".mode").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $("#markets").hidden = mode !== "markets";
  $("#sports").hidden = mode !== "sports";
  $("#stock").hidden = mode !== "stock";
  if (mode !== "stock" && stockPage.symbol) closeStock();
  if (mode === "markets") showMarkets(); else if (mode === "sports") showSports(); else openStock(stockSym);
  if (!$("#chat").hidden) renderChat();
}

document.addEventListener("click", (e) => {
  if (e.target.id === "odds-now") {
    e.target.textContent = "Updating odds…";
    api(`/sports/odds-now?league=${league}`, {}).then((d) => { gamesData = d; renderGames(); })
      .catch((err) => { e.target.textContent = err.message; });
    return;
  }
  const tab = e.target.closest("[data-yt-tab]");
  if (tab) {
    ytTab = tab.dataset.ytTab;
    store.set("ytTab", ytTab);
    $("#yt-q").value = "";
    loadVideos("");
    return;
  }
  const t = e.target.closest("[data-mode],[data-sym],[data-unwatch],[data-clear],[data-league],[data-books],[data-ask-game],[data-jump],[data-suggest]");
  if (!t) return;
  const d = t.dataset;
  if (d.mode) location.hash = d.mode;
  else if (d.sym) location.hash = `stock/${encodeURIComponent(d.sym)}`;
  else if (d.unwatch) { watch = watch.filter((s) => s !== d.unwatch); store.set("watch", watch); renderWatch(); loadRibbons(); }
  else if (d.clear) { tickerFilter = ""; $("#news-q").value = ""; $("#yt-q").value = ""; d.clear === "news" ? loadNews() : loadVideos(""); }
  else if (d.league) {
    league = d.league; store.set("league", league); renderLeagues();
    if (league !== "all") loadStandings();
    loadGames();
  } else if (d.books) { openBooks.has(d.books) ? openBooks.delete(d.books) : openBooks.add(d.books); renderGames(); }
  else if (d.askGame) {
    const g = gamesData.games.find((x) => x.id === d.askGame);
    if (g) openChat(`Break down ${g.away.name} @ ${g.home.name} (${g.league_name}, ${g.state === "pre" ? localTime(g.start) : g.detail}): recent form, key stats, injuries, and where the value is in the moneyline, spread and total.`);
  } else if (d.jump) {
    const el = document.querySelector(`.game[data-id="${CSS.escape(d.jump)}"]`);
    if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.animate([{ outline: "2px solid #b8ff5c" }, { outline: "2px solid transparent" }], 1500); }
  } else if (d.suggest) sendChat(d.suggest);
});

$("#watch-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const add = $("#watch-input").value.toUpperCase().split(/[\s,]+/).filter(Boolean);
  watch = [...new Set([...watch, ...add])].slice(0, 30);
  store.set("watch", watch);
  $("#watch-input").value = "";
  renderWatch();
  loadRibbons();
});
$("#news-form").addEventListener("submit", (e) => { e.preventDefault(); tickerFilter = $("#news-q").value.trim(); loadNews(); });
$("#yt-form").addEventListener("submit", (e) => { e.preventDefault(); loadVideos($("#yt-q").value.trim()); });
$("#talk-sort").addEventListener("change", loadTalk);
$("#game-date").addEventListener("change", () => loadGames());
$("#game-state").addEventListener("change", renderGames);
$("#game-find").addEventListener("input", renderGames);
$("#odds-format").addEventListener("change", () => { store.set("oddsFormat", $("#odds-format").value); renderGames(); });
$("#standings-league").addEventListener("change", loadStandings);

$("#stat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#stat-q").value.trim();
  if (!q) return;
  const box = $("#stat-results");
  box.innerHTML = `<div class="empty">Searching…</div>`;
  $("#stat-ask").hidden = false;
  try {
    const data = await api(`/sports/search?q=${encodeURIComponent(q)}`);
    box.innerHTML = data.items.map((r) => `<a class="stat-item" href="${esc(r.link)}" target="_blank" rel="noopener">
      ${r.image ? `<img src="${esc(r.image)}" alt="" loading="lazy">` : ""}
      <span><b>${esc(r.name)}</b><small>${esc(r.detail)}${r.type ? ` · ${esc(r.type)}` : ""}</small></span></a>`).join("")
      || `<div class="empty">No players or teams found.</div>`;
  } catch (err) { box.innerHTML = `<div class="empty">${esc(err.message)}</div>`; }
});
$("#stat-ask").addEventListener("click", () => openChat(`Give me the key stats for ${$("#stat-q").value.trim()} this season, recent form (last 5 games) and any injury news.`));

$("#chat-open").addEventListener("click", () => openChat());
$("#chat-close").addEventListener("click", () => { $("#chat").hidden = true; });
$("#chat-clear").addEventListener("click", () => { chat = []; store.set("chat", chat); renderChat(); });
$("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); sendChat($("#chat-input").value); });
$("#chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat($("#chat-input").value); }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("#chat").hidden = true; $("#settings").hidden = true; } });

$("#odds-format").value = store.get("oddsFormat", "american");
window.addEventListener("hashchange", showMode);
showMode();

/* ===================== LIVE PRICES ===================== */

// The server keeps live connections to Coinbase (crypto) and Alpaca (stocks)
// and pushes each new price here.
const streamInfo = { crypto: { status: "off" }, stocks: { status: "off" }, finnhub: { status: "off" }, sports: { status: "off" } };
const lastPx = {};

function applyLive(items) {
  for (const p of items) {
    if (p.symbol === stockPage.symbol) showStockPrice({ ...stockPage.quote, price: p.price, change: p.change, pct: p.pct, streaming: true }, true);
    const els = $$(`#ribbons .tick[data-sym="${CSS.escape(p.symbol)}"]`);
    const prev = lastPx[p.symbol];
    lastPx[p.symbol] = p.price;
    for (const el of els) {
      const px = el.querySelector(".tick-px");
      const ch = el.querySelector(".tick-ch");
      if (!px || !ch) continue;
      if (!el.querySelector(".bolt")) el.insertAdjacentHTML("afterbegin", `<span class="bolt" title="Live">⚡</span>`);
      px.textContent = fmtPrice(p.price);
      ch.className = `tick-ch ${dir(p.pct)}`;
      ch.textContent = fmtPct(p.pct);
      if (prev != null && prev !== p.price) {
        el.classList.remove("flash-up", "flash-down");
        void el.offsetWidth;  // restart the flash animation
        el.classList.add(p.price > prev ? "flash-up" : "flash-down");
      }
    }
  }
}

function showStreamStatus() {
  const c = streamInfo.crypto, k = streamInfo.stocks;
  const cryptoLive = c.status === "live";
  $$('.ribbon[data-id="crypto"]').forEach((r) => {
    r.classList.toggle("streaming", cryptoLive);
    r.title = cryptoLive ? `Live prices from ${c.source} (24-hour change)` : "";
  });
  const cryptoText = {
    live: `⚡ Live, streaming from ${c.source}`,
    connecting: `Connecting to ${c.source}…`,
    offline: `Can't reach Coinbase right now${c.error ? ` (${c.error})` : ""}. Showing regular prices; retrying.`,
    off: "Off (sample-data mode)",
  }[c.status] || c.status;
  const market = k.market_open === false ? " · market closed, prices move again at the next open" : "";
  const stockText = {
    live: `⚡ Live from Alpaca: ${k.streaming} stocks streaming, the rest real-time on each refresh${market}`,
    connecting: "Connecting to Alpaca…",
    offline: `Alpaca: ${k.error || "disconnected"}. Retrying.`,
    error: k.error,
    off: "Yahoo Finance (up to ~15 min delayed). Add free Alpaca keys below for real-time prices.",
  }[k.status] || k.status;
  const f = streamInfo.finnhub;
  const finnText = {
    live: `⚡ Live from Finnhub: ${f.streaming} more stocks streaming`,
    connecting: "Connecting to Finnhub…",
    offline: `Finnhub: ${f.error || "disconnected"}. Retrying.`,
    error: f.error,
    off: "Off. Add a free Finnhub key below to stream ~50 more stocks live.",
  }[f.status] || f.status;
  $("#sources-status").innerHTML = `<div class="source"><span>🪙 Crypto</span><span class="${cryptoLive ? "up" : "muted"}">${esc(cryptoText)}</span></div>
    <div class="source"><span>📈 Stocks (Alpaca)</span><span class="${k.status === "live" ? "up" : k.status === "error" ? "down" : "muted"}">${esc(stockText)}</span></div>
    <div class="source"><span>📈 More stocks (Finnhub)</span><span class="${f.status === "live" ? "up" : f.status === "error" ? "down" : "muted"}">${esc(finnText)}</span></div>
    <div class="source"><span>🏈 Live scores</span><span class="${streamInfo.sports.status === "live" ? "up" : "muted"}">${
      streamInfo.sports.status === "live" ? `⚡ ESPN, games in progress update every ${streamInfo.sports.every || 15}s` : "ESPN, refreshed"}</span></div>
    <div class="source"><span>🎲 Odds</span><span class="muted">${(streamInfo.sports.odds || {}).configured
      ? `The Odds API: many sportsbooks, live during games${(streamInfo.sports.odds || {}).remaining != null ? ` · ${streamInfo.sports.odds.remaining} credits left` : ""}`
      : "ESPN (one sportsbook). Add an Odds API key below for many sportsbooks and live odds."}</span></div>`;
  const hasKeys = k.configured && k.status !== "error";
  $("#alpaca-form").hidden = hasKeys && !alpacaEditing;
  $("#alpaca-change").hidden = !hasKeys || alpacaEditing;
  const hasFinn = f.configured && f.status !== "error";
  $("#finnhub-form").hidden = hasFinn && !finnhubEditing;
  $("#finnhub-change").hidden = !hasFinn || finnhubEditing;
}

// Odds API and Anthropic keys: paste, test, save. Once saved, the form shrinks to a "Change key" link.
async function showKeyForms() {
  let have = {};
  try { have = await api("/settings/keys"); } catch { /* older server */ }
  $$(".key-form").forEach((f) => {
    const saved = have[f.dataset.key];
    f.classList.toggle("saved", !!saved && !f.dataset.editing);
    const msg = f.querySelector(".key-msg");
    if (saved && !f.dataset.editing && !f.dataset.justSaved) {
      msg.innerHTML = `✅ Key saved. <button class="link-btn" type="button" data-change-key>Change key</button>`;
    }
  });
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-change-key]");
  if (!b) return;
  const f = b.closest(".key-form");
  f.dataset.editing = "1";
  f.classList.remove("saved");
  f.querySelector("input").focus();
});
$$(".key-form").forEach((f) => f.addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = f.querySelector("input"), msg = f.querySelector(".key-msg"), btn = f.querySelector("button");
  btn.disabled = true;
  msg.className = "small muted key-msg";
  msg.textContent = "Checking the key…";
  try {
    const res = await api("/settings/key", { name: f.dataset.key, value: input.value });
    msg.className = "small up key-msg";
    msg.textContent = `${res.message} Saved.`;
    input.value = "";
    delete f.dataset.editing;
    f.dataset.justSaved = "1";
    f.classList.add("saved");
    if (f.dataset.key === "ODDS_API_KEY" && sportsLoaded) loadGames(true);
  } catch (err) {
    msg.className = "small down key-msg";
    msg.textContent = err.message;
  }
  btn.disabled = false;
}));

let finnhubEditing = false;
$("#finnhub-change").addEventListener("click", () => { finnhubEditing = true; showStreamStatus(); $("#finnhub-key").focus(); });
$("#finnhub-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#finnhub-msg");
  $("#finnhub-save").disabled = true;
  msg.className = "small muted";
  msg.textContent = "Checking the key with Finnhub…";
  try {
    const res = await api("/settings/finnhub", { key: $("#finnhub-key").value });
    msg.className = "small up";
    msg.textContent = `${res.message} Saved. More live stocks start in a few seconds.`;
    $("#finnhub-key").value = "";
    finnhubEditing = false;
    setTimeout(loadRibbons, 3000);
  } catch (err) {
    msg.className = "small down";
    msg.textContent = err.message;
  }
  $("#finnhub-save").disabled = false;
});

let alpacaEditing = false;
$("#alpaca-change").addEventListener("click", () => { alpacaEditing = true; showStreamStatus(); $("#alpaca-key").focus(); });
$("#alpaca-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#alpaca-msg");
  const btn = $("#alpaca-save");
  btn.disabled = true;
  msg.className = "small muted";
  msg.textContent = "Checking the keys with Alpaca…";
  try {
    const res = await api("/settings/alpaca", { key_id: $("#alpaca-key").value, secret: $("#alpaca-secret").value });
    msg.className = "small up";
    msg.textContent = `${res.message} Saved. Live stock prices start in a few seconds.`;
    $("#alpaca-secret").value = "";
    alpacaEditing = false;
    setTimeout(loadRibbons, 3000);
  } catch (err) {
    msg.className = "small down";
    msg.textContent = err.message;
  }
  btn.disabled = false;
});

function startStream() {
  if (!window.EventSource) return;
  const es = new EventSource("/api/stream/live");  // reconnects by itself if the server restarts
  es.onmessage = (e) => {
    const d = JSON.parse(e.data);
    if (d.type === "prices") applyLive(d.items);
    else if (d.type === "games") applyGames(d.items);
    else if (d.type === "status") {
      streamInfo[d.stream] = d;
      showStreamStatus();
      if (d.stream === "sports" && !$("#sports").hidden) renderGamesNote();
    }
  };
}

/* ===================== REFRESH & UPDATES ===================== */

function stamp() {
  $("#updated-at").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
}

async function refreshNow() {
  const btn = $("#refresh-now");
  btn.classList.add("spinning");
  try { await api("/refresh", {}); } catch { /* still reload what we can */ }
  if (!$("#markets").hidden) await Promise.all([loadRibbons(), loadNews(), loadTalk(), loadVideos($("#yt-q").value.trim())]);
  else await Promise.all([loadGames(true), loadStandings()]);
  btn.classList.remove("spinning");
}

// Auto-refresh: prices on the Trading side, scores and odds on the Betting side.
let autoTimer = null;
function setAutoRefresh(seconds) {
  clearInterval(autoTimer);
  store.set("autoRefresh", seconds);
  if (seconds > 0) {
    autoTimer = setInterval(() => {
      if (document.hidden) return;
      if (!$("#markets").hidden) loadRibbons(); else loadGames(true);
    }, seconds * 1000);
  }
}

async function showVersion() {
  try {
    const info = await api("/app/info");
    $("#version-line").textContent = info.version
      ? `Version ${info.version}${info.updated_at ? ` · installed ${new Date(info.updated_at).toLocaleDateString()}` : ""}`
      : "Version: original download";
  } catch { $("#version-line").textContent = "Version: unknown"; }
}

async function checkUpdate(quiet = false) {
  const box = $("#update-box");
  if (!quiet) box.innerHTML = `<p class="muted">Checking GitHub…</p>`;
  try {
    const res = await api("/app/update");
    $("#update-dot").hidden = !res.available;
    if (res.error) box.innerHTML = quiet ? "" : `<p class="muted">${esc(res.error)}</p>`;
    else if (res.available) {
      box.innerHTML = `<div class="update-new"><p><b>New version available</b><br>${esc(res.latest.summary)}</p>
        <button id="update-now" class="btn-glow">Update now</button></div>`;
    } else box.innerHTML = quiet ? "" : `<p class="muted">✅ You have the latest version.</p>`;
  } catch (e) { if (!quiet) box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

async function installUpdate() {
  const box = $("#update-box");
  box.innerHTML = `<p class="muted">Downloading and installing… don't close RMT.</p>`;
  try {
    const before = await api("/app/info").catch(() => ({}));
    const res = await api("/app/update", {});
    if (res.error) { box.innerHTML = `<p class="muted">${esc(res.error)}</p>`; return; }
    if (!res.updated) { box.innerHTML = `<p class="muted">${esc(res.summary)}</p>`; return; }
    if (!res.restarting) {
      box.innerHTML = `<p class="muted">✅ Updated: ${esc(res.summary)}. Close RMT and open it again to finish.</p>`;
      return;
    }
    box.innerHTML = `<p class="muted">✅ Updated: ${esc(res.summary)}. Restarting RMT…</p>`;
    // Wait for the new server (a different process) to answer, then reload this window.
    const started = Date.now();
    const poll = async () => {
      try {
        const info = await api("/app/info");
        if (info.pid !== before.pid) { location.reload(); return; }
      } catch { /* still restarting */ }
      if (Date.now() - started < 120000) setTimeout(poll, 1000);
      else box.innerHTML = `<p class="muted">The update is installed. Close RMT and open it again.</p>`;
    };
    setTimeout(poll, 1500);
  } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

$("#refresh-now").addEventListener("click", refreshNow);
$("#auto-refresh").value = String(store.get("autoRefresh", 30));
$("#auto-refresh").addEventListener("change", () => setAutoRefresh(Number($("#auto-refresh").value)));
setAutoRefresh(Number($("#auto-refresh").value));
$("#settings-open").addEventListener("click", () => {
  $("#settings").hidden = !$("#settings").hidden;
  if (!$("#settings").hidden) { showVersion(); checkUpdate(); showKeyForms(); }
});
$("#update-check").addEventListener("click", () => checkUpdate());
api("/app/auto-update").then((r) => { $("#auto-update").checked = r.on; }).catch(() => {});
$("#auto-update").addEventListener("change", async () => {
  try { $("#auto-update").checked = (await api("/app/auto-update", { on: $("#auto-update").checked })).on; }
  catch (e) { $("#auto-update").checked = !$("#auto-update").checked; }
});

// Right after an update: say what's new, once.
function toast(html, ms = 9000) {
  const t = $("#toast");
  t.innerHTML = html;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, ms);
}
api("/app/info").then((info) => {
  const seen = store.get("seenVersion", null);
  if (info.version && seen && seen !== info.version) toast(`✨ <b>RMT was updated:</b> ${esc(info.summary || "latest version")}`);
  if (info.version) store.set("seenVersion", info.version);
}).catch(() => {});
document.addEventListener("click", (e) => {
  if (e.target.id === "update-now") installUpdate();
  else if (!$("#settings").hidden && !e.target.closest("#settings, #settings-open")) $("#settings").hidden = true;
});

startStream();

// Tell the server this window is still open (it stops itself a few minutes after the window closes).
const ping = () => fetch("/api/app/ping", { method: "POST", headers: { "X-RMT": "1" } }).catch(() => {});
ping();
setInterval(ping, 15000);
setTimeout(() => checkUpdate(true), 4000);  // just lights the ⚙ dot; never installs by itself
