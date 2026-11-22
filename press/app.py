# © 2026 Neiil Apshankar. All rights reserved. Personal project — not an app, platform, or business. See NOTICE.md.
"""Stop Looking at my Computer News: the day's news as a newspaper front page.

Run locally:   .venv/bin/streamlit run press/app.py
Hosted:        Streamlit Community Cloud, main file streamlit_app.py (or press/app.py). Works with no
               settings at all; optional Secrets: GUARDIAN_API_KEY, NYT_API_KEY, APP_PASSWORD.
"""

from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # so `press` imports when run as a script

from press.edition import Edition, build, is_live  # noqa: E402
from press.feeds import SECTIONS, Story  # noqa: E402
from press.lock import matches  # noqa: E402

ET = ZoneInfo("America/New_York")
REFRESH_S = 45 * 60

st.set_page_config(page_title="Stop Looking at my Computer News", page_icon="🗞️", layout="wide", initial_sidebar_state="collapsed")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700;800&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=Inter:wght@500;600&display=swap');
:root { --paper:#faf7f0; --ink:#16130f; --muted:#5f584d; --rule:#d9d1c2; --accent:#9a7a2e; --navy:#1f2a44; }
.stApp, [data-testid="stAppViewContainer"] { background: var(--paper); }
[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 1180px; padding-top: 1.2rem; padding-bottom: 4rem; }
.pp, .pp p { font-family: 'Source Serif 4', Georgia, serif; color: var(--ink); }
.pp a { color: inherit; text-decoration: none; }
.pp a:hover { text-decoration: underline; text-decoration-thickness: 1px; }
.mast { text-align:center; border-bottom: 3px double var(--ink); padding-bottom: .6rem; margin-bottom: .4rem; }
.mast .dateline { font-family: Inter, sans-serif; font-size: .72rem; letter-spacing: .08em; text-transform: uppercase;
  color: var(--muted); display:flex; justify-content: space-between; border-bottom: 1px solid var(--rule);
  padding-bottom: .35rem; margin-bottom: .5rem; gap: 1rem; flex-wrap: wrap; }
.mast h1 { font-family: 'Playfair Display', Georgia, serif; font-weight: 800; font-size: clamp(1.9rem, 5vw, 3.6rem);
  letter-spacing: -.01em; margin: 0; line-height: 1; color: var(--ink); }
.mast .tag { font-style: italic; color: var(--muted); margin-top: .25rem; font-size: 1rem; }
.nav { display:flex; flex-wrap: wrap; justify-content:center; gap: .2rem 1.1rem; font-family: Inter, sans-serif;
  font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; border-bottom: 1px solid var(--ink);
  padding: .45rem 0; margin-bottom: 1.4rem; }
.nav a { color: var(--navy); }
.front { display:grid; grid-template-columns: minmax(0, 2.1fr) minmax(0, 1fr); gap: 2rem; border-bottom: 1px solid var(--rule);
  padding-bottom: 1.4rem; }
@media (max-width: 860px) { .front { grid-template-columns: 1fr; } }
.lead img { width:100%; aspect-ratio: 16/9; object-fit: cover; border: 1px solid var(--rule); }
.lead h2 { font-family: 'Playfair Display', Georgia, serif; font-size: clamp(1.7rem, 3.4vw, 2.5rem); line-height:1.08;
  margin: .6rem 0 .5rem; font-weight: 700; }
.lead p.sum { font-size: 1.12rem; line-height: 1.5; color: #2b2620; }
.kicker { font-family: Inter, sans-serif; font-size: .7rem; letter-spacing: .08em; text-transform: uppercase;
  color: var(--accent); font-weight: 600; }
.also { font-family: Inter, sans-serif; font-size: .7rem; color: var(--muted); margin-top: .35rem; }
.side h3, .sec h3 { font-family: Inter, sans-serif; font-size: .78rem; letter-spacing: .1em; text-transform: uppercase;
  color: var(--ink); border-top: 3px solid var(--ink); padding-top: .4rem; margin: 0 0 .6rem; }
.side ul { padding-left: 1rem; margin: 0 0 1.2rem; }
.side li { margin-bottom: .55rem; line-height: 1.38; font-size: .98rem; }
.side .hist li { font-size: .9rem; color: #3a342c; }
.grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(255px, 1fr)); gap: 1.3rem 1.6rem; }
.card { border-top: 1px solid var(--rule); padding-top: .7rem; }
.card img { width:100%; aspect-ratio: 3/2; object-fit: cover; margin-bottom: .5rem; border: 1px solid var(--rule); }
.card h4 { font-family: 'Playfair Display', Georgia, serif; font-size: 1.12rem; line-height: 1.22; margin: .25rem 0 .35rem;
  font-weight: 700; }
.card p { font-size: .93rem; line-height: 1.45; color: #3a342c; margin: 0; }
.card.big h4 { font-size: 1.45rem; }
.sec { margin-top: 2.2rem; scroll-margin-top: 1rem; }
.sec h3 span { color: var(--muted); font-weight: 500; letter-spacing: .04em; text-transform: none; margin-left: .5rem; }
.foot { margin-top: 3rem; border-top: 3px double var(--ink); padding-top: .8rem; font-family: Inter, sans-serif;
  font-size: .75rem; color: var(--muted); line-height: 1.6; }
</style>
"""


@st.cache_data(ttl=REFRESH_S, show_spinner="Gathering today's edition…")
def edition() -> Edition:
    return build()


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def safe_url(url: str) -> str:
    return esc(url) if url.startswith(("https://", "http://")) else "#"


def ago(s: Story, now: datetime) -> str:
    if not s.published:
        return ""
    mins = int((now - s.published).total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 1)} min ago"
    if mins < 24 * 60:
        return f"{mins // 60} h ago"
    return s.published.astimezone(ET).strftime("%b %d").replace(" 0", " ")


def kicker(s: Story, now: datetime) -> str:
    bits = [s.source] + ([ago(s, now)] if s.published else []) + (["Live"] if is_live(s) else [])
    return f'<div class="kicker">{esc(" · ".join(bits))}</div>'


def also(s: Story) -> str:
    return f'<div class="also">Also in {esc(", ".join(s.also))}</div>' if s.also else ""


def card(s: Story, now: datetime, big: bool = False, image: bool = True) -> str:
    img = f'<a href="{safe_url(s.url)}" target="_blank"><img loading="lazy" src="{safe_url(s.image)}" alt=""></a>' \
        if image and s.image else ""
    return (f'<div class="card{" big" if big else ""}">{img}{kicker(s, now)}'
            f'<h4><a href="{safe_url(s.url)}" target="_blank">{esc(s.title)}</a></h4>'
            f'<p>{esc(s.summary)}</p>{also(s)}</div>')


def anchor(name: str) -> str:
    return name.lower().replace(" & ", "-").replace(" ", "-")


def page(e: Edition) -> str:
    now = e.made_at
    local = now.astimezone(ET)
    out = [CSS, '<div class="pp">']
    out.append(f'<div class="mast"><div class="dateline"><span>{local:%A, %B} {local.day}, {local:%Y}</span>'
               f'<span>Updated {local.strftime("%I:%M %p").lstrip("0")} ET</span><span>Free sources only</span></div>'
               f'<h1>Stop Looking at my Computer News</h1><div class="tag">The day&rsquo;s news, from free public sources.</div></div>')
    out.append('<div class="nav">' + "".join(f'<a href="#{anchor(n)}">{esc(n)}</a>' for n in SECTIONS[1:]) + "</div>")
    lead = ""
    if e.lead:
        s = e.lead
        img = f'<a href="{safe_url(s.url)}" target="_blank"><img src="{safe_url(s.image)}" alt=""></a>' if s.image else ""
        lead = (f'<div class="lead">{img}{kicker(s, now)}<h2><a href="{safe_url(s.url)}" target="_blank">{esc(s.title)}</a></h2>'
                f'<p class="sum">{esc(s.summary)}</p>{also(s)}</div>')
    side = '<div class="side">'
    if e.must_know:
        side += "<h3>What to know</h3><ul>" + "".join(f"<li>{esc(m)}</li>" for m in e.must_know) + "</ul>"
    if e.history:
        side += '<h3>On this day</h3><ul class="hist">' + "".join(f"<li>{esc(h)}</li>" for h in e.history) + "</ul>"
    side += "</div>"
    out.append(f'<div class="front">{lead}{side}</div>')
    if e.front:
        out.append('<div class="sec"><h3>Top stories</h3><div class="grid">'
                   + "".join(card(s, now, image=False) for s in e.front) + "</div></div>")
    for name, stories in e.sections.items():
        if not stories:
            continue
        cells = [card(stories[0], now, big=True)] + [card(s, now, image=i < 2) for i, s in enumerate(stories[1:])]
        out.append(f'<div class="sec" id="{anchor(name)}"><h3>{esc(name)}<span>{len(stories)} stories</span></h3>'
                   f'<div class="grid">{"".join(cells)}</div></div>')
    out.append(f'<div class="foot">Headlines, summaries and pictures belong to their publishers; every story links to the '
               f'original. Sources today: {esc(", ".join(e.sources))}. Wikipedia\'s "In the news" and "On this day" '
               f'are chosen by its editors. Nothing here is written or rewritten by AI. A personal reading page, not a '
               f'product or service.</div></div>')
    return "".join(out)


def password_ok() -> bool:
    """A simple lock, with no settings file needed: the built-in password (above), or APP_PASSWORD from the
    app's Secrets when one is set."""
    import hmac
    import os

    try:
        expected = str(st.secrets.get("APP_PASSWORD", "")) or os.environ.get("APP_PASSWORD", "")
    except Exception:
        expected = os.environ.get("APP_PASSWORD", "")
    if st.session_state.get("unlocked"):
        return True
    st.markdown(CSS + '<div class="pp"><div class="mast"><h1>Stop Looking at my Computer News</h1>'
                '<div class="tag">Private reading page</div></div></div>', unsafe_allow_html=True)
    with st.form("unlock", clear_on_submit=True):
        given = st.text_input("Password", type="password")
        if st.form_submit_button("Open today's edition"):
            right = hmac.compare_digest(given.encode(), expected.encode()) if expected else matches(given)
            if right:
                st.session_state["unlocked"] = True
                st.rerun()
            st.error("That's not it.")
    return False


def main() -> None:
    if not password_ok():
        return
    with st.sidebar:
        st.markdown("**Stop Looking at my Computer News**")
        if st.button("Refresh now"):
            edition.clear()
        st.caption(f"Refreshes on its own every {REFRESH_S // 60} minutes.")
    st.markdown(page(edition()), unsafe_allow_html=True)


main()
