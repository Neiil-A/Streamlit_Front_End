# © 2026 Neiil Apshankar. All rights reserved. Personal project — not an app, platform, or business. See NOTICE.md.
"""Sports: what happened, who stood out, what people said, what's next, and the standings.

Scores, records, top performers, scorers and standings come from ESPN's public scoreboard data (no key);
every game links to ESPN's own page, so each number can be checked there. "What people said" is quoted
word for word from the league's news (ESPN and the Guardian), with the link.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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
DAILY_WINDOW = (-2, 7)      # days around today for leagues that play most days: a week ahead
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


def _side(c: dict) -> Side:
    t = c.get("team") or {}
    return Side(t.get("displayName", ""), t.get("abbreviation", ""), c.get("score", ""),
                ((c.get("records") or [{}])[0]).get("summary", ""), t.get("logo", ""), bool(c.get("winner")))


def _link(e: dict) -> str:
    links = e.get("links") or []
    return next((l.get("href", "") for l in links if {"gamecast", "summary"} & set(l.get("rel") or [])),
                links[0].get("href", "") if links else "")


def _team_game(league: str, kind: str, e: dict) -> Game | None:
    comp = (e.get("competitions") or [{}])[0]
    sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    if "home" not in sides or "away" not in sides:
        return None
    status = (e.get("status") or {}).get("type") or {}
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
                periods=periods if all(periods) else ())


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
            status = (c.get("status") or {}).get("type") or {}
            sides = []
            for p in players:
                sets = " ".join(str(int(ls["value"])) for ls in p.get("linescores", []) if ls.get("value") is not None)
                sides.append(Side(_player(p), score=sets, winner=bool(p.get("winner"))))
            out.append(Game(league, status.get("state", ""), status.get("shortDetail", ""), _when(c.get("date", "")),
                            sides[0], sides[1], [], _link(e), f"{e.get('name', '')} · {label}"))
    return out


def scoreboard(league: str, today: datetime | None = None) -> list[Game]:
    path, kind, _, _ = LEAGUES[league]
    url = SCOREBOARD.format(path)
    events: list[dict] = []
    if kind == "tennis":
        for tour in ("tennis/atp", "tennis/wta"):
            events += requests.get(SCOREBOARD.format(tour), headers=UA, timeout=15).json().get("events", [])
        return [g for e in events for g in _tennis_games(league, e)]
    if league in WEEKLY:
        data = requests.get(url, headers=UA, timeout=15).json()           # the current week
        _remember_logo(league, data)
        events = data.get("events", [])
    else:
        today = today or datetime.now(timezone.utc)
        days = [(today + timedelta(days=d)).strftime("%Y%m%d") for d in range(DAILY_WINDOW[0], DAILY_WINDOW[1] + 1)]
        with ThreadPoolExecutor(6) as pool:
            for data in pool.map(lambda d: requests.get(url, params={"dates": d}, headers=UA, timeout=15).json(), days):
                _remember_logo(league, data)
                events += data.get("events", [])
    seen, games = set(), []
    for e in events:
        if e.get("id") in seen:
            continue
        seen.add(e.get("id"))
        g = _team_game(league, kind, e)
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


def standings(league: str, per_group: int = 10) -> dict[str, list[dict]]:
    """Each conference or league table, best first (none for tennis)."""
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
