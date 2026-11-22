# © 2026 Neiil Apshankar. All rights reserved. Personal project — not an app, platform, or business. See NOTICE.md.
"""Turns the raw feeds into an edition: one entry per story, checked against every outlet carrying it.

The same story from several outlets becomes one entry that keeps every outlet's link, so it can be
verified at each; its headline link goes to a free copy whenever one exists (never a paywall if it can
be helped), and the full text travels with it if any of them allows showing it. Being carried widely and
being high on an editor's front page is what puts a story on the front page. Celebrity news is capped
at three. Nothing is written or rewritten here: every headline and summary is the publisher's own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from press.feeds import PAYWALLED, SECTIONS, Story, gather

MAX_AGE = timedelta(hours=48)
SLOW_SECTIONS = {"Ideas": timedelta(days=14), "Entertainment": timedelta(days=7)}   # essays and reviews keep longer
PER_SOURCE = 4              # no single outlet fills a section while others have something
PER_SECTION = 14           # the briefing's top five, then more
SOCIAL_LIMIT = 3
STOP = set("a an the of to in on for and or but with at by from as is are was were be after over into amid says "
           "say new how why what who will can its it this that his her their our your us".split())
HARD_NEWS = {"World", "Politics", "Business & markets", "Technology", "Science & health"}
RUNNING_ORDER = {"NPR", "Al Jazeera", "DW", "PBS NewsHour", "The Guardian", "The New York Times"}


def is_live(s: Story) -> bool:
    t = s.title.lower()
    return "– live" in t or "- live" in t or ", live" in t or "live updates" in t or "as it happened" in t


def importance(s: Story) -> float:
    """Carried by several outlets counts most; then a high place in an editor's own running order."""
    place = max(0, 6 - s.rank) if (s.pick or s.source in RUNNING_ORDER) else 0
    return 3 * len(s.also) + place + (0.5 if s.image else 0) + (0.5 if s.body else 0) - (4 if is_live(s) else 0)


def varied(ranked: list[Story], limit: int, per_source: int = PER_SOURCE) -> list[Story]:
    """The best `limit` stories, at most `per_source` from any one outlet unless nothing else is left; best first."""
    picked, count = [], {}
    for s in ranked:
        if len(picked) < limit and count.get(s.source, 0) < per_source:
            picked.append(s)
            count[s.source] = count.get(s.source, 0) + 1
    chosen = {id(s) for s in picked}
    picked += [s for s in ranked if id(s) not in chosen][:limit - len(picked)]
    order = {id(s): i for i, s in enumerate(ranked)}
    return sorted(picked, key=lambda s: order[id(s)])


def outlets(s: Story) -> int:
    """How many separate outlets report it (the source, plus every twin)."""
    return 1 + len(s.also)


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", title.lower()) if w not in STOP and len(w) > 2}


def same_story(a: set[str], b: set[str]) -> bool:
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= 0.6 and len(a & b) >= 3


def merge(stories: list[Story]) -> list[Story]:
    """One entry per story. The kept copy is the free one with a picture and full text where possible; every
    outlet's link is kept for checking."""
    best_first = sorted(stories, key=lambda s: (s.source in PAYWALLED, not s.body, not s.pick, not s.image, s.source))
    kept: list[tuple[set[str], Story]] = []
    for s in best_first:
        w = _words(s.title)
        twin = next((k for k in kept if k[1].url == s.url or same_story(k[0], w)), None)
        if twin is None:
            s.links = [(s.source, s.url)]
            kept.append((w, s))
            continue
        main = twin[1]
        if s.source != main.source and s.source not in main.also:
            main.also.append(s.source)
            main.links.append((s.source, s.url))
            main.image = main.image or s.image
            main.pick = main.pick or s.pick
            main.rank = min(main.rank, s.rank)
    return [s for _, s in kept]


@dataclass
class Edition:
    made_at: datetime
    lead: Story | None
    front: list[Story]
    must_know: list[str]                 # Wikipedia's "In the news"
    sections: dict[str, list[Story]] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def build(now: datetime | None = None) -> Edition:
    now = now or datetime.now(timezone.utc)
    raw, itn, history = gather()
    fresh = [s for s in raw if not s.published or now - s.published <= SLOW_SECTIONS.get(s.section, MAX_AGE)]
    stories = merge(fresh)
    newest = lambda s: s.published or now - MAX_AGE
    weight = lambda s: (importance(s), newest(s))
    candidates = [s for s in stories if s.section in HARD_NEWS and (s.pick or s.also or (s.source in RUNNING_ORDER and s.rank < 5))]
    front = sorted(candidates, key=weight, reverse=True)[:7]
    lead = next((s for s in front if s.image and not is_live(s)), front[0] if front else None)
    shown = {id(s) for s in front}
    sections = {}
    for name in SECTIONS:
        mine = [s for s in stories if s.section == name and id(s) not in shown and not is_live(s)]
        limit = SOCIAL_LIMIT if name == "Social" else PER_SECTION
        sections[name] = varied(sorted(mine, key=weight, reverse=True), limit)
    return Edition(now, lead, [s for s in front if s is not lead], itn, sections, history,
                   sorted({s.source for s in raw}))
