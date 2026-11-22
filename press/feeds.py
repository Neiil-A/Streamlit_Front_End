# © 2026 Neiil Apshankar. All rights reserved. Personal project — not an app, platform, or business. See NOTICE.md.
"""Where Stop Looking at my Computer News gets its stories: free sources, chosen for substance.

Every outlet here is free to read on its own site, so a click never lands on a paywall: The Guardian
(open API, free developer key GUARDIAN_API_KEY), NPR, PBS NewsHour, Al Jazeera, DW, ProPublica,
Ars Technica, Quanta, Aeon, The Conversation, ESPN, and Wikipedia's "In the news" and "On this day".
The New York Times' Top Stories (free key NYT_API_KEY) helps rank stories and is marked as paywalled.
Quizzes, deals and live blogs are left out; celebrity news is capped at three items a day.

Three outlets allow their full articles to be shown here: The Guardian (its open API), The
Conversation (Creative Commons BY-ND) and ProPublica (Creative Commons BY-NC-ND). Those can be read
on the page, unchanged and credited; everything else opens at the publisher.
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

UA = {"User-Agent": "Mozilla/5.0 (personal news reader; non-commercial)"}
TIMEOUT = 15
SECTIONS = ("World", "Politics", "Business & markets", "Technology", "Science & health", "Ideas", "Culture",
            "Sports", "Social")
PAYWALLED = {"The New York Times"}
FULL_TEXT_LICENCE = {
    "The Guardian": "Shown in full through the Guardian's open platform.",
    "The Conversation": "Republished under Creative Commons BY-ND 4.0.",
    "ProPublica": "Republished under Creative Commons BY-NC-ND 3.0.",
}
# Titles that are noise, not news.
JUNK = re.compile(r"\b(quiz|crossword|wordle|sudoku|horoscope|puzzle|deals?|discount|gift guide|recipe|shopping|"
                  r"photos? of the (day|week)|what to watch|how to watch|live updates|as it happened|podcast|"
                  r"newsletter|sponsored|giveaway|coupon|red carpet|outfit|bikini|wardrobe|wait wait|not my job)\b|– live$|- live$", re.I)


@dataclass
class Story:
    title: str
    url: str
    source: str
    section: str
    summary: str = ""
    published: datetime | None = None
    image: str = ""
    pick: bool = False           # an editor put it on their front page
    rank: int = 99               # its place in the outlet's own running order (0 = top story), when it has one
    body: str = ""               # the full article, when the publisher allows showing it (paragraphs, plain text)
    byline: str = ""
    also: list[str] = field(default_factory=list)                     # other outlets with the same story
    links: list[tuple[str, str]] = field(default_factory=list)        # (outlet, link) for each of them


def _key(name: str) -> str:
    """The environment (.env, when PHANTOM runs it) first, then Streamlit's secrets (when hosted)."""
    if os.environ.get(name):
        return os.environ[name]
    try:
        import streamlit as st

        return str(st.secrets.get(name, ""))
    except Exception:
        return ""


def _clean(text: str, limit: int = 300) -> str:
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def paragraphs(html_text: str, max_words: int = 3000) -> str:
    """An article's HTML as plain paragraphs (figures, scripts and captions dropped)."""
    text = re.sub(r"(?is)<(script|style|figure|figcaption|aside)[^>]*>.*?</\1>", " ", html_text or "")
    parts = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", p)).split())
             for p in re.split(r"(?i)</p>|<br\s*/?>\s*<br\s*/?>", text)]
    out, words = [], 0
    for p in parts:
        if len(p) < 3:
            continue
        out.append(p)
        words += len(p.split())
        if words >= max_words:
            out.append("…")
            break
    return "\n\n".join(out)


def sharper(url: str) -> str:
    """A bigger copy of a picture where the publisher offers one (feeds often carry 240-500 px thumbnails)."""
    if not url.startswith("https://"):
        return ""
    if re.search(r"[?&]s=[0-9a-f]{16,}", url):     # a signed address (the Guardian's): changing the size breaks it
        return url
    url = re.sub(r"(media\.guim\.co\.uk/.+?)/(140|500)\.(jpg|jpeg|png)$", r"\1/1000.\3", url)
    url = re.sub(r"-\d{2,4}x\d{2,4}(\.(?:jpe?g|png|webp))(\?|$)", r"\1\2", url)          # WordPress-sized copies
    url = re.sub(r"([?&](?:w|width|resize))=\d+", lambda m: m.group(1) + "=1200", url)
    return url


def _first_image(html_text: str) -> str:
    m = re.search(r'<img[^>]+src="(https://[^"]+)"', html_text or "")
    return m.group(1) if m else ""


def _when(text: str) -> datetime | None:
    if not text:
        return None
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _get(url: str, **params) -> requests.Response:
    resp = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


# ---- RSS, RDF and Atom -------------------------------------------------------------------

RSS = (
    # (source, section, url, keeps the outlet's running order)
    ("NPR", "World", "https://feeds.npr.org/1001/rss.xml", True),
    ("NPR", "World", "https://feeds.npr.org/1004/rss.xml", True),
    ("Al Jazeera", "World", "https://www.aljazeera.com/xml/rss/all.xml", True),
    ("DW", "World", "https://rss.dw.com/rdf/rss-en-all", True),
    ("NPR", "Politics", "https://feeds.npr.org/1014/rss.xml", True),
    ("PBS NewsHour", "Politics", "https://www.pbs.org/newshour/feeds/rss/headlines", True),
    ("ProPublica", "Politics", "https://www.propublica.org/feeds/propublica/main", False),
    ("NPR", "Business & markets", "https://feeds.npr.org/1006/rss.xml", True),
    ("NPR", "Technology", "https://feeds.npr.org/1019/rss.xml", True),
    ("Ars Technica", "Technology", "https://feeds.arstechnica.com/arstechnica/index", False),
    ("NPR", "Science & health", "https://feeds.npr.org/1007/rss.xml", True),
    ("NPR", "Science & health", "https://feeds.npr.org/1128/rss.xml", True),
    ("Quanta", "Science & health", "https://www.quantamagazine.org/feed/", False),
    ("Aeon", "Ideas", "https://aeon.co/feed.rss", False),
    ("The Conversation", "Ideas", "https://theconversation.com/us/articles.atom", False),
    ("NPR", "Culture", "https://feeds.npr.org/1008/rss.xml", False),
    ("The Conversation", "Culture", "https://theconversation.com/us/arts/articles.atom", False),
    ("Smithsonian", "Culture", "https://www.smithsonianmag.com/rss/arts-culture/", False),
    ("Literary Hub", "Culture", "https://lithub.com/feed/", False),
    ("Hyperallergic", "Culture", "https://hyperallergic.com/feed/", False),
    ("Open Culture", "Culture", "https://www.openculture.com/feed", False),
    # the Guardian's own free feeds (no key): its API adds full text when a key is set; copies merge by address
    ("The Guardian", "Science & health", "https://www.theguardian.com/science/rss", True),
    ("The Guardian", "World", "https://www.theguardian.com/world/rss", True),
    ("The Guardian", "Politics", "https://www.theguardian.com/us-news/rss", True),
    ("The Guardian", "Business & markets", "https://www.theguardian.com/business/rss", True),
    ("The Conversation", "Business & markets", "https://theconversation.com/us/business/articles.atom", False),
    ("ESPN NBA", "Sports", "https://www.espn.com/espn/rss/nba/news", True),
    ("ESPN NFL", "Sports", "https://www.espn.com/espn/rss/nfl/news", True),
    ("E! News", "Social", "https://www.eonline.com/syndication/feeds/rssfeeds/topstories.xml", True),
)
_NS = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/",
       "content": "http://purl.org/rss/1.0/modules/content/", "dc": "http://purl.org/dc/elements/1.1/",
       "rss1": "http://purl.org/rss/1.0/"}


def _find(item, *paths):
    for p in paths:
        found = item.find(p, _NS)
        if found is not None:          # (an element with no children is falsy: compare with None)
            return found
    return None


def _widest_picture(item) -> str:
    """The biggest picture an item offers (feeds like the Guardian's list several sizes, smallest first)."""
    best, best_w = "", -1
    for tag in ("media:content", "media:thumbnail", "media:group/media:content", "enclosure"):
        for m in item.findall(tag, _NS):
            if "video" in (m.get("type") or "") or not m.get("url"):
                continue
            w = int(m.get("width") or 0)
            if w > best_w:
                best, best_w = m.get("url", ""), w
    return best


def parse_feed(xml_text: str, source: str, section: str, ordered: bool = True, limit: int = 12) -> list[Story]:
    root = ET.fromstring(xml_text)
    out = []
    items = list(root.iter("item")) + list(root.iter("{http://purl.org/rss/1.0/}item"))
    for i, item in enumerate(items):
        def text(tag: str) -> str:
            return item.findtext(tag, "", _NS) or ""

        rich, desc = text("content:encoded"), text("description") or text("rss1:description")
        image = _widest_picture(item)
        out.append(Story(
            _clean(text("title") or text("rss1:title"), 200), (text("link") or text("rss1:link")).strip(), source,
            section, _clean(desc), _when(text("pubDate") or text("dc:date")),
            sharper(image or _first_image(rich) or _first_image(desc)), rank=i if ordered else 99,
            body=paragraphs(rich) if source in FULL_TEXT_LICENCE and len(rich) > 1500 else "",
            byline=_clean(text("dc:creator"), 80)))
    for i, entry in enumerate(root.iter("{http://www.w3.org/2005/Atom}entry")):
        link = _find(entry, "atom:link[@rel='alternate']", "atom:link")
        content = entry.findtext("atom:content", "", _NS)
        author = entry.find("atom:author/atom:name", _NS)
        out.append(Story(
            _clean(entry.findtext("atom:title", "", _NS), 200), link.get("href", "") if link is not None else "",
            source, section, _clean(entry.findtext("atom:summary", "", _NS) or content),
            _when(entry.findtext("atom:published", "", _NS) or entry.findtext("atom:updated", "", _NS)),
            sharper(_first_image(content)), rank=i if ordered else 99,
            body=paragraphs(content) if source in FULL_TEXT_LICENCE else "",
            byline=author.text if author is not None and author.text else ""))
    return [s for s in out if s.title and s.url and not JUNK.search(s.title)][:limit]


def rss_stories() -> list[Story]:
    def one(row):
        source, section, url, ordered = row
        try:
            return parse_feed(_get(url).text, source, section, ordered)
        except Exception:
            return []

    with ThreadPoolExecutor(12) as pool:
        return [s for batch in pool.map(one, RSS) for s in batch]


# ---- The Guardian ------------------------------------------------------------------------

GUARDIAN = "https://content.guardianapis.com"
GUARDIAN_GROUPS = (
    ("us-news|politics", "Politics"),
    ("world|global-development", "World"),
    ("science|environment", "Science & health"),
    ("technology", "Technology"),
    ("business", "Business & markets"),
    ("books|culture|film|music|artanddesign|stage", "Culture"),
)
GUARDIAN_LONG_READ = "news/series/the-long-read"
GUARDIAN_PATHS = {
    "Politics": ("us-news", "politics", "law"),
    "World": ("world", "uk-news", "australia-news", "global-development"),
    "Science & health": ("science", "environment", "society"),
    "Technology": ("technology",),
    "Business & markets": ("business", "money"),
    "Sports": ("sport", "football"),
    "Culture": ("culture", "film", "music", "books", "artanddesign", "stage", "tv-and-radio"),
    "Ideas": ("commentisfree", "news"),
}
GUARDIAN_SKIP = ("lifeandstyle", "fashion", "food", "travel", "games", "crosswords", "thefilter", "wellness")


def guardian_section(url: str) -> str:
    """The section a Guardian article belongs to, from the first part of its address ('' to leave it out)."""
    part = url.split("theguardian.com/", 1)[-1].split("/", 1)[0]
    if part in GUARDIAN_SKIP:
        return ""
    return next((name for name, parts in GUARDIAN_PATHS.items() if part in parts), "World")


def _guardian_story(r: dict, section: str, pick: bool = False, rank: int = 99) -> Story | None:
    f = r.get("fields") or {}
    if pick:
        section = guardian_section(r.get("webUrl", ""))
    if not section or JUNK.search(r.get("webTitle", "")):
        return None
    body = "\n\n".join(p.strip() for p in re.split(r"\n+", f.get("bodyText", "")) if p.strip())
    if body.count("\n\n") < 2:   # the API's plain text often has no line breaks: split into ~4-sentence paragraphs
        sentences = re.split(r"(?<=[.!?\"”])\s+(?=[A-Z“\"])", body)
        body = "\n\n".join(" ".join(sentences[i:i + 4]) for i in range(0, len(sentences), 4))
    return Story(r.get("webTitle", ""), r.get("webUrl", ""), "The Guardian", section, _clean(f.get("trailText", "")),
                 _when(r.get("webPublicationDate", "")), sharper(f.get("thumbnail", "")), pick, rank=rank,
                 body=body if len(body) > 600 else "", byline=_clean(f.get("byline", ""), 80))


def guardian_stories() -> list[Story]:
    key = _key("GUARDIAN_API_KEY")
    if not key:
        return []
    fields = {"show-fields": "trailText,thumbnail,bodyText,byline", "api-key": key}
    out = []
    try:  # the editors' front page for the US edition, in their order
        body = _get(f"{GUARDIAN}/us", **{"show-editors-picks": "true", "page-size": 1, **fields}).json()["response"]
        out += [_guardian_story(r, "", pick=True, rank=i) for i, r in enumerate(body.get("editorsPicks", [])[:16])]
    except Exception:
        pass
    calls = [({"section": s, "page-size": 12, "order-by": "newest"}, sec) for s, sec in GUARDIAN_GROUPS]
    calls.append(({"tag": GUARDIAN_LONG_READ, "page-size": 6, "order-by": "newest"}, "Ideas"))
    for params, section in calls:
        time.sleep(1.0)   # the free developer key allows about one request a second
        try:
            body = _get(f"{GUARDIAN}/search", **params, **fields).json()["response"]
            out += [_guardian_story(r, section) for r in body.get("results", [])]
        except Exception:
            continue
    return [s for s in out if s and s.title]


# ---- The New York Times (ranking help: it's paywalled) ------------------------------------

NYT_TOP = "https://api.nytimes.com/svc/topstories/v2/{}.json"
NYT_SECTIONS = ("home", "politics", "science", "arts")
NYT_SECTION_OF = {"us": "Politics", "world": "World", "business": "Business & markets", "technology": "Technology",
                  "science": "Science & health", "health": "Science & health", "arts": "Culture", "books": "Culture",
                  "sports": "Sports", "opinion": "Ideas", "politics": "Politics"}


def nyt_stories() -> list[Story]:
    key = _key("NYT_API_KEY")
    if not key:
        return []
    out = []
    for name in NYT_SECTIONS:
        try:
            for i, r in enumerate(_get(NYT_TOP.format(name), **{"api-key": key}).json().get("results", [])[:12]):
                media = {m.get("format"): m.get("url", "") for m in r.get("multimedia") or []}
                if r.get("title") and not JUNK.search(r["title"]):
                    out.append(Story(r["title"], r.get("url", ""), "The New York Times",
                                     NYT_SECTION_OF.get(r.get("section", ""), "World"), _clean(r.get("abstract", "")),
                                     _when(r.get("published_date", "")),
                                     media.get("superJumbo") or media.get("threeByTwoSmallAt2X") or "",
                                     pick=name == "home", rank=i))
        except Exception:
            continue
    return [s for s in out if s.url]


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
    return [re.sub(r"\s+\((pictured|rendering shown|shown)\)", "", _clean(i, 400))
            for i in re.findall(r"<li>(.*?)</li>", block, re.S)][:6]


def on_this_day(day: date | None = None, n: int = 4) -> list[str]:
    day = day or date.today()
    try:
        events = _get(WIKI_FEED.format(day)).json().get("onthisday", [])
    except Exception:
        return []
    picks = sorted(events, key=lambda e: e.get("year", 0))
    step = max(len(picks) // n, 1)
    return [f"{e['year']}: {re.sub(r' [(]pictured[)]', '', _clean(e.get('text', ''), 220))}" for e in picks[::step][:n]]


def gather() -> tuple[list[Story], list[str], list[str]]:
    """Every story from every source, plus Wikipedia's top events and this day in history."""
    with ThreadPoolExecutor(5) as pool:
        jobs = [pool.submit(f) for f in (rss_stories, guardian_stories, nyt_stories, in_the_news, on_this_day)]
        rss, guardian, nyt, itn, history = (j.result() for j in jobs)
    return rss + guardian + nyt, itn, history
