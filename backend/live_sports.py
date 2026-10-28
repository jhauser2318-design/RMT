"""Live scores: games in progress refresh every 15 seconds and are pushed to the window.

While anyone has RMT open, leagues with a game in progress (or starting within
15 minutes) are checked every 15 seconds and every other league every 5
minutes. Only games whose score, clock or line changed are sent. Odds follow
the credit budget in odds.py, so live scores never cost odds credits.
"""
import asyncio
import logging
import time
from datetime import datetime

from . import odds, sports

log = logging.getLogger("rmt.live_sports")

LIVE_EVERY = 15      # seconds, leagues with games in progress
ALL_EVERY = 5 * 60   # seconds, every league (to notice games starting)
SOON = 15 * 60       # a game starting this soon counts as live


def _signature(g: dict) -> tuple:
    o = g.get("odds") or {}
    best = g.get("best") or {}
    return (g["state"], g["detail"], g["home"]["score"], g["away"]["score"], o.get("spread"), o.get("total"),
            o.get("home_ml"), o.get("away_ml"), g.get("odds_at"), str(best))


def _starts_soon(g: dict, now: float) -> bool:
    try:
        start = datetime.fromisoformat((g.get("start") or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    return g["state"] == "pre" and start - now < SOON


class ScoreWatcher:
    kind = "sports"

    def __init__(self, leagues=None):
        self.leagues = leagues or list(sports.LEAGUES)
        self.status = "off"
        self.source = "ESPN"
        self.error = ""
        self.since = 0.0
        self.live_games = 0
        self.live_leagues: set[str] = set()
        self._seen: dict[str, tuple] = {}
        self._listeners: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None

    def info(self) -> dict:
        return {"stream": self.kind, "status": self.status, "source": self.source, "error": self.error,
                "since": self.since, "live_games": self.live_games, "every": LIVE_EVERY, "odds": odds.budget()}

    def listen(self, q: asyncio.Queue | None = None) -> asyncio.Queue:
        q = q or asyncio.Queue(maxsize=100)
        self._listeners.add(q)
        return q

    def unlisten(self, q: asyncio.Queue) -> None:
        self._listeners.discard(q)

    def snapshot(self) -> list:
        return []  # the page loads games itself; only changes are pushed

    def _broadcast(self, event: dict) -> None:
        event = {**event, "stream": self.kind}
        for q in list(self._listeners):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def poll(self, leagues: list[str], ttl: float = 10) -> list[dict]:
        """One check of these leagues (runs in a worker thread). Returns the games that changed."""
        changed = []
        for lg in leagues:
            try:
                games = sports._league_games(lg, espn_ttl=ttl, odds_viewing=False)
            except Exception as e:  # noqa: BLE001 (one league failing shouldn't stop the rest)
                log.info("Live scores for %s failed: %s", lg, e)
                continue
            now = time.time()
            live_here = [g for g in games if g["state"] == "in" or _starts_soon(g, now)]
            if live_here:
                self.live_leagues.add(lg)
            else:
                self.live_leagues.discard(lg)
            for g in games:
                sig = _signature(g)
                if self._seen.get(g["id"]) != sig:
                    if g["id"] in self._seen:  # first sighting isn't a change; the page already has it
                        changed.append(g)
                    self._seen[g["id"]] = sig
        return changed

    async def _run(self) -> None:
        next_all = 0.0
        while True:
            if not self._listeners:  # nobody's looking: don't use ESPN
                if self.status != "off":
                    self.status = "off"
                await asyncio.sleep(3)
                continue
            now = time.time()
            leagues = self.leagues if now >= next_all else sorted(self.live_leagues)
            if now >= next_all:
                next_all = now + ALL_EVERY
            try:
                changed = await asyncio.to_thread(self.poll, leagues)
                self.live_games = sum(1 for sig in self._seen.values() if sig[0] == "in")
                if self.status != "live":
                    self.status, self.since, self.error = "live", time.time(), ""
                    self._broadcast({"type": "status", **self.info()})
                if changed:
                    self._broadcast({"type": "games", "items": sports.sort_games(changed)})
            except Exception as e:  # noqa: BLE001
                self.status, self.error = "offline", str(e)
                self._broadcast({"type": "status", **self.info()})
            await asyncio.sleep(LIVE_EVERY)


scores = ScoreWatcher()
