# © 2026 Neiil Apshankar. All rights reserved. Personal project — not an app, platform, or business. See NOTICE.md.
"""Sports: what happened, who stood out, what people said, what's next, and the standings.

Scores, records, top performers, scorers and standings come from ESPN's public scoreboard data (no key);
every game links to ESPN's own page, so each number can be checked there. "What people said" is quoted
word for word from the league's news (ESPN and the Guardian), with the link.

Scores are live: Scores keeps every league's games for everyone reading, by the rules in fresh_until. While a
game is on, its day's scoreboard is read again every LIVE_TTL seconds; with nothing on, every SLOW_TTL or when
the next game is due to start, whichever comes first. The page refreshes itself (refresh_every) to match.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from press.feeds import UA, Story, _get, _key, _when, parse_feed

LEAGUES = {
    # name: (ESPN path, kind, ESPN news feed, Guardian tag for league news and quotes)
    "NBA": ("basketball/nba", "us", "https://www.espn.com/espn/rss/nba/news", "sport/nba"),
    "NFL": ("football/nfl", "us", "https://www.espn.com/espn/rss/nfl/news", "sport/nfl"),
    "College football": ("football/college-football", "us", "https://www.espn.com/espn/rss/ncf/news",
                         "sport/college-football"),
    "NHL": ("hockey/nhl", "us", "https://www.espn.com/espn/rss/nhl/news", "sport/nhl"),
    "Premier League": ("soccer/eng.1", "soccer", "https://www.espn.com/espn/rss/soccer/news", "football/premierleague"),
    "LaLiga": ("soccer/esp.1", "soccer", "https://www.espn.com/espn/rss/soccer/news", "football/laligafootball"),
    "Champions League": ("soccer/uefa.champions", "soccer", "https://www.espn.com/espn/rss/soccer/news",
                         "football/championsleague"),
    "MLS": ("soccer/usa.1", "soccer", "https://www.espn.com/espn/rss/soccer/news", "football/mls"),
    "Tennis": ("tennis/atp", "tennis", "https://www.espn.com/espn/rss/tennis/news", "sport/tennis"),
}
WEEKLY = {"NFL", "College football"}          # ESPN's default scoreboard is the current week
NO_TABLES = {"College football", "Tennis"}    # dozens of conference tables / no league table
LOGOS: dict[str, str] = {}                    # league logo from ESPN, filled in as scoreboards load
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/{}/scoreboard"
STANDINGS = "https://site.api.espn.com/apis/v2/sports/{}/standings"
DAILY_WINDOW = (-2, 7)      # days around today (Eastern, ESPN's scoreboard dates) for leagues that play most days
ET = ZoneInfo("America/New_York")
LIVE_TTL = 25               # seconds: a scoreboard with a game on is read again this often (only the days with one on)
SLOW_TTL = 10 * 60          # seconds: with nothing on, this often at most, and as soon as the next game is due
LATE_START = 3 * 3600       # a game still not started this long after its start time no longer counts as due
PAGE_LIVE = 30              # seconds between the page's own score refreshes while a game is on or about to start
PAGE_CALM = 5 * 60          # ... and while nothing is (served from the cache, so no extra reads of ESPN)
CALLED_OFF = {"STATUS_POSTPONED": "Postponed", "STATUS_CANCELED": "Canceled", "STATUS_SUSPENDED": "Suspended",
              "STATUS_ABANDONED": "Abandoned", "STATUS_FORFEIT": "Forfeit"}
LEADER_UNITS = {"points": "pts", "rebounds": "reb", "assists": "ast"}
GOALS = ("Goal", "Penalty - Scored", "Own Goal", "Goal - Header", "Goal - Free-kick")


@dataclass
class Side:
    name: str
    abbr: str = ""
    score: str = ""
    record: str = ""
    logo: str = ""
    winner: bool = False


@dataclass
class Game:
    league: str
    state: str                  # "pre", "in" or "post"
    status: str                 # "Final", "8:19 - 4th", "Sun 1:00 PM"
    start: datetime | None
    away: Side
    home: Side
    standouts: list[str] = field(default_factory=list)   # top performers, scorers
    link: str = ""
    event: str = ""             # tournament and round, for tennis
    faces: list[str] = field(default_factory=list)       # headshots of the top performers, where ESPN has them
    recap_title: str = ""       # ESPN's recap of a finished game: headline and first lines
    recap: str = ""
    venue: str = ""
    periods: tuple = ()          # (away, home) scores by quarter, period or half
    id: str = ""
    day: str = ""               # the scoreboard date (YYYYMMDD, Eastern) ESPN lists it under; "" on week-long boards
    clock: str = ""             # game clock while it's on: "8:20", "67'"
    period: int = 0             # quarter, period, half or set number
    status_name: str = ""       # ESPN's status: STATUS_IN_PROGRESS, STATUS_HALFTIME, STATUS_FINAL, STATUS_POSTPONED...
    tbd: bool = False           # start time not set yet


def _side(c: dict) -> Side:
    t = c.get("team") or {}
    return Side(t.get("displayName", ""), t.get("abbreviation", ""), c.get("score", ""),
                ((c.get("records") or [{}])[0]).get("summary", ""), t.get("logo", ""), bool(c.get("winner")))


def _link(e: dict) -> str:
    links = e.get("links") or []
    return next((l.get("href", "") for l in links if {"gamecast", "summary"} & set(l.get("rel") or [])),
                links[0].get("href", "") if links else "")


def _clock(raw: dict) -> dict:
    """The live fields of an ESPN status: clock, period, status name."""
    return {"clock": str(raw.get("displayClock") or ""), "period": int(raw.get("period") or 0),
            "status_name": ((raw.get("type") or {}).get("name") or "")}


def _team_game(league: str, kind: str, e: dict, day: str = "") -> Game | None:
    comp = (e.get("competitions") or [{}])[0]
    sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    if "home" not in sides or "away" not in sides:
        return None
    raw = e.get("status") or comp.get("status") or {}
    status = raw.get("type") or {}
    state = status.get("state", "")
    standouts, faces = [], []
    if kind == "soccer":
        for d in comp.get("details", []):
            if (d.get("type") or {}).get("text") in GOALS:
                who = ", ".join(a.get("displayName", "") for a in d.get("athletesInvolved", []))
                own = " (own goal)" if "Own" in d["type"]["text"] else ""
                standouts.append(f"{who}{own} {d.get('clock', {}).get('displayValue', '')}".strip())
    elif state != "pre":   # before a game ESPN lists season leaders, not this game's
        for group in comp.get("leaders", []):                      # NFL: the game's passing, rushing, receiving
            top = (group.get("leaders") or [{}])[0]
            if (top.get("athlete") or {}).get("displayName"):
                standouts.append(f"{top['athlete']['displayName']}: {top.get('displayValue', '')}")
                faces.append(_headshot(top["athlete"]))
        for c in (sides["away"], sides["home"]):                   # NBA, NHL: each team's best all-round line
            groups = c.get("leaders") or []
            group = next((g for g in groups if g.get("name") == "rating"), None) or \
                next((g for g in groups if g.get("name") == "points"), None) or (groups[0] if groups else None)
            top = ((group or {}).get("leaders") or [{}])[0]
            if (top.get("athlete") or {}).get("displayName"):
                unit = "" if group.get("name") == "rating" else LEADER_UNITS.get(group.get("name", ""), group.get("name", ""))
                standouts.append(f"{top['athlete']['displayName']} ({c['team'].get('abbreviation', '')}) "
                                 f"{top.get('displayValue', '')} {unit}".strip())
                faces.append(_headshot(top["athlete"]))
    recap = next((h for h in comp.get("headlines") or [] if h.get("type") == "Recap"), None) or \
        ((comp.get("headlines") or [{}])[0] if state == "post" else {})
    periods = tuple([str(l.get("displayValue", l.get("value", ""))) for l in sides[k].get("linescores") or []]
                    for k in ("away", "home"))
    return Game(league, state, status.get("shortDetail", ""), _when(e.get("date", "")), _side(sides["away"]),
                _side(sides["home"]), standouts[:6], _link(e), faces=faces[:6],
                recap_title=(recap or {}).get("shortLinkText", ""),
                recap=re.sub(r"^[—–-]\s*", "", (recap or {}).get("description", "") or "").strip(),
                venue=((comp.get("venue") or {}).get("fullName") or ""),
                periods=periods if all(periods) else (), id=str(e.get("id", "")), day=day,
                tbd=comp.get("timeValid") is False, **_clock(raw))


def _headshot(athlete: dict) -> str:
    h = athlete.get("headshot")
    h = h.get("href", "") if isinstance(h, dict) else h or ""
    return h if str(h).startswith("https://") else ""


def _player(c: dict) -> str:
    if (c.get("athlete") or {}).get("displayName"):
        return c["athlete"]["displayName"]
    roster = (c.get("roster") or {}).get("athletes") or c.get("athletes") or []
    names = [a.get("displayName") or (a.get("athlete") or {}).get("displayName", "") for a in roster]
    return " / ".join(n for n in names if n) or (c.get("team") or {}).get("displayName", "")


def _tennis_games(league: str, e: dict) -> list[Game]:
    out = []
    for group in e.get("groupings") or []:
        label = (group.get("grouping") or {}).get("displayName", "")
        if "Doubles" in label:
            continue
        for c in group.get("competitions") or []:
            players = c.get("competitors") or []
            if len(players) != 2:
                continue
            raw = c.get("status") or {}
            status = raw.get("type") or {}
            sides = []
            for p in players:
                sets = " ".join(str(int(ls["value"])) for ls in p.get("linescores", []) if ls.get("value") is not None)
                sides.append(Side(_player(p), score=sets, winner=bool(p.get("winner"))))
            out.append(Game(league, status.get("state", ""), status.get("shortDetail", ""), _when(c.get("date", "")),
                            sides[0], sides[1], [], _link(e), f"{e.get('name', '')} · {label}",
                            id=str(c.get("id", "")), **_clock(raw)))
    return out


def scoreboard(league: str, today: datetime | None = None, days: list[str] | None = None) -> list[Game]:
    """The league's games: the current week, or for leagues that play most days DAILY_WINDOW around today.
    With `days` (YYYYMMDD), only those dates: a live update."""
    path, kind, _, _ = LEAGUES[league]
    url = SCOREBOARD.format(path)
    events: list[tuple[str, dict]] = []
    if kind == "tennis":
        for tour in ("tennis/atp", "tennis/wta"):
            events += [("", e) for e in requests.get(SCOREBOARD.format(tour), headers=UA, timeout=15).json().get("events", [])]
        return [g for _, e in events for g in _tennis_games(league, e)]
    if league in WEEKLY:
        data = requests.get(url, headers=UA, timeout=15).json()           # the current week
        _remember_logo(league, data)
        events = [("", e) for e in data.get("events", [])]
    else:
        if days is None:
            today = (today or datetime.now(ET)).astimezone(ET)
            days = [(today + timedelta(days=d)).strftime("%Y%m%d") for d in range(DAILY_WINDOW[0], DAILY_WINDOW[1] + 1)]
        if not days:
            return []
        with ThreadPoolExecutor(min(6, len(days))) as pool:
            for day, data in zip(days, pool.map(
                    lambda d: requests.get(url, params={"dates": d}, headers=UA, timeout=15).json(), days)):
                _remember_logo(league, data)
                events += [(day, e) for e in data.get("events", [])]
    seen, games = set(), []
    for day, e in events:
        if e.get("id") in seen:
            continue
        seen.add(e.get("id"))
        g = _team_game(league, kind, e, day)
        if g:
            games.append(g)
    return games


def _remember_logo(league: str, data: dict) -> None:
    logos = ((data.get("leagues") or [{}])[0]).get("logos") or []
    if logos and str(logos[0].get("href", "")).startswith("https://"):
        LOGOS.setdefault(league, logos[0]["href"])


def split(games: list[Game], n: int = 10, ahead: int | None = None) -> tuple[list[Game], list[Game], list[Game]]:
    """(live now, results newest first, coming up soonest first): n results, `ahead` upcoming games (default n)."""
    far = datetime.max.replace(tzinfo=timezone.utc)
    live = [g for g in games if g.state == "in"]
    done = sorted((g for g in games if g.state == "post"), key=lambda g: g.start or far, reverse=True)[:n]
    next_ = sorted((g for g in games if g.state == "pre"), key=lambda g: g.start or far)[:ahead or n]
    return live, done, next_


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def period_name(g: Game) -> str:
    """Where a game is: '4th quarter', '2nd period', '2nd half', 'Set 3', 'Overtime', 'Shootout'."""
    sport, p = LEAGUES[g.league][0].split("/")[0], g.period
    if p <= 0:
        return ""
    if sport == "soccer":
        return {1: "1st half", 2: "2nd half", 3: "Extra time", 4: "Extra time", 5: "Penalties"}.get(p, "")
    if sport == "tennis":
        return f"Set {p}"
    regular = 3 if sport == "hockey" else 4
    if p <= regular:
        return f"{_ordinal(p)} {'period' if sport == 'hockey' else 'quarter'}"
    if sport == "hockey" and re.search(r"\bSO\b", g.status.upper()):
        return "Shootout"
    return "Overtime" if p == regular + 1 else f"{_ordinal(p - regular)} overtime"


def live_detail(g: Game) -> str:
    """A game in progress, in words: '4th quarter · 8:20', 'Halftime', 'End of 2nd period', "1st half · 33'"."""
    period = period_name(g)
    if g.status_name == "STATUS_HALFTIME":
        return "Halftime"
    if g.status_name == "STATUS_END_PERIOD" and period:
        return "End of " + (period if period[0].isdigit() else period.lower())
    if "DELAY" in g.status_name:
        return g.status or "Delayed"
    if period and g.clock and g.clock not in ("0:00", "0.0", "0") and not period.startswith("Set"):
        return f"{period} · {g.clock}"
    return period or g.status


def final_detail(g: Game) -> str:
    """How a finished game ended, when it wasn't in regular time: 'overtime', 'shootout', 'on penalties'."""
    s = f"{g.status} {g.status_name}".upper()
    if "PEN" in s:
        return "on penalties"
    if "AET" in s:
        return "after extra time"
    if re.search(r"\bSO\b", s):
        return "shootout"
    if (m := re.search(r"(\d*)OT\b", s)):
        return "overtime" if m.group(1) in ("", "1") else f"{_ordinal(int(m.group(1)))} overtime"
    return ""


def _due(g: Game, now: datetime) -> float | None:
    """Seconds until a game that hasn't started is due (negative once its start time has passed), or None when it
    doesn't count: started, finished, no time set yet, or still not started LATE_START after its start time."""
    if g.state != "pre" or g.tbd or not g.start:
        return None
    wait = (g.start - now).total_seconds()
    return wait if wait > -LATE_START else None


def fresh_until(games: list[Game], fetched: datetime) -> datetime:
    """How long scores read at `fetched` may be served: LIVE_TTL while a game is on or should have started by now,
    else SLOW_TTL or until the next game is due to start, whichever comes first. So a game in progress is never
    served from the slow cache."""
    if any(g.state == "in" for g in games):
        return fetched + timedelta(seconds=LIVE_TTL)
    due = [w for g in games if (w := _due(g, fetched)) is not None]
    wait = min(SLOW_TTL, max(LIVE_TTL, min(due))) if due else SLOW_TTL
    return fetched + timedelta(seconds=wait)


def refresh_every(games: list[Game], now: datetime) -> int:
    """Seconds between the page's own refreshes: PAGE_LIVE while a game is on or due within PAGE_CALM, else
    PAGE_CALM (those refreshes are served from the cache)."""
    on = any(g.state == "in" for g in games) or \
        any((w := _due(g, now)) is not None and w <= PAGE_CALM for g in games)
    return PAGE_LIVE if on else PAGE_CALM


def hot_days(games: list[Game], now: datetime) -> set[str] | None:
    """The scoreboard dates to read again for a live update: those with a game on or due to start. None: read the
    whole scoreboard again (a week-long board, or nothing on)."""
    hot = [g for g in games if g.state == "in" or ((w := _due(g, now)) is not None and w <= LIVE_TTL)]
    if not hot or any(not g.day for g in hot):
        return None
    return {g.day for g in hot}


@dataclass
class Board:
    games: list[Game] = field(default_factory=list)
    fetched: datetime | None = None     # when these scores were read from ESPN
    full: datetime | None = None        # when the whole window was last read
    retry: datetime | None = None       # after a failed read: not again before this


class Scores:
    """Every league's games, one copy for everyone reading the paper, kept by fresh_until's rules. The whole window
    is read every SLOW_TTL; in between, only the days with a game on or due to start. A failed read keeps the last
    scores (with the time they were read) and tries again after LIVE_TTL."""

    def __init__(self, fetch=None, clock=None):
        self._fetch = fetch or scoreboard
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._boards: dict[str, Board] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, league: str) -> Board:
        with self._guard:
            lock = self._locks.setdefault(league, threading.Lock())
        with lock:                       # one read per league at a time, however many people are reading
            now = self._clock()
            old = self._boards.get(league) or Board()
            if old.retry and now < old.retry:
                return old
            try:
                if old.full is None or (now - old.full).total_seconds() >= SLOW_TTL:
                    new = Board(self._fetch(league), now, now)
                elif now < fresh_until(old.games, old.fetched):
                    return old
                elif (days := hot_days(old.games, now)) is None:
                    new = Board(self._fetch(league), now, now)
                else:
                    update = self._fetch(league, days=sorted(days))
                    ids = {g.id for g in update}
                    kept = [g for g in old.games if g.day not in days and g.id not in ids]
                    new = Board(kept + update, now, old.full)
            except Exception:
                new = replace(old, retry=now + timedelta(seconds=LIVE_TTL))
            self._boards[league] = new
            return new


def standings(league: str, per_group: int | None = None) -> dict[str, list[dict]]:
    """Each conference or league table, best first, every team unless per_group says otherwise (none for tennis)."""
    path, kind, _, _ = LEAGUES[league]
    if league in NO_TABLES:
        return {}
    data = requests.get(STANDINGS.format(path), headers=UA, timeout=15).json()
    groups = data.get("children") or [data]
    out = {}
    for conf in groups:
        entries = list((conf.get("standings") or {}).get("entries", []))
        for division in conf.get("children", []):
            entries += (division.get("standings") or {}).get("entries", [])
        rows = []
        for e in entries:
            st = {s.get("name"): s for s in e.get("stats", [])}
            val = lambda k: st.get(k, {}).get("displayValue", "")
            num = lambda k: float(st.get(k, {}).get("value") or 0)
            if kind == "soccer":
                rows.append({"Team": e["team"].get("displayName", ""), "P": val("gamesPlayed"), "W": val("wins"),
                             "D": val("ties"), "L": val("losses"), "GD": val("pointDifferential"), "Pts": val("points"),
                             "_sort": (num("points"), num("pointDifferential"))})
            elif league == "NHL":
                rows.append({"Team": e["team"].get("displayName", ""), "GP": val("gamesPlayed"), "W": val("wins"),
                             "L": val("losses"), "OTL": val("otLosses"), "PTS": val("points"),
                             "_sort": (num("points"), num("wins"))})
            else:
                row = {"Team": e["team"].get("displayName", ""), "W": val("wins"), "L": val("losses")}
                if league == "NFL":
                    row["T"] = val("ties")
                row.update({"PCT": val("winPercent"), "GB": val("gamesBehind")} if league == "NBA" else {"PCT": val("winPercent")})
                row["_sort"] = (num("winPercent"), num("wins"))
                rows.append(row)
        rows.sort(key=lambda r: r.pop("_sort"), reverse=True)
        if rows:
            out[conf.get("name", league)] = rows[:per_group]
    return out


_QUOTE = re.compile(r"[“\"‘]([^”\"’]{40,240})[”\"’]")
_NAME = r"((?:[A-Z][\w'’.-]+)(?:\s+(?:[A-Z][\w'’.-]+|de|van|von|da|di|del|la|le)){0,3})"
_VERB = r"(?:said|says|told [^.,;]{1,40}?|added|explained|insisted|admitted|wrote|posted)"
_AFTER = [re.compile(r"^[,.]?\s*" + _VERB + r"\s+" + _NAME), re.compile(r"^[,.]?\s*" + _NAME + r"\s+" + _VERB + r"\b")]
_BEFORE = re.compile(_NAME + r",?\s+(?:" + _VERB + r")(?:\s+[^:“\"]{0,40})?:\s*$")
_NOT_NAMES = {"The", "He", "She", "They", "It", "This", "That", "But", "And", "When", "After", "His", "Her", "We", "I"}


def _speaker(text: str, start: int, end: int) -> str:
    """Who said the quote between start and end, when the text names them right beside it."""
    after = text[end:end + 90]
    for pat in _AFTER:
        if (m := pat.search(after)):
            return m.group(1)
    if (m := _BEFORE.search(text[max(0, start - 90):start])):
        return m.group(1)
    return ""


def quotes(stories: list[Story], n: int = 4) -> list[tuple[str, str, Story]]:
    """Things people said, word for word: (quote, who said it, the story it came from). Only quotes whose
    speaker is named next to them, so every one says who is talking."""
    out, seen = [], set()
    for s in stories:
        for text in (s.summary, s.body[:6000]):
            found = None
            for m in _QUOTE.finditer(text or ""):
                q = m.group(1).strip().rstrip(",")
                who = _speaker(text, m.start(), m.end()).strip(" ,.")
                if q.lower() in seen or len(q.split()) < 7 or not who or who.split()[0] in _NOT_NAMES:
                    continue
                found = (q, who, s)
                break
            if found:
                seen.add(found[0].lower())
                out.append(found)
                break
        if len(out) >= n:
            break
    return out


def news(league: str, n: int = 8) -> list[Story]:
    """The league's headlines: ESPN's, plus the Guardian's (with full text) for soccer and tennis."""
    path, kind, feed, guardian = LEAGUES[league]
    espn: list[Story] = []
    stories: list[Story] = []
    try:
        espn = parse_feed(_get(feed).text, "ESPN", "Sports", True, limit=n)
    except Exception:
        pass
    key = _key("GUARDIAN_API_KEY")
    if guardian and not key:      # the Guardian's free feed for the league (no key, no full text)
        try:
            stories += parse_feed(_get(f"https://www.theguardian.com/{guardian}/rss").text, "The Guardian", "Sports", True,
                                  limit=n)
        except Exception:
            pass
    if guardian and key:
        from press.feeds import GUARDIAN, _guardian_story

        try:
            body = _get(f"{GUARDIAN}/search", tag=guardian if "/" in guardian else None, section=None if "/" in guardian else guardian,
                        **{"page-size": n, "order-by": "newest", "show-fields": "trailText,thumbnail,bodyText,byline",
                           "api-key": key}).json()["response"]
            stories += [s for r in body.get("results", []) if (s := _guardian_story(r, "Sports"))]
        except Exception:
            pass
    # ESPN's soccer feed covers every league, so for soccer the Guardian's league-specific stories come first
    return stories + espn if kind == "soccer" else espn + stories
