# © 2026 Neiil Apshankar. All rights reserved. Personal project — not an app, platform, or business. See NOTICE.md.
"""Stop Looking at my Computer News: the day's news, from free sources, as a modern reading page.

Pages along the top: the front page (a guide to every page, the economy in brief and what's coming up), one
page per section (each opening with a five-point briefing), Sports (every league at a glance, then recaps,
results, top performers, quotes, a week of fixtures and tables) and Markets (the economy's vital signs from
Neiil's own tools). Stories show how many outlets report them, with a link to each; where the publisher
allows it, the full article opens right here. Grim news (violence, crime, arrests, immigration raids) is
left out on purpose.

The market findings arrive sealed with the site password (press/vault.py) and are opened with the password
typed at the lock screen, so the repository can stay public.

Run locally:   .venv/bin/streamlit run press/app.py
Hosted:        Streamlit Community Cloud, main file streamlit_app.py (or press/app.py). Works with no
               settings; optional Secrets: GUARDIAN_API_KEY, NYT_API_KEY, APP_PASSWORD, LINKEDIN_URL.
"""

from __future__ import annotations

import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))   # so `press` imports when run as a script

from press import sports  # noqa: E402
from press.edition import Edition, build, outlets  # noqa: E402
from press.feeds import FULL_TEXT_LICENCE, PAYWALLED, SECTIONS, Story  # noqa: E402
from press.lock import matches  # noqa: E402

NAME = "Stop Looking at my Computer News"
AUTHOR = "Neiil Apshankar"
LINKEDIN_URL = "https://www.linkedin.com/in/neiil-apshankar/"     # LINKEDIN_URL in the app's Secrets overrides it
ET = ZoneInfo("America/New_York")
NEWS_TTL, SPORTS_TTL = 45 * 60, 10 * 60
SEALED_FILE = ROOT / "data" / "findings.json"                              # published each night, sealed
LOCAL_FILES = (ROOT / "data" / "markets.json", ROOT / "data" / "backtests" / "markets.json")   # on the home machine
NAV_SECTIONS = [s for s in SECTIONS if s not in ("Sports", "Social")]
BRIEF = 5
ALL_SPORTS = "All sports"
PAGES: dict = {}
MADE_BY = "Neiil built and developed for critical economy insights"
GUIDE = {   # what each page has, shown on the front page and under each page's title
    "Front page": ("🗞️", "Today's top stories, the economy in plain words, and what's coming up in the weeks ahead"),
    "World": ("🌍", "Major events in other countries: diplomacy, elections, economies"),
    "Politics": ("🏛️", "US government: Congress, the White House, courts and elections"),
    "Business & markets": ("💼", "Companies, the economy, and how every industry's shares are doing"),
    "Technology": ("💡", "Tech companies, AI, gadgets and the internet"),
    "Science & health": ("🔬", "Discoveries, medicine, climate, and health-care shares"),
    "Ideas": ("📚", "Essays and explainers worth your time"),
    "Entertainment": ("🎬", "Movies, music, books, art and TV"),
    "Sports": ("🏅", "Recaps, scores, top performers, quotes and a week of upcoming games for every major league"),
    "Markets": ("📈", "The economy's vital signs, explained, and every market against its last three years"),
}

st.set_page_config(page_title=NAME, page_icon="🗞️", layout="wide", initial_sidebar_state="collapsed")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600;8..60,700&display=swap');
:root { --bg:#f4f6f9; --card:#ffffff; --ink:#0b1b33; --soft:#3e4c63; --muted:#7b879a; --line:#e2e7ef;
        --accent:#1d4f91; --sky:#8fb3e3; --navy:#0a2342; --good:#0e7a4e; --bad:#c0392b; --chip:#e8eef8; }
.stApp, [data-testid="stAppViewContainer"] { background: var(--bg); }
[data-testid="stHeader"] { background: linear-gradient(90deg, #071a33, #0d2e58 60%, #16427a); border-bottom: 3px solid var(--sky); }
[data-testid="stHeader"] [data-testid="stToolbar"] button, [data-testid="stHeader"] svg { color: #fff !important; fill: #fff !important; }
[data-testid="stTopNavLink"] { background: rgba(255,255,255,.10); border-radius: 999px; padding: .32rem .85rem !important; margin: 0 .12rem;
  border: 1px solid rgba(255,255,255,.18); transition: background .15s; }
[data-testid="stTopNavLink"], [data-testid="stTopNavLink"] * { color: #e9f0fb !important; font-weight: 600 !important; font-size: .86rem !important; }
[data-testid="stTopNavLink"]:hover { background: rgba(255,255,255,.22); }
[data-testid="stTopNavLink"][aria-current="page"] { background: #fff; border-color: #fff; }
[data-testid="stTopNavLink"][aria-current="page"], [data-testid="stTopNavLink"][aria-current="page"] * { color: #0a2342 !important; }
[data-testid="stTopNavSection"], [data-testid="stTopNavSection"] * { color: #fff !important; font-weight: 600; }
[data-testid="stBaseButton-segmented_control"] { background: #e3ecf9 !important; border: 1px solid #c3d4ee !important; }
[data-testid="stBaseButton-segmented_control"], [data-testid="stBaseButton-segmented_control"] * { color: #1d4f91 !important; font-weight: 600 !important; }
[data-testid="stBaseButton-segmented_control"]:hover { background: #cfdef5 !important; }
[data-testid="stBaseButton-segmented_controlActive"] { background: #0a2342 !important; border: 1px solid #0a2342 !important; }
[data-testid="stBaseButton-segmented_controlActive"], [data-testid="stBaseButton-segmented_controlActive"] * { color: #fff !important; font-weight: 700 !important; }
[data-testid="stPageLink"] a { background: #e8eef8; border: 1px solid #c9d7ee; border-radius: 10px; padding: .35rem .7rem; }
[data-testid="stPageLink"] a:hover { background: #d6e3f6; }
[data-testid="stPageLink"] a * { color: #0a2342 !important; font-weight: 700 !important; }
.block-container { max-width: 1240px; padding-top: 3.8rem; padding-bottom: 4rem; }
html, body, .x, .x p, .x li, .x td { font-family: Inter, -apple-system, Segoe UI, sans-serif; color: var(--ink); }
.x a { color: inherit; text-decoration: none; }
.x a:hover { color: var(--accent); }
.serif { font-family: "Source Serif 4", Georgia, serif; }
.brand { display:flex; align-items: center; justify-content: space-between; gap: .6rem 1rem; flex-wrap: wrap;
  padding: .3rem 0 1rem; border-bottom: 1px solid var(--line); margin-bottom: 1.5rem; }
.brand .name { font-weight: 800; letter-spacing: -.025em; font-size: clamp(1.25rem, 2.6vw, 1.8rem); color: var(--navy); }
.brand .name span { color: var(--accent); }
.brand .meta { color: var(--muted); font-size: .76rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; }
.page-title { font-family: "Source Serif 4", Georgia, serif; font-weight: 600; font-size: clamp(1.8rem, 3.4vw, 2.4rem);
  letter-spacing: -.01em; margin: 0 0 .25rem; color: var(--navy); }
.page-sub { color: var(--soft); margin: 0 0 1.3rem; font-size: .95rem; }
.eyebrow { font-size: .7rem; letter-spacing: .14em; text-transform: uppercase; font-weight: 700; color: var(--accent); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; overflow: hidden;
  box-shadow: 0 1px 2px rgba(10,35,66,.04); margin-bottom: .35rem; }
.card .img { width:100%; aspect-ratio: 16/9; object-fit: cover; display:block; background:#e6ebf2; }
.card .in { padding: .9rem 1rem 1rem; }
.lead .img { aspect-ratio: 16/8.5; }
.meta-row { display:flex; flex-wrap: wrap; gap: .35rem .5rem; align-items:center; font-size: .72rem; color: var(--muted);
  font-weight: 600; letter-spacing: .01em; margin-bottom: .45rem; }
.src { color: var(--ink); }
.chip { background: var(--chip); color: var(--accent); border-radius: 999px; padding: .12rem .5rem; font-weight: 700; font-size: .7rem;
  white-space: nowrap; }
.chip.one { background:#f0f2f6; color: var(--muted); }
.chip.pay { background:#fff4e5; color:#a35f00; }
.card h3 { font-family: "Source Serif 4", Georgia, serif; font-weight: 600; font-size: 1.2rem; line-height: 1.26; margin: 0 0 .4rem; }
.lead h3 { font-size: clamp(1.6rem, 3vw, 2.3rem); line-height: 1.12; }
.card p.sum { color: var(--soft); font-size: .92rem; line-height: 1.5; margin: 0; }
.lead p.sum { font-size: 1.05rem; }
.check { margin-top: .6rem; font-size: .75rem; color: var(--muted); }
.check a { color: var(--accent); font-weight: 600; }
.box { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 1rem 1.1rem; margin-bottom: 1rem; }
.box h4, .brief h4 { font-size: .7rem; letter-spacing: .12em; text-transform: uppercase; color: var(--accent); margin: 0 0 .65rem; font-weight: 700; }
.box ul { margin: 0; padding-left: 1.05rem; } .box li { margin: 0 0 .55rem; font-size: .93rem; line-height: 1.45; }
.brief { background: var(--card); border: 1px solid var(--line); border-left: 4px solid var(--navy); border-radius: 14px;
  padding: 1.1rem 1.2rem .6rem; margin-bottom: 1.2rem; }
.brief ol { list-style: none; counter-reset: b; margin: 0; padding: 0; }
.brief li { counter-increment: b; position: relative; padding: 0 0 .85rem 2.1rem; font-size: .95rem; line-height: 1.45; }
.brief li::before { content: counter(b); position: absolute; left: 0; top: .05rem; width: 1.45rem; height: 1.45rem; border-radius: 50%;
  background: var(--navy); color: #fff; font-size: .72rem; font-weight: 700; display:flex; align-items:center; justify-content:center; }
.brief li b { font-weight: 700; } .brief li div { color: var(--soft); font-size: .88rem; margin-top: .15rem; }
.section-h { display:flex; justify-content: space-between; align-items: baseline; gap: 1rem; margin: 1.8rem 0 .8rem;
  border-top: 2px solid var(--navy); padding-top: .6rem; }
.section-h h2 { font-size: 1.05rem; font-weight: 800; margin: 0; letter-spacing: -.005em; color: var(--navy); }
.section-h span { color: var(--muted); font-size: .78rem; text-align: right; }
.article { font-family: "Source Serif 4", Georgia, serif; font-size: 1.08rem; line-height: 1.68; color: #18243a; }
.article .by { font-family: Inter; font-size: .8rem; color: var(--muted); margin-bottom: .6rem; }
.article .lic { font-family: Inter; font-size: .75rem; color: var(--muted); border-top: 1px solid var(--line); padding-top: .5rem; margin-top: .8rem; }
.panel { background: var(--card); border: 1px solid var(--line); border-radius: 16px; overflow: hidden; margin-bottom: 1.2rem; }
.panel .top { background: linear-gradient(120deg, #0a2342, #16427a); color: #fff; padding: .75rem 1.1rem; display:flex;
  justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }
.panel .top b { font-size: .72rem; letter-spacing: .14em; text-transform: uppercase; }
.panel .top span { font-size: .76rem; color: rgba(255,255,255,.72); }
.panel .body { padding: 1rem 1.1rem .4rem; }
.panel ul { columns: 2 320px; column-gap: 2rem; margin: .4rem 0 0; padding-left: 1.05rem; }
.panel li { break-inside: avoid; margin: 0 0 .6rem; font-size: .9rem; line-height: 1.45; color: var(--soft); }
.game { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: .75rem .9rem; margin-bottom: .7rem; }
.game .st { font-size: .7rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin-bottom: .35rem; }
.game .st.live { color: var(--bad); }
.game .row { display:flex; justify-content: space-between; align-items:center; font-size: .95rem; padding: .12rem 0; }
.game .row.win { font-weight: 700; } .game .rec { color: var(--muted); font-size: .75rem; margin-left: .35rem; font-weight: 500; }
.game .sc { font-variant-numeric: tabular-nums; font-weight: 700; }
.game .stars { font-size: .78rem; color: var(--soft); margin-top: .4rem; line-height: 1.45; }
.lg { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 1rem 1.1rem .7rem; margin-bottom: 1rem; }
.lg h3 { font-size: 1.02rem; font-weight: 800; margin: 0 0 .2rem; color: var(--navy); }
.lg .k { font-size: .66rem; letter-spacing: .12em; text-transform: uppercase; color: var(--accent); font-weight: 700; margin: .7rem 0 .25rem; }
.lg .g { font-size: .88rem; padding: .3rem 0; border-bottom: 1px solid #edf0f5; line-height: 1.4; }
.lg .g:last-child { border-bottom: 0; }
.lg .g small { display:block; color: var(--muted); font-size: .74rem; }
.lg .n { font-size: .86rem; padding: .3rem 0; line-height: 1.4; } .lg .n a { font-weight: 600; }
.lg .n div { color: var(--soft); font-size: .8rem; margin-top: .1rem; }
.quote { font-family: "Source Serif 4", Georgia, serif; font-size: 1.08rem; line-height: 1.45; border-left: 3px solid var(--accent);
  padding: .1rem 0 .1rem .8rem; margin: 0 0 .9rem; }
.quote a { display:block; font-family: Inter; font-size: .74rem; color: var(--muted); margin-top: .25rem; }
.tw { overflow-x: auto; margin-bottom: 1rem; }
table.t { width:100%; border-collapse: collapse; font-size: .88rem; background: var(--card); border-radius: 12px; overflow: hidden; }
table.t th { text-align:left; color: #fff; font-weight: 700; font-size: .68rem; text-transform: uppercase; letter-spacing: .08em;
  padding: .62rem .6rem; background: linear-gradient(90deg, #0a2342, #16427a); }
table.t td { padding: .5rem .6rem; border-bottom: 1px solid #eef1f5; font-variant-numeric: tabular-nums; }
table.t .fund { color: var(--muted); font-size: .72rem; margin-left: .3rem; }
.up { color: var(--good); font-weight: 600; } .down { color: var(--bad); font-weight: 600; }
.bar { position: relative; height: 6px; background: #e3e8ef; border-radius: 99px; min-width: 90px; }
.bar i { position:absolute; top:-3px; width: 12px; height: 12px; border-radius: 50%; background: var(--accent); transform: translateX(-50%); }
.tiles { display:grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: .8rem; margin-bottom: .9rem; }
.tile { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: .8rem 1rem; }
.panel .tile { background: #f7f9fc; }
.tile .l { font-size: .68rem; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }
.tile .v { font-size: 1.55rem; font-weight: 800; letter-spacing: -.02em; margin-top: .15rem; color: var(--navy); }
.tile .s { font-size: .78rem; color: var(--soft); }
.pill { display:inline-block; border-radius: 999px; padding: .2rem .65rem; margin: 0 .35rem .35rem 0; font-size: .8rem; font-weight: 600;
  background: #eef1f5; color: var(--soft); }
.pill.on { background: #fde8e6; color: var(--bad); }
.hero { position: relative; overflow: hidden; border-radius: 20px; padding: 2.3rem 2.3rem 1.9rem; color: #fff;
  background: radial-gradient(900px 380px at 100% -20%, rgba(143,179,227,.38), transparent 60%),
              linear-gradient(140deg, #071a33 0%, #0d2e58 55%, #1a4d8c 100%); }
.hero::after { content: ""; position: absolute; inset: 0; pointer-events: none; opacity: .5;
  background-image: linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px);
  background-size: 44px 44px; mask-image: linear-gradient(180deg, transparent, #000 70%); }
.hero > * { position: relative; z-index: 1; }
.hero .eyebrow { color: var(--sky); }
.hero h1 { font-family: "Source Serif 4", Georgia, serif; font-weight: 600; font-size: clamp(2rem, 4.2vw, 3.1rem); line-height: 1.04;
  letter-spacing: -.015em; margin: .7rem 0 .8rem; color: #fff; }
.hero p { color: rgba(255,255,255,.78); font-size: 1rem; line-height: 1.6; max-width: 34rem; margin: 0; }
.hero .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: .9rem 1.6rem; margin: 1.6rem 0;
  border-top: 1px solid rgba(255,255,255,.16); padding-top: 1.3rem; }
.hero .grid b { display:block; font-size: .9rem; color: #fff; } .hero .grid span { font-size: .8rem; color: rgba(255,255,255,.66); line-height: 1.4; }
.hero .by { display:flex; align-items:center; gap: .7rem 1rem; flex-wrap: wrap; font-size: .86rem; color: rgba(255,255,255,.82); }
.signin .t { font-weight: 800; font-size: 1.2rem; letter-spacing: -.01em; color: var(--navy); margin-top: .4rem; }
.signin .s { color: var(--muted); font-size: .86rem; margin: .2rem 0 .9rem; }
.signin .fine { color: var(--muted); font-size: .76rem; line-height: 1.5; margin-top: .3rem; }
[data-testid="stForm"] { background: var(--card); border: 1px solid var(--line) !important; border-radius: 18px;
  padding: 1.4rem 1.4rem 1.2rem; box-shadow: 0 12px 32px rgba(10,35,66,.08); }
a.li { display:inline-flex; align-items:center; gap: .4rem; background: #0a66c2; color: #fff !important; border-radius: 999px;
  padding: .28rem .8rem .28rem .5rem; font-weight: 600; font-size: .8rem; text-decoration: none; }
a.li:hover { background: #004182; }
a.li svg { width: 15px; height: 15px; fill: #fff; }
.foot { margin-top: 2.8rem; padding-top: 1rem; border-top: 2px solid var(--navy); color: var(--muted); font-size: .76rem; line-height: 1.6; }
.foot .who { display:flex; flex-wrap: wrap; align-items:center; gap: .5rem .9rem; margin-bottom: .55rem; color: var(--soft); font-size: .82rem; }
.foot .who b { color: var(--navy); }
[data-testid="stExpander"] details { border-radius: 12px; border: 1px solid var(--line); background: var(--card); }
.cred { color: var(--muted); font-size: .76rem; white-space: nowrap; }
.credit { font-size: .74rem; color: var(--muted); margin: -.6rem 0 1rem; font-style: italic; }
.guide-d { font-size: .78rem; color: var(--soft); line-height: 1.4; margin: .25rem 0 .8rem; min-height: 2.2em; }
.cal li { list-style: none; margin: 0 0 .55rem; } .cal ul { padding-left: 0 !important; }
.cal .d { display:inline-block; min-width: 5.6rem; font-weight: 700; color: var(--navy); font-size: .82rem; }
.cal .k { display:inline-block; border-radius: 999px; padding: .05rem .45rem; font-size: .64rem; font-weight: 700; margin-right: .35rem;
  text-transform: uppercase; letter-spacing: .06em; }
.k-Fed { background: #0a2342; color: #fff; } .k-Economy { background: #dbe7f8; color: #1d4f91; }
.k-Holiday { background: #eef1f5; color: #5b6678; } .k-Earnings { background: #e2f3ea; color: #0e7a4e; }
.banner { display:flex; align-items:center; gap: .9rem; border-radius: 16px; padding: .9rem 1.1rem; margin: .4rem 0 1rem; color: #fff;
  background: radial-gradient(600px 200px at 100% 0%, rgba(143,179,227,.35), transparent 60%), linear-gradient(120deg, #071a33, #16427a); }
.banner .lgo { width: 46px; height: 46px; border-radius: 12px; background: #fff; display:flex; align-items:center; justify-content:center; flex: 0 0 46px; }
.banner .lgo img { width: 36px; height: 36px; object-fit: contain; }
.banner b { font-size: 1.25rem; letter-spacing: -.01em; display:block; } .banner span { font-size: .8rem; color: rgba(255,255,255,.75); }
.gc { background: var(--card); border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 12px; padding: .8rem .95rem;
  margin-bottom: .75rem; box-shadow: 0 1px 2px rgba(10,35,66,.04); }
.gc.live { border-left-color: var(--bad); } .gc.pre { border-left-color: var(--sky); background: #f7faff; }
.gc .top { display:flex; justify-content: space-between; gap: .6rem; flex-wrap: wrap; font-size: .7rem; font-weight: 700; color: var(--accent);
  text-transform: uppercase; letter-spacing: .06em; margin-bottom: .45rem; }
.gc.live .top .when { color: var(--bad); } .gc .top .venue { color: var(--muted); font-weight: 600; text-transform: none; letter-spacing: 0; }
.gc .row { display:grid; grid-template-columns: 26px 1fr auto auto; align-items:center; gap: .55rem; padding: .16rem 0; font-size: .95rem; }
.gc .row img, .lg img.tl { width: 24px; height: 24px; object-fit: contain; }
.gc .row.win { font-weight: 800; } .gc .rec { color: var(--muted); font-size: .74rem; font-weight: 500; margin-left: .35rem; }
.gc .per { color: var(--muted); font-size: .74rem; font-variant-numeric: tabular-nums; letter-spacing: .04em; }
.gc .sc { font-weight: 800; font-size: 1.15rem; font-variant-numeric: tabular-nums; min-width: 2.2rem; text-align: right; color: var(--navy); }
.gc .recap { margin-top: .55rem; padding: .55rem .7rem; background: #f3f7fd; border-radius: 10px; font-size: .86rem; line-height: 1.45; color: var(--soft); }
.gc .recap b { display:block; color: var(--ink); font-size: .9rem; margin-bottom: .15rem; }
.gc .stars { display:flex; flex-wrap: wrap; gap: .4rem .8rem; margin-top: .55rem; }
.gc .star { display:inline-flex; align-items:center; gap: .4rem; font-size: .8rem; color: var(--soft); background: #f6f8fb;
  border: 1px solid #e6ebf2; border-radius: 999px; padding: .15rem .6rem .15rem .2rem; }
.gc .star img { width: 26px; height: 26px; border-radius: 50%; object-fit: cover; background: #e6ebf2; }
.gc .links { margin-top: .5rem; font-size: .76rem; } .gc .links a { color: var(--accent) !important; font-weight: 600; }
.day { display:inline-block; background: var(--navy); color: #fff; border-radius: 999px; padding: .18rem .7rem; font-size: .72rem; font-weight: 700;
  letter-spacing: .04em; margin: .6rem 0 .5rem; }
.lg { padding: 0 0 .7rem; overflow: hidden; }
.lg .lh { display:flex; align-items:center; gap: .6rem; padding: .7rem 1rem; color: #fff; background: linear-gradient(120deg, #0a2342, #16427a); }
.lg .lh .lgo { width: 32px; height: 32px; border-radius: 8px; background: #fff; display:flex; align-items:center; justify-content:center; }
.lg .lh .lgo img { width: 26px; height: 26px; object-fit: contain; }
.lg .lh b { font-size: 1rem; } .lg .lh span { margin-left: auto; font-size: .72rem; color: rgba(255,255,255,.72); }
.lg .k, .lg .g, .lg .n { margin-left: 1rem; margin-right: 1rem; }
.lg .g { display:flex; gap: .5rem; align-items: flex-start; } .lg .g .tx { flex: 1; }
.lg .g img.tl { width: 20px; height: 20px; margin-top: .1rem; }
@media (max-width: 640px) { .hero { padding: 1.6rem 1.3rem 1.4rem; } .block-container { padding-left: 1rem; padding-right: 1rem; } }
</style>
"""


# ---- data ---------------------------------------------------------------------------------

@st.cache_data(ttl=NEWS_TTL, show_spinner="Gathering today's edition…")
def edition() -> Edition:
    return build()


def _league_data(name: str, tables: bool = True, n: int = 10, ahead: int | None = None) -> dict:
    out = {"games": ([], [], []), "tables": {}, "news": [], "quotes": [], "logo": ""}
    try:
        out["games"] = sports.split(sports.scoreboard(name), n=n, ahead=ahead)
    except Exception:
        pass
    out["logo"] = sports.LOGOS.get(name, "")
    if tables:
        try:
            out["tables"] = sports.standings(name)
        except Exception:
            pass
    try:
        out["news"] = sports.news(name)
        out["quotes"] = sports.quotes(out["news"])
    except Exception:
        pass
    return out


@st.cache_data(ttl=SPORTS_TTL, show_spinner="Getting scores…")
def league(name: str) -> dict:
    return _league_data(name, n=12, ahead=45)      # a week of fixtures


@st.cache_data(ttl=SPORTS_TTL, show_spinner="Getting every league's scores…")
def overview() -> dict:
    with ThreadPoolExecutor(len(sports.LEAGUES)) as pool:
        return dict(zip(sports.LEAGUES, pool.map(lambda name: _league_data(name, tables=False, n=4), sports.LEAGUES)))


def markets() -> dict | None:
    """The market findings: the plain copy on the home machine, or the sealed copy in the repository, opened
    with the password typed at the lock screen."""
    for f in LOCAL_FILES:
        try:
            return json.loads(f.read_text())
        except (FileNotFoundError, ValueError):
            continue
    try:
        blob, stamp = json.loads(SEALED_FILE.read_text()), SEALED_FILE.stat().st_mtime
    except (FileNotFoundError, ValueError):
        return None
    cached = st.session_state.get("_findings")
    if cached and cached[0] == stamp:
        return cached[1]
    from press.vault import unseal

    data = unseal(blob, st.session_state.get("pw", ""))
    st.session_state["_findings"] = (stamp, data)
    return data


def no_findings() -> None:
    if SEALED_FILE.exists():
        st.info("The market findings are here but sealed with a different password from the one this site uses.")
    else:
        st.info("The market findings arrive with the next nightly run (7:45 AM and 10:30 PM ET).")


# ---- pieces ---------------------------------------------------------------------------------

def esc(text: str) -> str:
    return html.escape(str(text or ""), quote=True)


def url(link: str) -> str:
    return esc(link) if str(link).startswith(("https://", "http://")) else "#"


def img(link: str, cls: str = "", alt: str = "") -> str:
    return f'<img class="{cls}" src="{url(link)}" alt="{esc(alt)}" loading="lazy">' if str(link).startswith("https://") else ""


def ago(when: datetime | None) -> str:
    if not when:
        return ""
    mins = int((datetime.now(timezone.utc) - when).total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 1)} min ago"
    if mins < 48 * 60:
        return f"{mins // 60} h ago"
    return when.astimezone(ET).strftime("%b %d").replace(" 0", " ")


def first_sentence(text: str, limit: int = 220) -> str:
    text = " ".join((text or "").split())
    m = re.match(r"(.{40,}?[.!?])(\s|$)", text)
    s = m.group(1) if m else text
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "…"


def credit(*tools: str) -> str:
    names = " and ".join(tools)
    return f"{names}, {'tools' if len(tools) > 1 else 'a tool'} {MADE_BY}, found this."


def brand(subtitle: str = "") -> None:
    now = datetime.now(ET)
    st.markdown(CSS + f'<div class="x brand"><div class="name">Stop Looking at my <span>Computer</span> News</div>'
                f'<div class="meta">{now:%A, %B} {now.day} · {esc(subtitle) or "Free sources, checked against each other"}'
                f'</div></div>', unsafe_allow_html=True)


def title(name: str, sub: str = "") -> None:
    sub = sub or GUIDE.get(name, ("", ""))[1]
    st.markdown(f'<div class="x"><div class="page-title">{esc(name)}</div>'
                + (f'<div class="page-sub">{esc(sub)}</div>' if sub else "") + "</div>", unsafe_allow_html=True)


def attribution(s: Story) -> str:
    who = f", {s.byline}" if s.byline and s.byline.lower() not in s.source.lower() else ""
    return f'<span class="cred">— {esc(s.source)}{esc(who)}</span>'


def card(s: Story, lead: bool = False, picture: bool = True) -> None:
    n = outlets(s)
    chip = (f'<span class="chip">Reported by {n} outlets</span>' if n > 1 else '<span class="chip one">One source</span>')
    if s.source in PAYWALLED:
        chip += '<span class="chip pay">Subscription</span>'
    pic = f'<a href="{url(s.url)}" target="_blank"><img class="img" loading="lazy" src="{url(s.image)}" alt=""></a>' \
        if picture and s.image else ""
    check = ""
    if len(s.links) > 1:
        check = '<div class="check">Check it: ' + " · ".join(
            f'<a href="{url(link)}" target="_blank">{esc(src)}</a>' for src, link in s.links) + "</div>"
    by = f"<span>By {esc(s.byline)}</span>" if s.byline and s.byline.lower() not in s.source.lower() else ""
    summary = f'<p class="sum">{esc(s.summary)}</p>' if s.summary else ""
    st.markdown(f'<div class="x card{" lead" if lead else ""}">{pic}<div class="in"><div class="meta-row">'
                f'<span class="src">{esc(s.source)}</span>{by}<span>{esc(ago(s.published))}</span>{chip}</div>'
                f'<h3><a href="{url(s.url)}" target="_blank">{esc(s.title)}</a></h3>{summary}{check}</div></div>',
                unsafe_allow_html=True)
    if s.body:
        with st.expander("Read it here"):
            paras = "".join(f"<p>{esc(p)}</p>" for p in s.body.split("\n\n"))
            st.markdown(f'<div class="x article"><div class="by">{esc(s.byline or s.source)} · {esc(s.source)}</div>{paras}'
                        f'<div class="lic">{esc(FULL_TEXT_LICENCE.get(s.source, ""))} Original: '
                        f'<a href="{url(s.url)}" target="_blank">{esc(s.source)}</a></div></div>', unsafe_allow_html=True)


def grid(stories: list[Story], cols: int = 3, pictures: bool = True) -> None:
    for i in range(0, len(stories), cols):
        row = st.columns(cols, gap="medium")
        for col, s in zip(row, stories[i:i + cols]):
            with col:
                card(s, picture=pictures)


def briefing(heading_text: str, stories: list[Story]) -> None:
    """The top stories as a numbered list: headline, how many outlets, what happened, and who reported it."""
    if not stories:
        return
    items = []
    for s in stories:
        n = outlets(s)
        chip = f' <span class="chip">{n} outlets</span>' if n > 1 else ""
        items.append(f'<li><a href="{url(s.url)}" target="_blank"><b>{esc(s.title)}</b></a>{chip}'
                     f'<div>{esc(first_sentence(s.summary, 260))} {attribution(s)}</div></li>')
    st.markdown(f'<div class="x brief"><h4>{esc(heading_text)}</h4><ol>{"".join(items)}</ol></div>', unsafe_allow_html=True)


def heading(text: str, note: str = "") -> None:
    st.markdown(f'<div class="x section-h"><h2>{esc(text)}</h2><span>{esc(note)}</span></div>', unsafe_allow_html=True)


def box(heading_text: str, lines: list[str], cls: str = "") -> None:
    if lines:
        st.markdown(f'<div class="x box {cls}"><h4>{esc(heading_text)}</h4><ul>' + "".join(f"<li>{line}</li>" for line in lines)
                    + "</ul></div>", unsafe_allow_html=True)


def linkedin() -> str:
    """The LinkedIn address: LINKEDIN_URL in the app's Secrets, or the one written here."""
    try:
        given = str(st.secrets.get("LINKEDIN_URL", ""))
    except Exception:
        given = ""
    link = given or LINKEDIN_URL
    return link if link.startswith(("https://www.linkedin.com/", "https://linkedin.com/")) else ""


LI_ICON = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 '
           '1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 '
           '2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 '
           '24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z"/></svg>')


def li_button() -> str:
    li = linkedin()
    return f'<a class="li" href="{esc(li)}" target="_blank" rel="noopener">{LI_ICON}LinkedIn</a>' if li else ""


def footer(e: Edition | None = None) -> None:
    src = f" Sources today: {esc(', '.join(e.sources))}." if e else ""
    who = f'<div class="who"><span><b>{esc(NAME)}</b> · put together by {esc(AUTHOR)}</span>{li_button()}</div>'
    st.markdown(f'<div class="x foot">{who}Headlines, summaries and pictures belong to their publishers, and every summary '
                f'names its outlet and links to the original; "Reported by" counts the separate outlets carrying the same '
                f'story, each one linked. Stories about violence, crime and arrests are left out on purpose.{src} Nothing here '
                f'is written or rewritten by AI. A personal reading page, not a product or service.</div>',
                unsafe_allow_html=True)


def go_to(page: str, label: str) -> None:
    if page in PAGES:
        st.page_link(PAGES[page], label=label, icon=":material/arrow_forward:")


def guide() -> None:
    """Every page, what it has, and a button to it."""
    if not PAGES:
        return
    heading("Find your way around", "Every page is also in the blue bar at the top")
    names = [n for n in GUIDE if n != "Front page"]
    for i in range(0, len(names), 5):
        cols = st.columns(5, gap="small")
        for col, name in zip(cols, names[i:i + 5]):
            key = {"Sports": "sports", "Markets": "markets"}.get(name, name)
            with col:
                if key in PAGES:
                    st.page_link(PAGES[key], label=name, icon=GUIDE[name][0])
                st.markdown(f'<div class="x guide-d">{esc(GUIDE[name][1])}</div>', unsafe_allow_html=True)


# ---- the market findings ------------------------------------------------------------------

def _num(v, kind: str = "price") -> str:
    if v is None:
        return "—"
    cls = "up" if v > 0 else "down" if v < 0 else ""
    text = f"{v:+.2f} pts" if kind == "rate" else f"{v:+.1f}%"
    return f'<span class="{cls}">{text}</span>'


def tile(label: str, value: str, sub: str) -> str:
    return f'<div class="tile"><div class="l">{esc(label)}</div><div class="v">{value}</div><div class="s">{sub}</div></div>'


TILE_NAMES = {"S&P 500": "Stock market (S&P 500)", "Fear gauge (VIX)": "Investor fear (VIX)",
              "10-year Treasury yield": "Mortgage-rate driver (10-yr Treasury)", "Oil (WTI, $ a barrel)": "Oil, $ a barrel",
              "Dollar vs trading partners": "The dollar vs other currencies"}


def market_tiles(m: dict, names: tuple[str, ...]) -> str:
    by = {r["market"]: r for r in m["markets"]}
    plain = m.get("plain", {})
    out = []
    for name in names:
        if name == "chain":
            out.append(tile("Debt-crisis check", esc(plain.get("chain", f'{m["level"]} of 4')),
                            f'{m["level"]} of 4 warning signs on'))
        elif (r := by.get(name)):
            value = f'{r["last"]:.2f}%' if r["kind"] == "rate" else f'{r["last"]:,.2f}' if r["last"] < 100 else f'{r["last"]:,.0f}'
            sub = {"Fear gauge (VIX)": plain.get("vix"), "10-year Treasury yield": plain.get("rates")}.get(name)
            sub = esc(sub) if sub else f'{_num(r["day"], r["kind"])} on the day · {_num(r["month"], r["kind"])} this month'
            out.append(tile(TILE_NAMES.get(name, name), value, sub))
    return '<div class="tiles">' + "".join(out) + "</div>"


def findings_panel(m: dict, heading_text: str, tiles: tuple[str, ...], lines: list[str], tools: tuple[str, ...]) -> None:
    st.markdown(f'<div class="x panel"><div class="top"><b>{esc(heading_text)}</b><span>Data as of {esc(m.get("as_of", ""))}'
                f'</span></div><div class="body">{market_tiles(m, tiles) if tiles else ""}'
                + ("<ul>" + "".join(f"<li>{esc(line)}</li>" for line in lines) + "</ul>" if lines else "")
                + f'</div></div><div class="x credit">{esc(credit(*tools))}</div>', unsafe_allow_html=True)


def sectors_table(rows: list[dict]) -> str:
    rows = sorted(rows, key=lambda r: (r.get("month") is None, -(r.get("month") or 0)))
    body = "".join(
        f'<tr><td>{esc(r["market"])}<span class="fund">{esc(r.get("fund", ""))}</span></td><td>{_num(r["day"])}</td>'
        f'<td>{_num(r["month"])}</td><td>{_num(r["year"])}</td><td><div class="bar"><i style="left:{r["place_3y"]}%"></i></div></td></tr>'
        for r in rows)
    return ('<div class="tw"><table class="x t"><tr><th>Industry (fund)</th><th>Day</th><th>Month</th><th>Year</th>'
            f'<th>Where it sits in its 3-year range</th></tr>{body}</table></div>')


def coming_up(m: dict | None, n: int = 9) -> None:
    """The weeks ahead: Fed decisions, big economic reports, market holidays, the biggest companies' earnings."""
    events = (m or {}).get("calendar") or []
    today = datetime.now(ET).date().isoformat()
    events = [e for e in events if e["date"] >= today]
    if not events:
        return
    firsts = [e for e in events if e["kind"] != "Earnings"][:n]
    picked = sorted(firsts + [e for e in events if e["kind"] == "Earnings"][:max(n - len(firsts), 3)],
                    key=lambda e: e["date"])[:n + 3]
    lines = []
    for e in picked:
        d = datetime.fromisoformat(e["date"])
        lines.append(f'<span class="d">{d:%a, %b} {d.day}</span><span class="k k-{esc(e["kind"])}">{esc(e["kind"])}</span>'
                     f'{esc(e["what"])}')
    box("Coming up in the next few weeks", lines, cls="cal")


# ---- pages ---------------------------------------------------------------------------------

def front_page() -> None:
    e = edition()
    brand(f"Updated {e.made_at.astimezone(ET).strftime('%I:%M %p').lstrip('0')} ET")
    title("Today's edition", GUIDE["Front page"][1])
    m = markets()
    if m:
        findings_panel(m, "The economy today, in plain words", ("chain", "S&P 500", "Fear gauge (VIX)", "10-year Treasury yield"),
                       m.get("briefing", [])[:5], ("Crisis Tracker", "Market Monitor"))
    left, right = st.columns([2.1, 1], gap="large")
    with left:
        if e.lead:
            card(e.lead, lead=True)
    with right:
        coming_up(m)
        box("What to know", [esc(x) for x in e.must_know])
        social = e.sections.get("Social", [])
        box("Social, in brief", [f'<a href="{url(s.url)}" target="_blank">{esc(s.title)}</a>' for s in social])
    heading("Top stories", "Ranked by how many outlets carry them and where editors placed them")
    briefing("The briefing", e.front[:BRIEF])
    grid(e.front[BRIEF:], pictures=False)
    guide()
    for name in ("World", "Politics", "Business & markets", "Technology"):
        if e.sections.get(name):
            heading(name, "More on its own page")
            grid(e.sections[name][:3])
    footer(e)


def section_page(name: str):
    def page() -> None:
        e = edition()
        brand(name)
        stories = e.sections.get(name, [])
        sources = sorted({s.source for s in stories} | {o for s in stories for o in s.also})
        count = f" · {len(stories)} stories from {len(sources)} outlets" if stories else ""
        title(name, GUIDE.get(name, ("", ""))[1] + count)
        m = markets()
        if name == "Business & markets":
            if m:
                findings_panel(m, "Markets and industries", ("S&P 500", "10-year Treasury yield", "Oil (WTI, $ a barrel)",
                                                             "Dollar vs trading partners"),
                               [x for x in m.get("briefing", []) if x.startswith(("Stocks:", "Winners"))], ("Market Monitor",))
                if m.get("sectors"):
                    heading("Industries", "Sector funds, best month first")
                    st.markdown(sectors_table(m["sectors"]), unsafe_allow_html=True)
                    st.markdown(f'<div class="x credit">{esc(credit("Market Monitor"))}</div>', unsafe_allow_html=True)
                go_to("markets", "Every market, explained")
            else:
                no_findings()
        if name == "Science & health" and m and m.get("health"):
            findings_panel(m, "Health care in the markets", (), m["health"], ("Market Monitor",))
        if not stories:
            st.info("Nothing new here in the last two days.")
        briefing(f"{name}: the briefing", stories[:BRIEF])
        if stories[BRIEF:]:
            heading("More", "With pictures, and the full article where the publisher allows it")
            grid(stories[BRIEF:])
        footer(e)
    page.__name__ = "page_" + name.lower().replace(" & ", "_").replace(" ", "_")
    return page


# ---- sports ---------------------------------------------------------------------------------

def _when(g: sports.Game) -> str:
    start = g.start.astimezone(ET) if g.start else None
    if g.state == "pre":
        return f"{start:%a, %b} {start.day} · {start:%I:%M %p}".replace(" 0", " ") + " ET" if start else g.status
    if g.state == "in":
        return f"● Live · {g.status}"
    return f"{g.status} · {start:%a, %b} {start.day}" if start else g.status


def _soccer(g: sports.Game) -> bool:
    return sports.LEAGUES[g.league][1] == "soccer"


def game_card(g: sports.Game) -> str:
    """One game: teams with logos, scores by period, ESPN's recap, the top performers with photos."""
    a, b = (g.home, g.away) if _soccer(g) else (g.away, g.home)
    pa, pb = (g.periods[1], g.periods[0]) if g.periods and _soccer(g) else (g.periods or ([], []))
    def row(side, per):
        return (f'<div class="row{" win" if side.winner else ""}">{img(side.logo) or "<span></span>"}'
                f'<span>{esc(side.name)}<span class="rec">{esc(side.record)}</span></span>'
                f'<span class="per">{esc(" ".join(per)) if g.state != "pre" else ""}</span>'
                f'<span class="sc">{esc(side.score) if g.state != "pre" else ""}</span></div>')
    recap = ""
    if g.recap_title or g.recap:
        text = g.recap.replace("...", "…")
        recap = f'<div class="recap"><b>{esc(g.recap_title)}</b>{esc(text)} <span class="cred">— ESPN recap</span></div>'
    stars = ""
    if g.standouts and g.state != "pre":
        faces = g.faces + [""] * len(g.standouts)
        stars = '<div class="stars">' + "".join(
            f'<span class="star">{img(f) or ""}{esc(s)}</span>' for s, f in zip(g.standouts[:4], faces)) + "</div>"
    label = "Preview" if g.state == "pre" else "Box score"
    link = f'<div class="links"><a href="{url(g.link)}" target="_blank">{label} on ESPN</a></div>' if g.link else ""
    venue = f'<span class="venue">{esc(g.venue)}</span>' if g.venue else ""
    event = f'<span class="venue">{esc(g.event)}</span>' if g.event else ""
    cls = {"in": " live", "pre": " pre"}.get(g.state, "")
    return (f'<div class="x gc{cls}"><div class="top"><span class="when">{esc(_when(g))}</span>{venue}{event}</div>'
            f'{row(a, pa)}{row(b, pb)}{recap}{stars}{link}</div>')


def by_day(games: list[sports.Game]) -> str:
    """Upcoming games under a date heading for each day."""
    out, last = [], None
    for g in games:
        d = g.start.astimezone(ET).date() if g.start else None
        if d != last:
            out.append(f'<div class="x day">{d:%A, %B} {d.day}</div>' if d else '<div class="x day">Date to be set</div>')
            last = d
        out.append(game_card(g))
    return "".join(out)


def game_line(g: sports.Game) -> str:
    """One line per game for the all-sports view, with team logos and a date."""
    soccer = _soccer(g)
    logo = img(g.home.logo if soccer else g.away.logo, "tl")
    if g.state == "pre":
        a, b = (g.home, g.away) if soccer else (g.away, g.home)
        text = f'{esc(a.name)} {"v" if soccer else "at"} {esc(b.name)}'
        sub = esc(_when(g) + (" · " + g.event if g.event else ""))
    elif g.event:      # tennis: winner first, sets as 6-4 7-5
        w, l = (g.away, g.home) if g.away.winner else (g.home, g.away)
        sets = " ".join(f"{x}-{y}" for x, y in zip(w.score.split(), l.score.split()))
        text = f'<b>{esc(w.name)}</b> {"beat" if g.state == "post" else "vs"} {esc(l.name)} {esc(sets)}'
        sub = esc(("Live · " if g.state == "in" else "") + g.event)
    else:
        a, b = (g.home, g.away) if soccer else (g.away, g.home)
        name = lambda s: f"<b>{esc(s.name)}</b>" if s.winner else esc(s.name)
        text = f'{name(a)} {esc(a.score)} – {esc(b.score)} {name(b)}'
        sub = esc(_when(g))
        if g.recap_title:
            sub += f'<br><span style="color:var(--soft)">{esc(g.recap_title)}</span>'
        elif g.standouts:
            sub += " · " + esc(" · ".join(g.standouts[:2]))
    label = "preview" if g.state == "pre" else "box score"
    link = f' · <a href="{url(g.link)}" target="_blank" style="color:var(--accent)">{label}</a>' if g.link else ""
    return f'<div class="g">{logo}<div class="tx">{text}<small>{sub}{link}</small></div></div>'


def table_html(rows: list[dict]) -> str:
    if not rows:
        return ""
    cols = list(rows[0])
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{esc(r[c])}</td>" for c in cols) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="x t"><tr>{head}</tr>{body}</table></div>'


def all_sports() -> None:
    data, seen, panels = overview(), set(), []
    for name, d in data.items():
        live, done, upcoming = d["games"]
        news = [s for s in d["news"] if s.url not in seen][:3]
        seen.update(s.url for s in news)
        counts = f"{len(done)} results · {len(upcoming)} coming up" if (done or upcoming) else ""
        logo = f'<span class="lgo">{img(d.get("logo", ""))}</span>' if d.get("logo") else ""
        parts = [f'<div class="lh">{logo}<b>{esc(name)}</b><span>{esc(counts)}</span></div>']
        if live:
            parts += ['<div class="k">Live now</div>'] + [game_line(g) for g in live[:3]]
        if done:
            parts += ['<div class="k">Latest results</div>'] + [game_line(g) for g in done[:3]]
        if upcoming:
            parts += ['<div class="k">Coming up</div>'] + [game_line(g) for g in upcoming[:3]]
        if news:
            parts += ['<div class="k">The latest</div>'] + [
                f'<div class="n"><a href="{url(s.url)}" target="_blank">{esc(s.title)}</a>'
                f'<div>{esc(first_sentence(s.summary, 160))} {attribution(s)}</div></div>' for s in news]
        if len(parts) == 1:
            parts.append('<div class="g"><small>Nothing in the last two days or the week ahead.</small></div>')
        panels.append(f'<div class="x lg">{"".join(parts)}</div>')
    cols = st.columns(2, gap="medium")
    for i, p in enumerate(panels):
        with cols[i % 2]:
            st.markdown(p, unsafe_allow_html=True)


def sports_page() -> None:
    brand("Sports")
    title("Sports", GUIDE["Sports"][1] + ". Pick a league below, or see them all at once.")
    choice = st.segmented_control("League", [ALL_SPORTS, *sports.LEAGUES], default=ALL_SPORTS,
                                  label_visibility="collapsed") or ALL_SPORTS
    if choice == ALL_SPORTS:
        all_sports()
        footer()
        return
    data = league(choice)
    live, done, upcoming = data["games"]
    logo = f'<span class="lgo">{img(data.get("logo", ""))}</span>' if data.get("logo") else ""
    st.markdown(f'<div class="x banner">{logo}<div><b>{esc(choice)}</b><span>{len(live)} live · {len(done)} recent results · '
                f'{len(upcoming)} games in the week ahead</span></div></div>', unsafe_allow_html=True)
    briefing(f"{choice}: the latest", data["news"][:BRIEF])
    a, b = st.columns([1.35, 1], gap="large")
    with a:
        if live:
            heading("Live now")
            st.markdown("".join(game_card(g) for g in live), unsafe_allow_html=True)
        heading("Results", "Newest first, with ESPN's recap and the top performers")
        st.markdown("".join(game_card(g) for g in done) or '<div class="x box">No recent results.</div>', unsafe_allow_html=True)
        heading("Coming up", "The week ahead, by day (Eastern time)")
        st.markdown(by_day(upcoming) or '<div class="x box">Nothing scheduled in the week ahead.</div>', unsafe_allow_html=True)
    with b:
        if data["quotes"]:
            heading("What people said", "Word for word, with who said it")
            st.markdown("".join(f'<div class="x quote">“{esc(q)}”<a href="{url(s.url)}" target="_blank"><b>{esc(who)}</b>, '
                                f'quoted by {esc(s.source)}: {esc(s.title)}</a></div>' for q, who, s in data["quotes"]),
                        unsafe_allow_html=True)
        for group, rows in data["tables"].items():
            heading(group)
            st.markdown(table_html(rows), unsafe_allow_html=True)
    if data["news"][BRIEF:]:
        heading(f"More {choice} news")
        grid(data["news"][BRIEF:BRIEF + 6])
    footer()


def markets_page() -> None:
    brand("Markets")
    title("Markets", GUIDE["Markets"][1] + ". Public market data only: nothing about any account or trade.")
    m = markets()
    if not m:
        no_findings()
        footer()
        return
    findings_panel(m, "The economy today, in plain words", ("chain", "S&P 500", "Fear gauge (VIX)", "10-year Treasury yield"),
                   m.get("briefing", []), ("Crisis Tracker", "Market Monitor"))
    coming_up(m, n=14)
    st.markdown('<div class="x">' + "".join(f'<span class="pill{" on" if l["on"] else ""}">{esc(l["link"])}: '
                                         f'{"on" if l["on"] else "off"}</span>' for l in m["links"]) + "</div>",
                unsafe_allow_html=True)
    box("Crisis Tracker's notes", [esc(line) for line in m["summary"]])
    st.markdown(f'<div class="x credit">{esc(credit("Crisis Tracker"))}</div>', unsafe_allow_html=True)
    heading("Every market against its last three years")
    rows = "".join(
        f'<tr><td>{esc(r["market"])}</td><td>{r["last"]:,}</td><td>{_num(r["day"], r["kind"])}</td><td>{_num(r["month"], r["kind"])}</td>'
        f'<td>{_num(r["year"], r["kind"])}</td><td>{_num(r["three_years"], r["kind"])}</td>'
        f'<td><div class="bar"><i style="left:{r["place_3y"]}%"></i></div><div style="font-size:.7rem;color:var(--muted)">'
        f'{r["low_3y"]:,} to {r["high_3y"]:,}</div></td><td style="color:var(--muted);font-size:.75rem">{esc(r["as_of"])}</td></tr>'
        for r in m["markets"])
    st.markdown('<div class="tw"><table class="x t"><tr><th>Market</th><th>Latest</th><th>Day</th><th>Month</th><th>Year</th>'
                f'<th>3 years</th><th>Where it sits in its 3-year range</th><th>As of</th></tr>{rows}</table></div>'
                f'<div class="x credit">{esc(credit("Market Monitor"))}</div>', unsafe_allow_html=True)
    if m.get("sectors"):
        heading("Industries", "Sector funds, best month first")
        st.markdown(sectors_table(m["sectors"]) + f'<div class="x credit">{esc(credit("Market Monitor"))}</div>',
                    unsafe_allow_html=True)
    v = m.get("valuation")
    if v:
        heading("How expensive stocks are")
        box("Price over ten years of profits (the CAPE ratio)",
            [f"Now {v['now']}; a year ago {v['year_ago']}; three years ago {v['three_years_ago']}.",
             f"Three-year range: {v['low_3y']} to {v['high_3y']}.",
             "Higher means investors are paying more for each dollar of profit, which leaves more room to fall."])
        st.markdown(f'<div class="x credit">{esc(credit("Bubble Watch"))}</div>', unsafe_allow_html=True)
    st.caption(esc(m.get("note", "")) + f" Built {esc(m.get('made_at', ''))}.")
    footer()


# ---- the entry screen ---------------------------------------------------------------------

def password_ok() -> bool:
    """A simple lock with no settings file needed: the built-in password (press/lock.py, kept only as a one-way
    hash), or APP_PASSWORD from the app's Secrets when one is set."""
    import hmac
    import os

    if st.session_state.get("unlocked"):
        return True
    try:
        expected = str(st.secrets.get("APP_PASSWORD", "")) or os.environ.get("APP_PASSWORD", "")
    except Exception:
        expected = os.environ.get("APP_PASSWORD", "")
    now = datetime.now(ET)
    brand("Private edition")
    left, right = st.columns([1.45, 1], gap="large", vertical_alignment="center")
    with left:
        inside = (("Front page", "Top stories, the economy in plain words, and what's coming up"),
                  ("Sections", "World, Politics, Business, Technology, Science & health, Ideas, Entertainment"),
                  ("Sports", "Recaps, scores, top performers and a week of upcoming games"),
                  ("Markets", "The economy's vital signs, from tools Neiil built"))
        st.markdown(f'<div class="x hero"><div class="eyebrow">Private edition · {now:%A, %B} {now.day}</div>'
                    f'<h1>{esc(NAME)}</h1><p>The day\'s news from free sources, checked against each other, without the '
                    'grim noise, plus the economy explained in plain words.</p>'
                    '<div class="grid">' + "".join(f"<div><b>{esc(t)}</b><span>{esc(s)}</span></div>" for t, s in inside)
                    + f'</div><div class="by"><span>Put together by {esc(AUTHOR)}</span>{li_button()}</div></div>',
                    unsafe_allow_html=True)
    with right:
        with st.form("unlock", clear_on_submit=True, border=False):
            st.markdown('<div class="x signin"><div class="eyebrow">Sign in</div><div class="t">Open today\'s edition</div>'
                        '<div class="s">Enter the password. It stays open until you close the tab.</div></div>',
                        unsafe_allow_html=True)
            given = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
            if st.form_submit_button("Open today's edition", width="stretch", type="primary"):
                right_one = hmac.compare_digest(given.encode(), expected.encode()) if expected else matches(given)
                if right_one:
                    st.session_state["unlocked"] = True
                    st.session_state["pw"] = given          # opens the sealed findings; kept only for this visit
                    st.rerun()
                st.error("That's not it.")
            st.markdown('<div class="x signin"><div class="fine">Free sources only, so every link opens without a '
                        'subscription. Nothing is written or rewritten by AI.</div></div>', unsafe_allow_html=True)
    footer()
    return False


def main() -> None:
    if not password_ok():
        return
    PAGES["front"] = st.Page(front_page, title="Front page", url_path="front", default=True, icon="🗞️")
    for name in NAV_SECTIONS:
        PAGES[name] = st.Page(section_page(name), title=name, url_path=name.lower().replace(" & ", "-").replace(" ", "-"),
                              icon=GUIDE.get(name, ("", ""))[0] or None)
    PAGES["sports"] = st.Page(sports_page, title="Sports", url_path="sports", icon="🏅")
    PAGES["markets"] = st.Page(markets_page, title="Markets", url_path="markets", icon="📈")
    st.navigation(list(PAGES.values()), position="top").run()


if __name__ == "__main__":   # Streamlit runs the main file as __main__; importing it (tests) runs nothing
    main()
