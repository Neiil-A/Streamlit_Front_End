# © 2026 Neiil Apshankar. All rights reserved. Personal project — not an app, platform, or business. See NOTICE.md.
"""Where Stop Looking at my Computer News gets its stories: free, public feeds only.

The Guardian (open API, free developer key: GUARDIAN_API_KEY), The New York Times' Top Stories
(free key: NYT_API_KEY; skipped without one), Wikipedia's "In the news" and "On this day",
and public RSS feeds (BBC, NPR, ESPN, Quanta, Aeon, The Conversation, Page Six, E! News).

Only headlines, short summaries, pictures and links are shown; the full article is one click
away at the publisher (free everywhere except the Times, which allows a few articles a month).
"""

from __future__ import annotations

import html
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

import requests

UA = {"User-Agent": "PurifiedPress/0.1 (personal news reader; non-commercial)"}
TIMEOUT = 15


@dataclass
class Story:
    title: str
    url: str
    source: str
    section: str                 # one of SECTIONS
    summary: str = ""
    published: datetime | None = None
    image: str = ""
    pick: bool = False           # an editor put it on their front page
    also: list[str] = field(default_factory=list)   # other outlets carrying the same story
    rank: int = 99               # its place in the outlet's own running order (0 = top story), when it has one


SECTIONS = ("Front page", "Government & politics", "World", "Ideas & long reads", "Science & health",
            "Technology", "Business & markets", "Sports", "Culture & gossip")


def _key(name: str) -> str:
    """The environment (.env, when PHANTOM runs it) first, then Streamlit's secrets (when hosted)."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st

        return str(st.secrets.get(name, ""))
    except Exception:
        return ""


def _clean(text: str, limit: int = 320) -> str:
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _when(text: str) -> datetime | None:
    if not text:
        return None
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            when = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _get(url: str, **params) -> requests.Response:
    resp = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


# ---- RSS and Atom ------------------------------------------------------------------------

RSS = (
    # (source, section, url)
    ("BBC", "World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("NPR", "World", "https://feeds.npr.org/1004/rss.xml"),
    ("NPR", "Government & politics", "https://feeds.npr.org/1014/rss.xml"),
    ("NPR", "Science & health", "https://feeds.npr.org/1007/rss.xml"),
    ("NPR", "Science & health", "https://feeds.npr.org/1128/rss.xml"),
    ("Quanta", "Ideas & long reads", "https://www.quantamagazine.org/feed/"),
    ("Aeon", "Ideas & long reads", "https://aeon.co/feed.rss"),
    ("The Conversation", "Ideas & long reads", "https://theconversation.com/us/articles.atom"),
    ("BBC Sport", "Sports", "https://feeds.bbci.co.uk/sport/rss.xml"),
    ("ESPN", "Sports", "https://www.espn.com/espn/rss/news"),
    ("Page Six", "Culture & gossip", "https://pagesix.com/feed/"),
    ("E! News", "Culture & gossip", "https://www.eonline.com/syndication/feeds/rssfeeds/topstories.xml"),
)
_NS = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/"}


def parse_feed(xml_text: str, source: str, section: str, limit: int = 12) -> list[Story]:
    root = ET.fromstring(xml_text)
    out = []
    for i, item in enumerate(root.iter("item")):
        thumb = item.find("media:thumbnail", _NS)   # (an element with no children is falsy: compare with None)
        if thumb is None:
            thumb = item.find("media:content", _NS)
        enclosure = item.find("enclosure")
        image = (thumb.get("url") if thumb is not None else "") or (
            enclosure.get("url") if enclosure is not None and "image" in (enclosure.get("type") or "") else "")
        out.append(Story(_clean(item.findtext("title", "")), (item.findtext("link") or "").strip(), source, section,
                         _clean(item.findtext("description", "")), _when(item.findtext("pubDate", "")), image,
                         rank=i))
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link = entry.find("atom:link[@rel='alternate']", _NS)
        if link is None:
            link = entry.find("atom:link", _NS)
        out.append(Story(_clean(entry.findtext("atom:title", "", _NS)), link.get("href", "") if link is not None else "",
                         source, section, _clean(entry.findtext("atom:summary", "", _NS)),
                         _when(entry.findtext("atom:published", "", _NS) or entry.findtext("atom:updated", "", _NS))))
    return [s for s in out if s.title and s.url][:limit]


def rss_stories() -> list[Story]:
    def one(row):
        source, section, url = row
        try:
            return parse_feed(_get(url).text, source, section)
        except Exception:
            return []

    with ThreadPoolExecutor(8) as pool:
        return [s for batch in pool.map(one, RSS) for s in batch]


# ---- The Guardian ------------------------------------------------------------------------

GUARDIAN = "https://content.guardianapis.com"
GUARDIAN_GROUPS = (
    ("us-news|politics", "Government & politics"),
    ("world", "World"),
    ("science|environment|society", "Science & health"),
    ("technology", "Technology"),
    ("business|money", "Business & markets"),
    ("sport|football", "Sports"),
    ("culture|film|music|tv-and-radio|books|artanddesign|stage", "Culture & gossip"),
)
GUARDIAN_LONG_READ = "news/series/the-long-read"


GUARDIAN_PATHS = {
    "Government & politics": ("us-news", "politics", "law"),
    "World": ("world", "uk-news", "australia-news", "global-development"),
    "Science & health": ("science", "environment", "society", "healthcare-network"),
    "Technology": ("technology",),
    "Business & markets": ("business", "money"),
    "Sports": ("sport", "football"),
    "Culture & gossip": ("culture", "film", "music", "tv-and-radio", "books", "artanddesign", "stage", "lifeandstyle",
                         "fashion", "food", "games", "travel"),
    "Ideas & long reads": ("commentisfree", "news"),
}


def guardian_section(url: str) -> str:
    """The section a Guardian article belongs to, from the first part of its address."""
    part = url.split("theguardian.com/", 1)[-1].split("/", 1)[0]
    return next((name for name, parts in GUARDIAN_PATHS.items() if part in parts), "World")


def _guardian_story(r: dict, section: str, pick: bool = False, rank: int = 99) -> Story:
    f = r.get("fields") or {}
    if pick:
        section = guardian_section(r.get("webUrl", ""))
    return Story(r.get("webTitle", ""), r.get("webUrl", ""), "The Guardian", section, _clean(f.get("trailText", "")),
                 _when(r.get("webPublicationDate", "")), f.get("thumbnail", ""), pick, rank=rank)


def guardian_stories() -> list[Story]:
    key = _key("GUARDIAN_API_KEY")
    if not key:
        return []
    fields = {"show-fields": "trailText,thumbnail", "api-key": key}
    out = []
    try:  # the editors' front page for the US edition
        body = _get(f"{GUARDIAN}/us", **{"show-editors-picks": "true", "page-size": 1, **fields}).json()["response"]
        out += [_guardian_story(r, "Front page", pick=True, rank=i) for i, r in enumerate(body.get("editorsPicks", [])[:14])]
    except Exception:
        pass
    calls = [({"section": s, "page-size": 14, "order-by": "newest"}, sec) for s, sec in GUARDIAN_GROUPS]
    calls.append(({"tag": GUARDIAN_LONG_READ, "page-size": 6, "order-by": "newest"}, "Ideas & long reads"))
    for params, section in calls:
        time.sleep(1.0)   # the free developer key allows about one request a second
        try:
            body = _get(f"{GUARDIAN}/search", **params, **fields).json()["response"]
            out += [_guardian_story(r, section) for r in body.get("results", [])]
        except Exception:
            continue
    return [s for s in out if s.title]


# ---- The New York Times ------------------------------------------------------------------

NYT_TOP = "https://api.nytimes.com/svc/topstories/v2/{}.json"
NYT_SECTIONS = (("home", "Front page"), ("politics", "Government & politics"), ("arts", "Culture & gossip"),
                ("science", "Science & health"))   # five a minute: four keeps one in reserve


def nyt_stories() -> list[Story]:
    key = _key("NYT_API_KEY")
    if not key:
        return []
    out = []
    for name, section in NYT_SECTIONS:
        try:
            for i, r in enumerate(_get(NYT_TOP.format(name), **{"api-key": key}).json().get("results", [])[:12]):
                media = [m for m in r.get("multimedia") or [] if m.get("url")]
                image = next((m["url"] for m in media if m.get("format") in ("threeByTwoSmallAt2X", "Large Thumbnail")),
                             media[0]["url"] if media else "")
                out.append(Story(r.get("title", ""), r.get("url", ""), "The New York Times", section,
                                 _clean(r.get("abstract", "")), _when(r.get("published_date", "")), image,
                                 pick=name == "home", rank=i))
        except Exception:
            continue
    return [s for s in out if s.title and s.url]


# ---- Wikipedia -----------------------------------------------------------------------------

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_FEED = "https://en.wikipedia.org/api/rest_v1/feed/featured/{:%Y/%m/%d}"


def in_the_news() -> list[str]:
    """The few events Wikipedia's editors judge most important worldwide right now."""
    try:
        text = _get(WIKI_API, action="parse", page="Template:In_the_news", prop="text", format="json",
                    formatversion=2).json()["parse"]["text"]
    except Exception:
        return []
    block = text.split("Ongoing")[0]
    return [_clean(i, 400) for i in re.findall(r"<li>(.*?)</li>", block, re.S)][:6]


def on_this_day(day: date | None = None, n: int = 4) -> list[str]:
    day = day or date.today()
    try:
        events = _get(WIKI_FEED.format(day)).json().get("onthisday", [])
    except Exception:
        return []
    picks = sorted(events, key=lambda e: e.get("year", 0))
    step = max(len(picks) // n, 1)
    return [f"{e['year']}: {_clean(e.get('text', ''), 220)}" for e in picks[::step][:n]]


def gather() -> tuple[list[Story], list[str], list[str]]:
    """Every story from every source, plus Wikipedia's top events and this day in history."""
    with ThreadPoolExecutor(5) as pool:
        jobs = [pool.submit(f) for f in (rss_stories, guardian_stories, nyt_stories, in_the_news, on_this_day)]
        rss, guardian, nyt, itn, history = (j.result() for j in jobs)
    return rss + guardian + nyt, itn, history
