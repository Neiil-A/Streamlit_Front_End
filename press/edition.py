# © 2026 Neiil Apshankar. All rights reserved. Personal project — not an app, platform, or business. See NOTICE.md.
"""Turns the raw feeds into an edition: one copy of each story, the best stories first, in sections.

The same story from several outlets becomes one entry ("also in BBC, NPR"); being carried widely
and being on an editor's front page is what puts a story on the front page. Nothing is written or
rewritten here: every headline and summary is the publisher's own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from press.feeds import SECTIONS, Story, gather

MAX_AGE = timedelta(hours=48)
STOP = set("a an the of to in on for and or but with at by from as is are was were be after over into amid says "
           "say new how why what who will can its it this that his her their our your us".split())


# The front page is for the news that matters; sports, culture and gossip have their own pages.
HARD_NEWS = {"Government & politics", "World", "Science & health", "Technology", "Business & markets"}


# Outlets whose feeds list stories in their editors' order of importance.
RUNNING_ORDER = {"BBC", "NPR", "The Guardian", "The New York Times"}


def importance(s: Story) -> float:
    """Carried by several outlets counts most; then a high place in an editor's own running order."""
    place = max(0, 6 - s.rank) if (s.pick or s.source in RUNNING_ORDER) else 0
    return 3 * len(s.also) + place + (0.5 if s.image else 0) - (4 if is_live(s) else 0)


def is_live(s: Story) -> bool:
    t = s.title.lower()
    return "– live" in t or "- live" in t or "live updates" in t or "as it happened" in t


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", title.lower()) if w not in STOP and len(w) > 2}


def same_story(a: set[str], b: set[str]) -> bool:
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= 0.6 and len(a & b) >= 3


def merge(stories: list[Story]) -> list[Story]:
    """One entry per story; the copy with a picture and an editor's pick is kept, the others listed in `also`."""
    kept: list[tuple[set[str], Story]] = []
    for s in sorted(stories, key=lambda s: (not s.pick, not s.image, s.source)):
        w = _words(s.title)
        twin = next((k for k in kept if k[1].url == s.url or same_story(k[0], w)), None)
        if twin is None:
            kept.append((w, s))
        elif s.source != twin[1].source and s.source not in twin[1].also:
            twin[1].also.append(s.source)
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


def build(per_section: int = 9, now: datetime | None = None) -> Edition:
    now = now or datetime.now(timezone.utc)
    raw, itn, history = gather()
    fresh = [s for s in raw if not s.published or now - s.published <= MAX_AGE or s.section == "Ideas & long reads"]
    stories = merge(fresh)
    newest = lambda s: s.published or now - MAX_AGE
    weight = lambda s: (importance(s), newest(s))
    candidates = [s for s in stories if s.section in HARD_NEWS and (s.pick or s.also or (s.source in RUNNING_ORDER and s.rank < 5))]
    front = sorted(candidates, key=weight, reverse=True)[:7]
    lead = next((s for s in front if s.image and not is_live(s)), front[0] if front else None)
    shown = {id(s) for s in front}
    sections = {}
    for name in SECTIONS[1:]:
        mine = [s for s in stories if s.section == name and id(s) not in shown]
        sections[name] = sorted(mine, key=weight, reverse=True)[:per_section]
    return Edition(now, lead, [s for s in front if s is not lead], itn, sections, history,
                   sorted({s.source for s in raw}))
