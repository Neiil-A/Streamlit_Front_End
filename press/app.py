# © 2026 Neiil Apshankar. All rights reserved. Personal project — not an app, platform, or business. See NOTICE.md.
"""Stop Looking at my Computer News: the day's news, from free sources, as a modern reading page.

Pages along the top: the front page, one page per section, Sports (results, standouts, quotes, what's
next, tables) and Markets (Purified Water's public market findings, when published to a private repo).
Stories show how many outlets report them, with a link to each; where the publisher allows it, the full
article can be read right here.

Run locally:   .venv/bin/streamlit run press/app.py
Hosted:        Streamlit Community Cloud, main file streamlit_app.py (or press/app.py). Works with no
               settings; optional Secrets: GUARDIAN_API_KEY, NYT_API_KEY, APP_PASSWORD.
"""

from __future__ import annotations

import html
import json
import sys
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
LINKEDIN_URL = ""            # https://www.linkedin.com/in/<name>/  (or LINKEDIN_URL in the app's Secrets)
ET = ZoneInfo("America/New_York")
NEWS_TTL, SPORTS_TTL = 45 * 60, 10 * 60
MARKETS_FILE = ROOT / "data" / "markets.json"
NAV_SECTIONS = [s for s in SECTIONS if s not in ("Sports", "Social")]

st.set_page_config(page_title=NAME, page_icon="🗞️", layout="wide", initial_sidebar_state="collapsed")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Newsreader:opsz,wght@6..72,500;6..72,600&display=swap');
:root { --bg:#f6f6f3; --card:#ffffff; --ink:#111318; --soft:#4b5160; --muted:#8a8f9c; --line:#e7e7e2;
        --accent:#2f5bea; --good:#0f9d58; --bad:#d93025; --chip:#eef1fb; }
.stApp, [data-testid="stAppViewContainer"] { background: var(--bg); }
[data-testid="stHeader"] { background: rgba(246,246,243,.85); backdrop-filter: blur(8px); }
.block-container { max-width: 1240px; padding-top: 3.6rem; padding-bottom: 4rem; }
html, body, .x, .x p, .x li, .x td { font-family: Inter, -apple-system, Segoe UI, sans-serif; color: var(--ink); }
.x a { color: inherit; text-decoration: none; }
.x a:hover { color: var(--accent); }
.brand { display:flex; align-items: baseline; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
  padding: .2rem 0 1rem; border-bottom: 1px solid var(--line); margin-bottom: 1.4rem; }
.brand .name { font-weight: 800; letter-spacing: -.02em; font-size: clamp(1.3rem, 2.6vw, 1.9rem); }
.brand .name span { color: var(--accent); }
.brand .meta { color: var(--muted); font-size: .82rem; font-weight: 500; }
.page-title { font-weight: 800; font-size: 1.9rem; letter-spacing: -.02em; margin: 0 0 .2rem; }
.page-sub { color: var(--soft); margin: 0 0 1.2rem; font-size: .95rem; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 16px; overflow: hidden;
  box-shadow: 0 1px 2px rgba(17,19,24,.04); margin-bottom: .35rem; }
.card .img { width:100%; aspect-ratio: 16/9; object-fit: cover; display:block; background:#e9e9e4; }
.card .in { padding: .9rem 1rem 1rem; }
.lead .img { aspect-ratio: 16/8.5; }
.meta-row { display:flex; flex-wrap: wrap; gap: .35rem .5rem; align-items:center; font-size: .72rem; color: var(--muted);
  font-weight: 600; letter-spacing: .01em; margin-bottom: .45rem; }
.src { color: var(--ink); }
.chip { background: var(--chip); color: var(--accent); border-radius: 999px; padding: .12rem .5rem; font-weight: 700; }
.chip.one { background:#f3f3ef; color: var(--muted); }
.chip.pay { background:#fff4e5; color:#b26a00; }
.card h3 { font-family: Newsreader, Georgia, serif; font-weight: 600; font-size: 1.22rem; line-height: 1.25; margin: 0 0 .4rem; }
.lead h3 { font-size: clamp(1.6rem, 3vw, 2.3rem); line-height: 1.12; }
.card p.sum { color: var(--soft); font-size: .92rem; line-height: 1.5; margin: 0; }
.lead p.sum { font-size: 1.05rem; }
.check { margin-top: .6rem; font-size: .75rem; color: var(--muted); }
.check a { color: var(--accent); font-weight: 600; }
.box { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 1rem 1.1rem; margin-bottom: 1rem; }
.box h4 { font-size: .74rem; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0 0 .6rem; font-weight: 700; }
.box ul { margin: 0; padding-left: 1.05rem; } .box li { margin: 0 0 .55rem; font-size: .93rem; line-height: 1.42; }
.section-h { display:flex; justify-content: space-between; align-items: baseline; margin: 1.8rem 0 .8rem; }
.section-h h2 { font-size: 1.15rem; font-weight: 800; margin: 0; letter-spacing: -.01em; }
.section-h span { color: var(--muted); font-size: .8rem; }
.article { font-family: Newsreader, Georgia, serif; font-size: 1.08rem; line-height: 1.65; color: #1d2027; }
.article .by { font-family: Inter; font-size: .8rem; color: var(--muted); margin-bottom: .6rem; }
.article .lic { font-family: Inter; font-size: .75rem; color: var(--muted); border-top: 1px solid var(--line); padding-top: .5rem; margin-top: .8rem; }
.game { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: .75rem .9rem; margin-bottom: .7rem; }
.game .st { font-size: .72rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: .35rem; }
.game .st.live { color: var(--bad); }
.game .row { display:flex; justify-content: space-between; align-items:center; font-size: .95rem; padding: .12rem 0; }
.game .row.win { font-weight: 700; } .game .rec { color: var(--muted); font-size: .75rem; margin-left: .35rem; font-weight: 500; }
.game .sc { font-variant-numeric: tabular-nums; font-weight: 700; }
.game .stars { font-size: .78rem; color: var(--soft); margin-top: .4rem; line-height: 1.45; }
.quote { font-family: Newsreader, Georgia, serif; font-size: 1.08rem; line-height: 1.45; border-left: 3px solid var(--accent);
  padding: .1rem 0 .1rem .8rem; margin: 0 0 .9rem; }
.quote a { display:block; font-family: Inter; font-size: .74rem; color: var(--muted); margin-top: .25rem; }
table.t { width:100%; border-collapse: collapse; font-size: .88rem; background: var(--card); border-radius: 12px; overflow: hidden; }
table.t th { text-align:left; color: var(--muted); font-weight: 600; font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
  padding: .55rem .6rem; border-bottom: 1px solid var(--line); }
table.t td { padding: .5rem .6rem; border-bottom: 1px solid #f0f0ec; font-variant-numeric: tabular-nums; }
.up { color: var(--good); font-weight: 600; } .down { color: var(--bad); font-weight: 600; }
.bar { position: relative; height: 6px; background: #ececE6; border-radius: 99px; min-width: 90px; }
.bar i { position:absolute; top:-3px; width: 12px; height: 12px; border-radius: 50%; background: var(--accent); transform: translateX(-50%); }
.tiles { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: .8rem; margin-bottom: 1rem; }
.tile { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: .8rem 1rem; }
.tile .l { font-size: .72rem; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: .05em; }
.tile .v { font-size: 1.6rem; font-weight: 800; letter-spacing: -.02em; margin-top: .15rem; }
.tile .s { font-size: .78rem; color: var(--soft); }
.pill { display:inline-block; border-radius: 999px; padding: .2rem .65rem; margin: 0 .35rem .35rem 0; font-size: .8rem; font-weight: 600;
  background: #f0f0ec; color: var(--soft); }
.pill.on { background: #fde8e7; color: var(--bad); }
[data-testid="stForm"] { background: var(--card); border: 1px solid var(--line) !important; border-radius: 16px;
  padding: 1.2rem 1.2rem 1.1rem; box-shadow: 0 1px 2px rgba(17,19,24,.04); }
[data-testid="stForm"] input { font-size: 1rem; }
.lockhead { display:flex; gap: .9rem; align-items:center; margin-bottom: .9rem; }
.lockhead .mark { flex: 0 0 44px; height: 44px; border-radius: 12px; background: var(--ink); color: #fff;
  display:flex; align-items:center; justify-content:center; font-size: 1.25rem; }
.lockhead .t { font-weight: 800; font-size: 1.15rem; letter-spacing: -.01em; }
.lockhead .s { color: var(--muted); font-size: .85rem; }
.ghost { display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: .8rem; margin-top: 1rem; }
.ghost div { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: .8rem .9rem; }
.ghost b { display:block; font-size: .9rem; } .ghost span { color: var(--muted); font-size: .76rem; line-height: 1.4; }
.foot { margin-top: 2.6rem; padding-top: 1rem; border-top: 1px solid var(--line); color: var(--muted); font-size: .76rem; line-height: 1.6; }
.foot .who { display:flex; flex-wrap: wrap; align-items:center; gap: .5rem .9rem; margin-bottom: .55rem; color: var(--soft); font-size: .82rem; }
.foot .who b { color: var(--ink); }
.foot a.li { display:inline-flex; align-items:center; gap: .35rem; background: #0a66c2; color: #fff !important; border-radius: 999px;
  padding: .2rem .7rem .2rem .45rem; font-weight: 600; font-size: .78rem; }
.foot a.li:hover { background: #004182; }
.foot a.li svg { width: 14px; height: 14px; fill: #fff; }
[data-testid="stExpander"] details { border-radius: 12px; border: 1px solid var(--line); background: var(--card); }
</style>
"""


# ---- data ---------------------------------------------------------------------------------

@st.cache_data(ttl=NEWS_TTL, show_spinner="Gathering today's edition…")
def edition() -> Edition:
    return build()


@st.cache_data(ttl=SPORTS_TTL, show_spinner="Getting scores…")
def league(name: str) -> dict:
    out = {"games": ([], [], []), "tables": {}, "news": [], "quotes": []}
    try:
        out["games"] = sports.split(sports.scoreboard(name))
    except Exception:
        pass
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


def markets() -> dict | None:
    try:
        return json.loads(MARKETS_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return None


# ---- pieces ---------------------------------------------------------------------------------

def esc(text: str) -> str:
    return html.escape(str(text or ""), quote=True)


def url(link: str) -> str:
    return esc(link) if str(link).startswith(("https://", "http://")) else "#"


def ago(when: datetime | None) -> str:
    if not when:
        return ""
    mins = int((datetime.now(timezone.utc) - when).total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 1)} min ago"
    if mins < 48 * 60:
        return f"{mins // 60} h ago"
    return when.astimezone(ET).strftime("%b %d").replace(" 0", " ")


def brand(subtitle: str = "") -> None:
    now = datetime.now(ET)
    st.markdown(CSS + f'<div class="x brand"><div class="name">Stop Looking at my <span>Computer</span> News</div>'
                f'<div class="meta">{now:%A, %B} {now.day} · {subtitle or "Free sources, checked against each other"}</div></div>',
                unsafe_allow_html=True)


def card(s: Story, lead: bool = False, picture: bool = True) -> None:
    n = outlets(s)
    chip = (f'<span class="chip">Reported by {n} outlets</span>' if n > 1 else '<span class="chip one">One source</span>')
    if s.source in PAYWALLED:
        chip += '<span class="chip pay">Subscription</span>'
    img = f'<a href="{url(s.url)}" target="_blank"><img class="img" loading="lazy" src="{url(s.image)}" alt=""></a>' \
        if picture and s.image else ""
    check = ""
    if len(s.links) > 1:
        check = '<div class="check">Check it: ' + " · ".join(
            f'<a href="{url(link)}" target="_blank">{esc(src)}</a>' for src, link in s.links) + "</div>"
    st.markdown(f'<div class="x card{" lead" if lead else ""}">{img}<div class="in"><div class="meta-row">'
                f'<span class="src">{esc(s.source)}</span><span>{esc(ago(s.published))}</span>{chip}</div>'
                f'<h3><a href="{url(s.url)}" target="_blank">{esc(s.title)}</a></h3>'
                f'<p class="sum">{esc(s.summary)}</p>{check}</div></div>', unsafe_allow_html=True)
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


def heading(title: str, note: str = "") -> None:
    st.markdown(f'<div class="x section-h"><h2>{esc(title)}</h2><span>{esc(note)}</span></div>', unsafe_allow_html=True)


def box(title: str, lines: list[str]) -> None:
    if lines:
        st.markdown(f'<div class="x box"><h4>{esc(title)}</h4><ul>' + "".join(f"<li>{line}</li>" for line in lines)
                    + "</ul></div>", unsafe_allow_html=True)


def linkedin() -> str:
    """The LinkedIn address: LINKEDIN_URL in the app's Secrets, or the one written here."""
    try:
        given = str(st.secrets.get("LINKEDIN_URL", ""))
    except Exception:
        given = ""
    link = given or LINKEDIN_URL
    return link if link.startswith("https://www.linkedin.com/") or link.startswith("https://linkedin.com/") else ""


LI_ICON = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 '
           '1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 '
           '2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 '
           '24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z"/></svg>')


def footer(e: Edition | None = None) -> None:
    src = f" Sources today: {esc(', '.join(e.sources))}." if e else ""
    li = linkedin()
    who = (f'<div class="who"><span><b>{esc(NAME)}</b> · put together by {esc(AUTHOR)}</span>'
           + (f'<a class="li" href="{esc(li)}" target="_blank" rel="noopener">{LI_ICON}LinkedIn</a>' if li else "") + "</div>")
    st.markdown(f'<div class="x foot">{who}Headlines, summaries and pictures belong to their publishers, and every story links '
                f'to the original; "Reported by" counts the separate outlets carrying the same story, each one linked.'
                f'{src} Nothing here is written or rewritten by AI. A personal reading page, not a product or service.</div>',
                unsafe_allow_html=True)


# ---- pages ---------------------------------------------------------------------------------

def front_page() -> None:
    e = edition()
    brand(f"Updated {e.made_at.astimezone(ET).strftime('%I:%M %p').lstrip('0')} ET")
    left, right = st.columns([2.1, 1], gap="large")
    with left:
        if e.lead:
            card(e.lead, lead=True)
    with right:
        box("What to know", [esc(m) for m in e.must_know])
        m = markets()
        if m:
            spx = next((r for r in m["markets"] if r["market"] == "S&P 500"), None)
            lines = [esc(line) for line in m["summary"][:2]]
            if spx:
                lines.insert(0, f"S&amp;P 500 {spx['last']:,.0f} · {spx['day']:+.1f}% on the day")
            box("Markets", lines)
        social = e.sections.get("Social", [])
        box("Social, in brief", [f'<a href="{url(s.url)}" target="_blank">{esc(s.title)}</a>' for s in social])
        box("On this day", [esc(h) for h in e.history])
    heading("Top stories", "Ranked by how many outlets carry them and where editors placed them")
    grid(e.front, pictures=False)
    for name in ("World", "Politics", "Technology"):
        if e.sections.get(name):
            heading(name, "More on its own page above")
            grid(e.sections[name][:3])
    footer(e)


def section_page(name: str):
    def page() -> None:
        e = edition()
        brand(name)
        st.markdown(f'<div class="x"><div class="page-title">{esc(name)}</div></div>', unsafe_allow_html=True)
        stories = e.sections.get(name, [])
        if not stories:
            st.info("Nothing new here in the last two days.")
        grid(stories)
        footer(e)
    page.__name__ = "page_" + name.lower().replace(" & ", "_").replace(" ", "_")
    return page


def game_html(g: sports.Game) -> str:
    live = g.state == "in"
    when = g.status if g.state != "pre" else (g.start.astimezone(ET).strftime("%a %b %d · %I:%M %p ET").replace(" 0", " ")
                                              if g.start else g.status)
    def row(side):
        return (f'<div class="row{" win" if side.winner else ""}"><span>{esc(side.name)}'
                f'<span class="rec">{esc(side.record)}</span></span><span class="sc">{esc(side.score)}</span></div>')
    stars = f'<div class="stars">{" · ".join(esc(s) for s in g.standouts)}</div>' if g.standouts else ""
    title = f'<div class="st{" live" if live else ""}">{"● Live · " if live else ""}{esc(when)}' \
            f'{" · " + esc(g.event) if g.event else ""}</div>'
    link = f'<div class="stars"><a href="{url(g.link)}" target="_blank" style="color:var(--accent)">Box score</a></div>' if g.link else ""
    return f'<div class="x game">{title}{row(g.away)}{row(g.home)}{stars}{link}</div>'


def table_html(rows: list[dict]) -> str:
    if not rows:
        return ""
    cols = list(rows[0])
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{esc(r[c])}</td>" for c in cols) + "</tr>" for r in rows)
    return f'<table class="x t"><tr>{head}</tr>{body}</table>'


def sports_page() -> None:
    brand("Sports")
    st.markdown('<div class="x"><div class="page-title">Sports</div><div class="page-sub">Results and standouts, what people '
                'said, what\'s next, and the tables. Every score links to its box score.</div></div>', unsafe_allow_html=True)
    choice = st.segmented_control("League", list(sports.LEAGUES), default="NBA", label_visibility="collapsed") or "NBA"
    data = league(choice)
    live, done, upcoming = data["games"]
    a, b = st.columns([1.35, 1], gap="large")
    with a:
        if live:
            heading("Live now")
            st.markdown("".join(game_html(g) for g in live), unsafe_allow_html=True)
        heading("Results", "Newest first, with top performers")
        st.markdown("".join(game_html(g) for g in done) or '<div class="x box">No recent results.</div>', unsafe_allow_html=True)
        heading("Coming up")
        st.markdown("".join(game_html(g) for g in upcoming) or '<div class="x box">Nothing scheduled in the next few days.</div>',
                    unsafe_allow_html=True)
    with b:
        if data["quotes"]:
            heading("What people said")
            st.markdown("".join(f'<div class="x quote">“{esc(q)}”<a href="{url(s.url)}" target="_blank">{esc(s.source)} · '
                                f'{esc(s.title)}</a></div>' for q, s in data["quotes"]), unsafe_allow_html=True)
        for group, rows in data["tables"].items():
            heading(group)
            st.markdown(table_html(rows), unsafe_allow_html=True)
    if data["news"]:
        heading(f"{choice} headlines")
        grid(data["news"][:6])
    footer()


def _num(v, kind: str) -> str:
    if v is None:
        return "—"
    cls = "up" if v > 0 else "down" if v < 0 else ""
    text = f"{v:+.2f} pts" if kind == "rate" else f"{v:+.1f}%"
    return f'<span class="{cls}">{text}</span>'


def markets_page() -> None:
    brand("Markets")
    st.markdown('<div class="x"><div class="page-title">Markets</div><div class="page-sub">Purified Water\'s findings, compared '
                'with the last three years. Public market data only: nothing about any account or trade.</div></div>',
                unsafe_allow_html=True)
    m = markets()
    if not m:
        st.info("The Markets page is filled in each night by Purified Water, and only ever into a private repository. "
                "Make this app's GitHub repository private and it appears after the next nightly run.")
        footer()
        return
    on = [l["link"] for l in m["links"] if l["on"]]
    st.markdown(f'<div class="x tiles"><div class="tile"><div class="l">Credit-crisis chain</div><div class="v">{m["level"]} of 4</div>'
                f'<div class="s">links switched on, data as of {esc(m["as_of"])}</div></div>'
                + "".join(f'<div class="tile"><div class="l">{esc(r["market"])}</div><div class="v">{r["last"]:,}</div>'
                          f'<div class="s">{_num(r["day"], r["kind"])} today · {_num(r["year"], r["kind"])} in a year</div></div>'
                          for r in m["markets"][:3]) + "</div>", unsafe_allow_html=True)
    st.markdown('<div class="x">' + "".join(f'<span class="pill{" on" if l["on"] else ""}">{esc(l["link"])}: '
                                         f'{"on" if l["on"] else "off"}</span>' for l in m["links"]) + "</div>",
                unsafe_allow_html=True)
    box("What it says", [esc(line) for line in m["summary"]])
    heading("Every market against its last three years")
    rows = "".join(
        f'<tr><td>{esc(r["market"])}</td><td>{r["last"]:,}</td><td>{_num(r["day"], r["kind"])}</td><td>{_num(r["month"], r["kind"])}</td>'
        f'<td>{_num(r["year"], r["kind"])}</td><td>{_num(r["three_years"], r["kind"])}</td>'
        f'<td><div class="bar"><i style="left:{r["place_3y"]}%"></i></div><div style="font-size:.7rem;color:var(--muted)">'
        f'{r["low_3y"]:,} to {r["high_3y"]:,}</div></td><td style="color:var(--muted);font-size:.75rem">{esc(r["as_of"])}</td></tr>'
        for r in m["markets"])
    st.markdown('<table class="x t"><tr><th>Market</th><th>Latest</th><th>Day</th><th>Month</th><th>Year</th><th>3 years</th>'
                f'<th>Where it sits in its 3-year range</th><th>As of</th></tr>{rows}</table>', unsafe_allow_html=True)
    v = m.get("valuation")
    if v:
        heading("How expensive stocks are")
        box("Price over ten years of earnings (CAPE)",
            [f"Now {v['now']}; a year ago {v['year_ago']}; three years ago {v['three_years_ago']}.",
             f"Three-year range: {v['low_3y']} to {v['high_3y']}.", esc(v["what"]) + "."])
    st.caption(esc(m.get("note", "")) + f" Built {esc(m.get('made_at', ''))}.")
    footer()


# ---- the lock ---------------------------------------------------------------------------------

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
    brand("Private edition")
    left, right = st.columns([2.1, 1], gap="large")
    with left:
        st.markdown('<div class="x"><div class="page-title">Today\'s edition is ready</div><div class="page-sub">A private '
                    'reading page. Enter the password to open it.</div></div>', unsafe_allow_html=True)
        with st.form("unlock", clear_on_submit=True, border=False):
            st.markdown('<div class="x lockhead"><div class="mark">🗞️</div><div><div class="t">Sign in</div>'
                        '<div class="s">Stays open until you close the tab.</div></div></div>', unsafe_allow_html=True)
            given = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
            if st.form_submit_button("Open today's edition", width="stretch", type="primary"):
                right_one = hmac.compare_digest(given.encode(), expected.encode()) if expected else matches(given)
                if right_one:
                    st.session_state["unlocked"] = True
                    st.rerun()
                st.error("That's not it.")
        st.markdown('<div class="x ghost">' + "".join(
            f"<div><b>{esc(t)}</b><span>{esc(s)}</span></div>" for t, s in (
                ("Front page", "The day's top stories, ranked by how many outlets carry them"),
                ("Sections", "World, Politics, Business, Technology, Science, Ideas, Culture"),
                ("Sports", "Scores, top performers, quotes, what's next, tables"),
                ("Markets", "Public market data against the last three years"))) + "</div>", unsafe_allow_html=True)
    with right:
        box("How it works", ["Free sources only, so every link opens without a subscription.",
                             "Each story shows how many outlets report it, with a link to every one.",
                             "Where the publisher allows it, the full article opens right on the page.",
                             "Nothing is written or rewritten by AI."])
    footer()
    return False


def main() -> None:
    if not password_ok():
        return
    pages = [st.Page(front_page, title="Front page", url_path="front", default=True)]
    pages += [st.Page(section_page(name), title=name, url_path=name.lower().replace(" & ", "-").replace(" ", "-"))
              for name in NAV_SECTIONS]
    pages += [st.Page(sports_page, title="Sports", url_path="sports"),
              st.Page(markets_page, title="Markets", url_path="markets")]
    st.navigation(pages, position="top").run()


if __name__ == "__main__":   # Streamlit runs the main file as __main__; importing it (tests) runs nothing
    main()
