"""Monitor Digest — hyper-modern black feed over the digest-aggregator Worker.

Data source: GET {WORKER_URL}/digests  (public JSON; written by the Claude
digest Routine into the aggregator-state D1). Two tabs: Daily (one post per
7am/9am/5pm ET trigger run, newest first) and Weekly (Friday syntheses).
"""

import html
import json
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
import streamlit as st

WORKER_URL = st.secrets.get(
    "WORKER_URL", "https://digest-aggregator.alatimore06370.workers.dev"
)
ET = ZoneInfo("America/New_York")

AVATARS = {"7am ET": "🌅", "9am ET": "☕", "5pm ET": "🌆", "weekly": "🧠"}
ACCENT = "#00e5a0"

st.set_page_config(
    page_title="Monitor Digest",
    page_icon="📡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&family=JetBrains+Mono:wght@400;600&display=swap');

  html, body, [data-testid="stAppViewContainer"] {
    background: #000000 !important;
    font-family: 'Inter', -apple-system, sans-serif;
  }
  [data-testid="stHeader"] { background: rgba(0,0,0,0.6); backdrop-filter: blur(12px); }
  .block-container { max-width: 680px; padding-top: 2.2rem; }

  .masthead {
    display:flex; align-items:baseline; gap:.6rem; margin-bottom:.2rem;
  }
  .masthead h1 {
    font-size: 1.55rem; font-weight: 800; letter-spacing: -0.03em;
    color: #f2f2f5; margin: 0;
  }
  .masthead .live {
    font-family:'JetBrains Mono',monospace; font-size:.68rem; color:#00e5a0;
    border:1px solid rgba(0,229,160,.35); border-radius:999px; padding:.15rem .55rem;
    background: rgba(0,229,160,.07);
  }
  .sub { color:#6b6b76; font-size:.82rem; margin-bottom: 1.1rem; }

  .stTabs [data-baseweb="tab-list"] {
    gap: .4rem; background: transparent; border-bottom: 1px solid #17171d;
  }
  .stTabs [data-baseweb="tab"] {
    color:#8a8a94; font-weight:600; font-size:.9rem; background:transparent;
  }
  .stTabs [aria-selected="true"] { color:#f2f2f5 !important; }
  .stTabs [data-baseweb="tab-highlight"] { background-color:#00e5a0 !important; }

  .post {
    border: 1px solid #17171d; border-radius: 18px;
    background: linear-gradient(180deg, #0b0b10 0%, #060608 100%);
    padding: 1.05rem 1.2rem 0.9rem; margin-bottom: 0.95rem;
    transition: border-color .15s ease;
  }
  .post:hover { border-color: #26262f; }

  .post-head { display:flex; align-items:center; gap:.6rem; margin-bottom:.55rem; }
  .avatar {
    width: 38px; height: 38px; border-radius: 12px; flex: 0 0 38px;
    display:flex; align-items:center; justify-content:center; font-size:1.15rem;
    background: #101016; border: 1px solid #1d1d25;
  }
  .handle { color:#f2f2f5; font-weight:700; font-size:.9rem; line-height:1.15; }
  .meta {
    font-family:'JetBrains Mono',monospace; font-size:.7rem; color:#5d5d68;
  }
  .headline {
    color:#e9e9ee; font-weight:700; font-size:1.02rem; letter-spacing:-0.015em;
    line-height:1.35; margin: .1rem 0 .65rem;
  }
  .wk-summary {
    color:#a9a9b4; font-size:.86rem; line-height:1.55; margin-bottom:.75rem;
    border-left: 2px solid rgba(0,229,160,.4); padding-left: .75rem;
  }

  .item { padding:.42rem 0; border-top: 1px solid #101016; }
  .item:first-of-type { border-top:none; }
  .item-line { display:flex; gap:.55rem; align-items:baseline; }
  .rank {
    font-family:'JetBrains Mono',monospace; font-size:.68rem; font-weight:600;
    color:#00e5a0; min-width:1.2rem; text-align:right; flex:0 0 auto;
  }
  .item-text { color:#c9c9d2; font-size:.865rem; line-height:1.45; }
  .value {
    font-family:'JetBrains Mono',monospace; font-size:.7rem; font-weight:600;
    color:#050505; background:#00e5a0; border-radius:6px; padding:.05rem .4rem;
    margin-left:.35rem; white-space:nowrap;
  }
  .src { margin-left:1.75rem; margin-top:.12rem; }
  .src a {
    font-family:'JetBrains Mono',monospace; font-size:.7rem; color:#4f8fff;
    text-decoration:none;
  }
  .src a:hover { text-decoration:underline; }
  .src .arrow { color:#3a3a44; margin-right:.25rem; }
  .worker-tag {
    font-family:'JetBrains Mono',monospace; font-size:.62rem; color:#5d5d68;
    margin-left:.5rem;
  }
  .empty { color:#5d5d68; text-align:center; padding:3rem 0; font-size:.9rem; }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=120, show_spinner=False)
def fetch_digests():
    r = requests.get(f"{WORKER_URL}/digests", timeout=15)
    r.raise_for_status()
    return r.json()


def fmt_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ET).strftime("%b %-d, %Y · %-I:%M %p ET")
    except Exception:
        return iso


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.replace("www.", "")
        return "via Google News" if host == "news.google.com" else host
    except Exception:
        return "source"


def render_items(items, cap=None):
    rows = []
    for it in items[: cap or len(items)]:
        rank = it.get("rank", "")
        text = html.escape(str(it.get("text", "")))
        value = it.get("value")
        url = it.get("url")
        worker = it.get("worker")
        badge = f'<span class="value">{html.escape(str(value))}</span>' if value else ""
        tag = f'<span class="worker-tag">{html.escape(str(worker))}</span>' if worker else ""
        link = (
            f'<div class="src"><span class="arrow">↳</span>'
            f'<a href="{html.escape(str(url), quote=True)}" target="_blank">{html.escape(domain_of(str(url)))}</a>{tag}</div>'
            if url
            else f'<div class="src"><span class="arrow">↳</span><a>no link captured</a>{tag}</div>'
        )
        rows.append(
            f'<div class="item"><div class="item-line"><span class="rank">{rank}</span>'
            f'<span class="item-text">{text}{badge}</span></div>{link}</div>'
        )
    return "".join(rows)


def daily_card(post):
    label = post.get("trigger_label") or "digest"
    avatar = AVATARS.get(label, "📡")
    return (
        f'<div class="post">'
        f'<div class="post-head"><div class="avatar">{avatar}</div>'
        f'<div><div class="handle">@monitor-digest</div>'
        f'<div class="meta">{html.escape(label)} · {fmt_time(post.get("posted_at", ""))}</div></div></div>'
        f'<div class="headline">{html.escape(post.get("headline") or "")}</div>'
        f'{render_items(post.get("items", []))}'
        f"</div>"
    )


def weekly_card(post):
    week_of = post.get("week_of") or ""
    summary = html.escape(post.get("summary") or "")
    return (
        f'<div class="post">'
        f'<div class="post-head"><div class="avatar">{AVATARS["weekly"]}</div>'
        f'<div><div class="handle">@monitor-digest · weekly synthesis</div>'
        f'<div class="meta">week of {html.escape(week_of)} · {fmt_time(post.get("posted_at", ""))}</div></div></div>'
        f'<div class="headline">{html.escape(post.get("headline") or "")}</div>'
        f'<div class="wk-summary">{summary}</div>'
        f'{render_items(post.get("items", []))}'
        f"</div>"
    )


st.markdown(
    '<div class="masthead"><h1>📡 Monitor Digest</h1>'
    '<span class="live">● LIVE</span></div>'
    '<div class="sub">11 Cloudflare workers → digest-aggregator → ranked by Claude '
    "(Fable 5) at 7am · 9am · 5pm ET, synthesized Fridays 8am ET</div>",
    unsafe_allow_html=True,
)

try:
    data = fetch_digests()
except Exception as e:
    st.markdown(
        f'<div class="empty">Could not reach the aggregator.<br/>'
        f"<code>{html.escape(str(e))}</code></div>",
        unsafe_allow_html=True,
    )
    st.stop()

tab_daily, tab_weekly = st.tabs(["⚡ Daily", "🗞 Weekly"])

with tab_daily:
    daily = data.get("daily", [])
    if not daily:
        st.markdown('<div class="empty">No digest posts yet — the next trigger will populate this feed.</div>', unsafe_allow_html=True)
    for post in daily:
        st.markdown(daily_card(post), unsafe_allow_html=True)

with tab_weekly:
    weekly = data.get("weekly", [])
    if not weekly:
        st.markdown('<div class="empty">First weekly synthesis lands Friday 8:00am ET.</div>', unsafe_allow_html=True)
    for post in weekly:
        st.markdown(weekly_card(post), unsafe_allow_html=True)

st.markdown(
    f'<div class="sub" style="margin-top:1.5rem;text-align:center">'
    f'refreshes every 2 min · <a style="color:#4f8fff;text-decoration:none" '
    f'href="{WORKER_URL}/digests" target="_blank">raw JSON</a></div>',
    unsafe_allow_html=True,
)
