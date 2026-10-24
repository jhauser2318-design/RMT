// RMT front end: stock ribbons, news, trading talk, YouTube, games & odds,
// stats and the "Ask RMT" chat. Talks only to the RMT server (/api/...).

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(`rmt.${k}`)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(`rmt.${k}`, JSON.stringify(v)); } catch { /* private mode */ } },
};

async function api(path, body) {
  const res = await fetch(`/api${path}`, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : {});
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
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
function ribbonHTML(label, inner, count) {
  return `<div class="ribbon"><div class="ribbon-label">${esc(label)}</div>
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
    const tick = (q) => `<span class="tick-sym">${esc(q.label)}</span>
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
      <span class="tick" data-sym="${esc(q.symbol)}" title="${esc(q.name)}: click for news &amp; videos">${tick(q)}</span>`).join(""), r.items.length)).join("");
  } catch (e) {
    $("#ribbons").innerHTML = `<div class="empty">Couldn't load prices: ${esc(e.message)}</div>`;
  }
}

function renderWatch() {
  $("#watch-chips").innerHTML = watch.map((s) => `<button class="chip" data-unwatch="${esc(s)}">${esc(s)}<span class="x">✕</span></button>`).join("");
}

async function loadNews() {
  const list = $("#news");
  list.innerHTML = `<li class="empty">Loading headlines…</li>`;
  $("#news-filter").hidden = !tickerFilter;
  $("#news-filter").innerHTML = `News for <b>${esc(tickerFilter)}</b> <button data-clear="news">✕ show all</button>`;
  try {
    const data = await api(`/markets/news?q=${encodeURIComponent(tickerFilter)}`);
    list.innerHTML = data.items.map((i) => `<li>
      <a class="title" href="${esc(i.link)}" target="_blank" rel="noopener">${esc(i.title)}</a>
      ${i.summary ? `<div class="summary">${esc(i.summary)}</div>` : ""}
      <div class="meta"><span class="src">${esc(i.source)}</span><span>${timeAgo(i.time)}</span></div>
    </li>`).join("") || `<li class="empty">No headlines found.</li>`;
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

async function loadVideos(q = tickerFilter) {
  const box = $("#videos");
  box.innerHTML = `<div class="empty">Loading videos…</div>`;
  $("#yt-filter").hidden = !q;
  $("#yt-filter").innerHTML = `Videos for <b>${esc(q)}</b> <button data-clear="yt">✕ show latest</button>
    · <a href="https://www.youtube.com/results?search_query=${encodeURIComponent(`${q} stock`)}" target="_blank" rel="noopener">search on YouTube ↗</a>`;
  try {
    const data = await api(`/markets/videos?q=${encodeURIComponent(q)}`);
    box.innerHTML = data.items.map((v) => `<a class="video" href="${esc(v.link)}" target="_blank" rel="noopener">
      <div class="thumb" style="${v.image ? `background-image:url('${esc(v.image)}')` : ""}">${v.image ? "" : "▶"}</div>
      <div class="vt">${esc(v.title)}</div>
      <div class="vm">${esc(v.source)}${v.time ? ` · ${timeAgo(v.time)}` : ""}</div></a>`).join("")
      || `<div class="empty">No matching videos from the followed channels.${data.searchable ? "" : " Add a YOUTUBE_API_KEY to search all of YouTube."}</div>`;
  } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

function filterTicker(sym) {
  tickerFilter = sym;
  $("#news-q").value = sym;
  $("#yt-q").value = sym;
  loadNews();
  loadVideos();
  $("#news").scrollIntoView({ behavior: "smooth", block: "nearest" });
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
      ${!spread && total == null && awayMl == null ? `<span class="pill">No line posted yet</span>` : ""}
    </div>
    <div class="game-actions">
      ${g.books?.length ? `<button class="btn" data-books="${esc(g.id)}">${openBooks.has(g.id) ? "Hide" : "Compare"} ${g.books.length} books</button>` : ""}
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

function renderGames() {
  const games = visibleGames();
  let html = games.map(gameCard).join("");
  if (league === "all") {  // group by league, keeping live-first order inside each
    const byLeague = {};
    games.forEach((g) => { (byLeague[g.league] ||= []).push(g); });
    html = Object.values(byLeague).map((lst) => `<h3 class="league-head">${lst[0].emoji} ${esc(lst[0].league_name)}</h3>${lst.map(gameCard).join("")}`).join("");
  }
  $("#games").innerHTML = html || `<div class="empty">No games match. Try another league or date.</div>`;
  const note = $("#games-note");
  note.hidden = gamesData.multi_book || !gamesData.games.length;
  note.textContent = "Showing one sportsbook's line per game. Add a free ODDS_API_KEY in .env to compare DraftKings, FanDuel, BetMGM and more side by side.";

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

/* ============================ WIRING ============================ */

function showMode() {
  const mode = location.hash === "#sports" ? "sports" : "markets";
  $$(".mode").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $("#markets").hidden = mode !== "markets";
  $("#sports").hidden = mode !== "sports";
  if (mode === "markets") showMarkets(); else showSports();
  if (!$("#chat").hidden) renderChat();
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-mode],[data-sym],[data-unwatch],[data-clear],[data-league],[data-books],[data-ask-game],[data-jump],[data-suggest]");
  if (!t) return;
  const d = t.dataset;
  if (d.mode) location.hash = d.mode;
  else if (d.sym) filterTicker(d.sym);
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
  if (!$("#settings").hidden) { showVersion(); checkUpdate(); }
});
$("#update-check").addEventListener("click", () => checkUpdate());
document.addEventListener("click", (e) => {
  if (e.target.id === "update-now") installUpdate();
  else if (!$("#settings").hidden && !e.target.closest("#settings, #settings-open")) $("#settings").hidden = true;
});

// Tell the server this window is still open (it stops itself a few minutes after the window closes).
const ping = () => fetch("/api/app/ping", { method: "POST" }).catch(() => {});
ping();
setInterval(ping, 15000);
setTimeout(() => checkUpdate(true), 4000);  // just lights the ⚙ dot; never installs by itself
