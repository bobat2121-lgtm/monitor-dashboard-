"""Monitor Digest — hyper-modern black feed over the digest-aggregator Worker.

Data source: GET {WORKER_URL}/digests  (public JSON; written by the Claude
digest Routine into the aggregator-state D1). Three tabs: Daily (one post per
7am/9am/5pm ET trigger run, newest first), Weekly (Friday syntheses), and a
Rejected audit lane for reviewed items that did not make the digest.
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

  .rej-id {
    font-family:'JetBrains Mono',monospace; font-size:.66rem; font-weight:600;
    color:#8a8a94; background:#101016; border:1px solid #1d1d25; border-radius:6px;
    padding:.05rem .4rem; min-width:3.2rem; text-align:center; flex:0 0 auto;
  }
  .rej-meta {
    font-family:'JetBrains Mono',monospace; font-size:.64rem; color:#5d5d68;
    margin-left:.5rem; white-space:nowrap;
  }
  .rej-signals {
    margin-left:3.75rem; margin-top:.3rem; display:flex; flex-wrap:wrap; gap:.3rem;
  }
  .rej-chip {
    font-family:'JetBrains Mono',monospace; font-size:.62rem; font-weight:600;
    color:#9b9ba7; background:#0d0d12; border:1px solid #202028; border-radius:6px;
    padding:.08rem .38rem; white-space:nowrap;
  }
  .rej-chip.score {
    color:#00e5a0; border-color:rgba(0,229,160,.28); background:rgba(0,229,160,.05);
  }
  .rej-rationale {
    margin-left:3.75rem; margin-top:.34rem; padding-left:.55rem;
    border-left:2px solid #202028; color:#858590; font-size:.76rem; line-height:1.45;
  }
  .rej-rationale strong { color:#b5b5c0; font-weight:600; }

  [data-testid="stExpander"] {
    border: 1px solid #14141a !important; border-radius: 14px !important;
    background: #07070a !important; margin-top: -0.55rem; margin-bottom: .95rem;
  }
  [data-testid="stExpander"] summary p {
    color: #6b6b76 !important; font-size: .78rem !important;
    font-family: 'JetBrains Mono', monospace;
  }
  [data-testid="stExpander"] [data-testid="stWidgetLabel"] p {
    color: #a9a9b4 !important; font-size: .8rem !important;
  }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=120, show_spinner=False)
def fetch_digests():
    r = requests.get(f"{WORKER_URL}/digests", timeout=15)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=120, show_spinner=False)
def fetch_rejected(days: int):
    r = requests.get(f"{WORKER_URL}/rejected", params={"days": days, "limit": 500}, timeout=20)
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


def rejected_diagnostics(it) -> str:
    """Compact model diagnostics for rejected items; legacy rows can be blank."""
    chips = []

    tier = it.get("tier")
    if tier not in (None, ""):
        tier_text = str(tier).replace("_", " ").strip()
        if tier_text:
            chips.append((tier_text, ""))

    score = it.get("score")
    if score is not None and str(score).strip() != "":
        chips.append((f"score {score}", "score"))

    category = it.get("category")
    if category not in (None, ""):
        chips.append((str(category).replace("_", " ").strip(), ""))

    novelty = it.get("novelty")
    if novelty not in (None, ""):
        chips.append((f"novelty {str(novelty).replace('_', ' ').strip()}", ""))

    chip_html = ""
    if chips:
        chip_html = '<div class="rej-signals">' + "".join(
            f'<span class="rej-chip {css}">{html.escape(text)}</span>'
            for text, css in chips if text
        ) + "</div>"

    rationale = str(it.get("rationale") or "").strip()
    rationale_html = (
        f'<div class="rej-rationale"><strong>model rationale</strong> · {html.escape(rationale)}</div>'
        if rationale else ""
    )
    return chip_html + rationale_html


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


# Grading: the owner thumbs items / leaves a note; the aggregator stores it in
# its feedback table and the next daily Claude run distills it into precedents
# (permanent ranking case law). PIN-gated because the page itself is public.
GRADE_PANEL_DAILY = 12   # grade panels only on the newest posts
GRADE_PANEL_WEEKLY = 8


def grade_panel(ptype, post):
    pid = post.get("id")
    if pid is None:
        return
    graded = post.get("graded") or 0
    title = "⚖ grade this post" + (f" · ✓ {graded} on file" if graded else "")
    with st.expander(title, expanded=False):
        if not str(st.session_state.get("grader_pin", "")).strip():
            st.caption("Owner grading — set the PIN in the sidebar (top-left ☰) to submit. "
                       "Grades become ranking case law at the next digest run.")
        for it in post.get("items", []):
            rank = it.get("rank")
            if rank is None:
                continue
            st.radio(
                f"{rank}. {str(it.get('text', ''))[:90]}",
                ["–", "👍", "👎"],
                horizontal=True,
                key=f"g_{ptype}_{pid}_{rank}",
            )
        st.text_area(
            "Note to the ranking engine (optional)",
            key=f"note_{ptype}_{pid}",
            placeholder="e.g. item 4 was noise · the Kodiak item deserved #1",
            height=70,
        )
        if st.button("Submit grades", key=f"sub_{ptype}_{pid}", type="primary"):
            pin = str(st.session_state.get("grader_pin", "")).strip()
            if not pin:
                st.warning("Enter the grader PIN in the sidebar first.")
                return
            grades = []
            for it in post.get("items", []):
                rank = it.get("rank")
                v = st.session_state.get(f"g_{ptype}_{pid}_{rank}")
                if v == "👍":
                    grades.append({"rank": rank, "verdict": "up"})
                elif v == "👎":
                    grades.append({"rank": rank, "verdict": "down"})
            note = str(st.session_state.get(f"note_{ptype}_{pid}", "")).strip()
            if not grades and not note:
                st.info("Nothing to submit — thumb an item or write a note.")
                return
            try:
                resp = requests.post(
                    f"{WORKER_URL}/grade",
                    json={"pin": pin, "post_type": ptype, "post_id": pid,
                          "grades": grades, "note": note},
                    timeout=10,
                )
                if resp.status_code == 200:
                    st.success(f"Stored {resp.json().get('stored', len(grades))} — "
                               "absorbed into ranking at the next digest run.")
                elif resp.status_code == 403:
                    st.error("Bad PIN.")
                else:
                    st.error(f"Error {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                st.error(f"Could not reach the aggregator: {e}")


with st.sidebar:
    st.markdown("### ⚖ Owner grading")
    st.text_input("Grader PIN", type="password", key="grader_pin")
    st.caption("With the PIN set, open “grade this post” under any recent post: "
               "👍 more like this · 👎 noise, plus an optional note. The next "
               "digest run turns grades into precedents that permanently steer "
               "the ranking.")

st.markdown(
    '<div class="masthead"><h1>📡 Monitor Digest</h1>'
    '<span class="live">● LIVE</span></div>'
    '<div class="sub">the monitor worker fleet → digest-aggregator → ranked by Claude '
    "at 7am · 9am · 5pm ET, synthesized Fridays 8am ET</div>",
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

tab_daily, tab_weekly, tab_rejected = st.tabs(["⚡ Daily", "🗞 Weekly", "🗑 Rejected"])

with tab_daily:
    daily = data.get("daily", [])
    if not daily:
        st.markdown('<div class="empty">No digest posts yet — the next trigger will populate this feed.</div>', unsafe_allow_html=True)
    for i, post in enumerate(daily):
        st.markdown(daily_card(post), unsafe_allow_html=True)
        if i < GRADE_PANEL_DAILY:
            grade_panel("daily", post)

with tab_weekly:
    weekly = data.get("weekly", [])
    if not weekly:
        st.markdown('<div class="empty">First weekly synthesis lands Friday 8:00am ET.</div>', unsafe_allow_html=True)
    for i, post in enumerate(weekly):
        st.markdown(weekly_card(post), unsafe_allow_html=True)
        if i < GRADE_PANEL_WEEKLY:
            grade_panel("weekly", post)

# Rejected audit: everything a digest cycle read and did NOT publish. The
# Routine marks chosen events status='published'; the rest land here. Flagging
# an item 👍 files owner feedback the next digest run turns into a precedent —
# the long-term lever for tuning what the digestion phase keeps.
with tab_rejected:
    days = st.selectbox("Window", [1, 3, 7, 14], index=1, format_func=lambda d: f"last {d} day{'s' if d > 1 else ''}")
    try:
        rej = fetch_rejected(days)
    except Exception as e:
        st.markdown(f'<div class="empty">Could not load rejected items.<br/><code>{html.escape(str(e))}</code></div>', unsafe_allow_html=True)
        rej = None
    if rej:
        items = rej.get("items", [])
        workers = sorted({str(it.get("worker")) for it in items if it.get("worker")})
        pick = st.selectbox("Worker", ["all"] + workers)
        if pick != "all":
            items = [it for it in items if it.get("worker") == pick]
        st.markdown(
            f'<div class="sub">{len(items)} rejected item(s) in window · model diagnostics shown when available · flag one below to teach the ranking</div>',
            unsafe_allow_html=True,
        )
        with st.expander("⚖ flag an item (owner)", expanded=False):
            st.caption("Enter the item's ID badge. 👍 = this should have ranked (becomes a precedent at the next digest run); 👎 = confirms the rejection.")
            flag_id = st.number_input("Event ID", min_value=0, step=1, key="rej_flag_id")
            flag_verdict = st.radio("Verdict", ["👍 should have ranked", "👎 correct rejection"], horizontal=True, key="rej_flag_v")
            flag_note = st.text_area("Note (optional)", key="rej_flag_note", height=70,
                                     placeholder="e.g. this Teal Drones award mattered — anything naming a covered subsidiary ranks")
            if st.button("Submit flag", type="primary", key="rej_flag_sub"):
                pin = str(st.session_state.get("grader_pin", "")).strip()
                if not pin:
                    st.warning("Enter the grader PIN in the sidebar first.")
                elif not flag_id:
                    st.info("Enter the event ID from the item's badge.")
                else:
                    try:
                        resp = requests.post(
                            f"{WORKER_URL}/grade",
                            json={"pin": pin, "post_type": "rejected", "post_id": int(flag_id),
                                  "verdict": "up" if flag_verdict.startswith("👍") else "down",
                                  "note": str(st.session_state.get("rej_flag_note", "")).strip()},
                            timeout=10,
                        )
                        if resp.status_code == 200:
                            st.success("Flag stored — absorbed into ranking at the next digest run.")
                        elif resp.status_code == 403:
                            st.error("Bad PIN.")
                        elif resp.status_code == 404:
                            st.error("No event with that ID.")
                        else:
                            st.error(f"Error {resp.status_code}: {resp.text[:200]}")
                    except Exception as e:
                        st.error(f"Could not reach the aggregator: {e}")
        if not items:
            st.markdown('<div class="empty">Nothing rejected in this window — or the first marked cycle has not run yet.</div>', unsafe_allow_html=True)
        rows = []
        for it in items[:250]:
            iid = it.get("id")
            title = html.escape(str(it.get("title") or ""))
            url_v = it.get("canonical_url") or it.get("url")
            worker_v = html.escape(str(it.get("worker") or ""))
            ts_v = html.escape(fmt_time(str(it.get("ts") or it.get("created_at") or "")))
            diagnostics = rejected_diagnostics(it)
            link = (
                f'<div class="src"><span class="arrow">↳</span>'
                f'<a href="{html.escape(str(url_v), quote=True)}" target="_blank">{html.escape(domain_of(str(url_v)))}</a></div>'
                if url_v else ""
            )
            rows.append(
                f'<div class="item"><div class="item-line"><span class="rej-id">#{iid}</span>'
                f'<span class="item-text">{title}<span class="rej-meta">{worker_v} · {ts_v}</span></span></div>'
                f'{diagnostics}{link}</div>'
            )
        if rows:
            st.markdown(f'<div class="post">{"".join(rows)}</div>', unsafe_allow_html=True)
            if len(items) > 250:
                st.caption(f"Showing newest 250 of {len(items)} — narrow the window or filter by worker.")
        kills = rej.get("prefilter_kills", [])
        if kills:
            with st.expander(f"🧹 prefilter kills ({len(kills)}) — junk dropped before the digest ever saw it"):
                for k in kills:
                    st.markdown(
                        f'<div class="item"><div class="item-line"><span class="rej-id">#{k.get("id")}</span>'
                        f'<span class="item-text">{html.escape(str(k.get("title") or ""))}'
                        f'<span class="rej-meta">{html.escape(str(k.get("worker") or ""))} · {html.escape(str(k.get("rule") or ""))}</span></span></div></div>',
                        unsafe_allow_html=True,
                    )

st.markdown(
    f'<div class="sub" style="margin-top:1.5rem;text-align:center">'
    f'refreshes every 2 min · <a style="color:#4f8fff;text-decoration:none" '
    f'href="{WORKER_URL}/digests" target="_blank">raw JSON</a> · '
    f'<a style="color:#4f8fff;text-decoration:none" '
    f'href="{WORKER_URL}/rejected" target="_blank">rejected JSON</a></div>',
    unsafe_allow_html=True,
)