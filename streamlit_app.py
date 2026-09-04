"""The Physical AI Universe — tablet-first editorial feed over the digest aggregator.

Data source: GET {WORKER_URL}/digests. Daily editions are shown in the Feed,
newest first. The Rejected lane remains the audit and feedback surface for
reviewed items that did not make a digest.
"""

import html
import os
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
import streamlit as st

from dashboard_utils import (
    MIN_TIME,
    parse_time,
    pipeline_status,
    rejected_time,
    relative_time,
    sort_rejected,
)


try:
    SECRET_WORKER_URL = st.secrets.get("WORKER_URL")
except Exception:
    # Streamlit raises when no secrets file exists; local development should
    # still work with the public default or an ordinary environment variable.
    SECRET_WORKER_URL = None

WORKER_URL = str(
    SECRET_WORKER_URL
    or os.environ.get("WORKER_URL")
    or "https://digest-aggregator.alatimore06370.workers.dev"
).rstrip("/")
ET = ZoneInfo("America/New_York")

DAILY_PAGE_SIZE = 10
REJECTED_PAGE_SIZE = 50
REJECTED_FETCH_LIMIT = 500
GRADE_PANEL_DAILY = 12


st.set_page_config(
    page_title="The Physical AI Universe",
    page_icon="📡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
  :root {
    --digest-bg: #070a0f;
    --digest-surface: #0c1118;
    --digest-surface-raised: #111821;
    --digest-surface-hover: #101722;
    --digest-border: #232b36;
    --digest-border-soft: #19212b;
    --digest-text: #eef1f4;
    --digest-text-secondary: #b2b9c2;
    --digest-text-muted: #858e99;
    --digest-blue: #3182f6;
    --digest-blue-soft: rgba(49, 130, 246, 0.13);
    --digest-orange: #ff9a3d;
    --digest-orange-soft: rgba(255, 138, 31, 0.13);
    --digest-green: #3ddc84;
    --digest-amber: #f5b942;
    --digest-red: #ff5f65;
  }

  html, body {
    background: var(--digest-bg) !important;
    color: var(--digest-text);
    font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont,
      "Segoe UI", sans-serif;
  }

  [data-testid="stAppViewContainer"] {
    background:
      radial-gradient(circle at 50% -10%, rgba(49, 130, 246, .09), transparent 31rem),
      linear-gradient(180deg, #080c12 0%, var(--digest-bg) 35rem) !important;
    color: var(--digest-text);
  }

  [data-testid="stHeader"] {
    background: rgba(7, 10, 15, .8);
    backdrop-filter: blur(14px);
  }

  .block-container {
    max-width: 820px;
    padding-top: 1.25rem;
    padding-bottom: 3rem;
  }

  .digest-hero {
    margin: .35rem 0 .55rem;
    padding: 1.55rem 0 .75rem;
  }

  .digest-title {
    display: inline-block;
    color: var(--digest-text);
    font-size: clamp(2.25rem, 5vw, 2.9rem);
    font-weight: 790;
    letter-spacing: -.055em;
    line-height: 1.02;
    margin: 0;
  }

  .digest-title::after {
    content: "";
    display: block;
    width: 54px;
    height: 3px;
    margin-top: .72rem;
    border-radius: 999px;
    background: var(--digest-blue);
    box-shadow: 0 0 18px rgba(49, 130, 246, .28);
  }

  .digest-status {
    display: flex;
    align-items: center;
    gap: .42rem;
    min-height: 44px;
    color: var(--digest-text-muted);
    font-size: .78rem;
    margin: 0;
  }

  .digest-status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }

  .digest-status-dot.status-green {
    background: var(--digest-green);
    box-shadow: 0 0 0 3px rgba(61, 220, 132, .08);
  }

  .digest-status-dot.status-amber {
    background: var(--digest-amber);
    box-shadow: 0 0 0 3px rgba(245, 185, 66, .10);
  }

  .digest-status-dot.status-red {
    background: var(--digest-red);
    box-shadow: 0 0 0 3px rgba(255, 95, 101, .10);
  }

  .st-key-dashboard_view [role="radiogroup"] {
    display: flex;
    gap: .35rem;
    padding: .25rem;
    margin: .35rem 0 .8rem;
    background: var(--digest-surface);
    border: 1px solid var(--digest-border);
    border-radius: 12px;
  }

  .st-key-dashboard_view [role="radiogroup"] > label {
    flex: 1 1 0;
    justify-content: center;
    min-height: 40px;
    border-radius: 9px;
  }

  .feed-edition {
    overflow: hidden;
    margin: 0 0 .9rem;
    background: var(--digest-surface);
    border: 1px solid var(--digest-border);
    border-radius: 14px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, .18);
  }

  .feed-edition.latest-edition {
    border-top: 2px solid var(--digest-blue);
    box-shadow:
      0 -12px 38px rgba(49, 130, 246, .055),
      0 18px 40px rgba(0, 0, 0, .24);
  }

  .edition-head {
    padding: .85rem 1rem .8rem;
    background: var(--digest-surface-raised);
    border-bottom: 1px solid var(--digest-border);
  }

  .edition-kicker {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: .42rem;
    color: var(--digest-text-muted);
    font-size: .74rem;
    font-variant-numeric: tabular-nums;
  }

  .edition-label {
    color: var(--digest-text-secondary);
    font-weight: 650;
  }

  .latest-badge {
    border-radius: 999px;
    padding: .13rem .45rem;
    color: #a9cfff;
    background: var(--digest-blue-soft);
    font-size: .66rem;
    font-weight: 700;
    letter-spacing: .045em;
  }

  .edition-headline {
    color: var(--digest-text);
    font-size: 1rem;
    font-weight: 650;
    letter-spacing: -.01em;
    line-height: 1.4;
    margin-top: .5rem;
  }

  .feed-item {
    position: relative;
    display: grid;
    grid-template-columns: 40px minmax(0, 1fr);
    gap: .75rem;
    padding: .95rem 1rem;
    border-bottom: 1px solid var(--digest-border-soft);
    transition: background-color .16s ease;
  }

  .feed-item:hover { background: var(--digest-surface-hover); }
  .feed-item:last-child { border-bottom: 0; }

  .feed-item.has-value::before {
    content: "";
    position: absolute;
    inset: .8rem auto .8rem 0;
    width: 2px;
    border-radius: 0 999px 999px 0;
    background: var(--digest-orange);
    opacity: .72;
  }

  .rank-marker {
    width: 34px;
    height: 34px;
    display: grid;
    place-items: center;
    border-radius: 10px;
    color: #a9cfff;
    background: var(--digest-blue-soft);
    font-size: .78rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    transition: color .16s ease, background-color .16s ease;
  }

  .feed-item:hover .rank-marker {
    color: #c5ddff;
    background: rgba(49, 130, 246, .19);
  }

  .feed-copy { min-width: 0; }

  .feed-meta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: .35rem;
    color: var(--digest-text-muted);
    font-size: .72rem;
    line-height: 1.35;
  }

  .feed-worker { color: var(--digest-text-secondary); }

  .feed-text {
    color: #dce1e6;
    font-size: .9rem;
    line-height: 1.5;
    margin: .33rem 0 .48rem;
  }

  .value-badge {
    display: inline-flex;
    align-items: center;
    min-height: 23px;
    border-radius: 999px;
    padding: .08rem .48rem;
    color: var(--digest-orange);
    background: var(--digest-orange-soft);
    font-size: .68rem;
    font-weight: 700;
    white-space: nowrap;
  }

  .source-link {
    color: #73adff;
    font-size: .75rem;
    font-weight: 600;
    text-decoration: none;
  }

  .source-link:hover { color: #a9cfff; text-decoration: underline; }

  .empty-state {
    color: var(--digest-text-muted);
    text-align: center;
    padding: 3rem 1rem;
    font-size: .9rem;
  }

  .rejected-summary {
    color: var(--digest-text-muted);
    font-size: .78rem;
    margin: .15rem 0 .7rem;
  }

  .rejected-grader-title {
    color: var(--digest-text);
    font-size: .92rem;
    font-weight: 700;
    margin-bottom: .12rem;
  }

  .rejected-grader-copy {
    color: var(--digest-text-muted);
    font-size: .74rem;
    line-height: 1.45;
    margin-bottom: .35rem;
  }

  .rejected-feed {
    overflow: hidden;
    background: var(--digest-surface);
    border: 1px solid var(--digest-border);
    border-radius: 14px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, .16);
  }

  .rejected-item {
    display: grid;
    grid-template-columns: 58px minmax(0, 1fr);
    gap: .75rem;
    padding: .9rem 1rem;
    border-bottom: 1px solid var(--digest-border-soft);
    transition: background-color .16s ease;
  }

  .rejected-item:hover { background: var(--digest-surface-hover); }
  .rejected-item:last-child { border-bottom: 0; }

  .rejected-id {
    align-self: start;
    border-radius: 8px;
    padding: .23rem .35rem;
    color: var(--digest-text-secondary);
    background: var(--digest-surface-raised);
    border: 1px solid var(--digest-border);
    font-size: .69rem;
    font-weight: 700;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }

  .rejected-title {
    color: #d7dce2;
    font-size: .86rem;
    line-height: 1.45;
  }

  .rejected-meta {
    color: var(--digest-text-muted);
    font-size: .69rem;
    margin-top: .28rem;
    font-variant-numeric: tabular-nums;
  }

  .rejected-signals {
    display: flex;
    flex-wrap: wrap;
    gap: .32rem;
    margin-top: .42rem;
  }

  .rejected-chip {
    border-radius: 999px;
    padding: .1rem .42rem;
    color: var(--digest-text-secondary);
    background: var(--digest-surface-raised);
    border: 1px solid var(--digest-border);
    font-size: .65rem;
    font-weight: 650;
  }

  .rejected-chip.score {
    color: #a9cfff;
    background: var(--digest-blue-soft);
    border-color: rgba(49, 130, 246, .25);
  }

  .rejected-rationale {
    margin-top: .45rem;
    padding-left: .62rem;
    border-left: 2px solid var(--digest-border);
    color: var(--digest-text-muted);
    font-size: .73rem;
    line-height: 1.5;
  }

  .rejected-rationale strong {
    color: var(--digest-text-secondary);
    font-weight: 650;
  }

  div[data-testid="stPopover"] > button,
  div[data-testid="stButton"] > button {
    min-height: 44px;
    border-color: var(--digest-border);
    border-radius: 11px;
  }

  div[data-testid="stPopover"] > button:hover,
  div[data-testid="stButton"] > button:hover {
    border-color: rgba(49, 130, 246, .55);
    color: #a9cfff;
  }

  [data-testid="stExpander"] {
    background: var(--digest-surface) !important;
    border: 1px solid var(--digest-border) !important;
    border-radius: 12px !important;
  }

  [data-testid="stWidgetLabel"] p,
  [data-testid="stCaptionContainer"] p {
    color: var(--digest-text-secondary) !important;
  }

  .digest-footer {
    margin-top: 1.5rem;
    color: var(--digest-text-muted);
    font-size: .72rem;
    text-align: center;
  }

  .digest-footer a { color: #73adff; text-decoration: none; }
  .digest-footer a:hover { text-decoration: underline; }

  @media (max-width: 900px) {
    .block-container {
      max-width: 100%;
      padding-left: 1rem;
      padding-right: 1rem;
    }
  }

  @media (max-width: 600px) {
    .block-container {
      padding-left: .7rem;
      padding-right: .7rem;
      padding-top: .85rem;
    }
    .digest-hero {
      margin-top: 0;
      padding: 1.2rem 0 .6rem;
    }
    .digest-title {
      font-size: clamp(2rem, 9vw, 2.45rem);
      line-height: 1.05;
    }
    .digest-title::after {
      width: 46px;
      margin-top: .58rem;
    }
    .edition-head { padding-inline: .8rem; }
    .feed-item {
      grid-template-columns: 35px minmax(0, 1fr);
      gap: .58rem;
      padding: .85rem .8rem;
    }
    .rank-marker { width: 31px; height: 31px; }
    .rejected-item {
      grid-template-columns: 52px minmax(0, 1fr);
      gap: .58rem;
      padding-inline: .8rem;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { scroll-behavior: auto !important; }
  }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=120, show_spinner=False)
def fetch_digests():
    response = requests.get(f"{WORKER_URL}/digests", timeout=15)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=60, show_spinner=False)
def fetch_health():
    response = requests.get(f"{WORKER_URL}/health", timeout=10)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("health response was not an object")
    return payload


@st.cache_data(ttl=120, show_spinner=False)
def fetch_rejected(days: int):
    response = requests.get(
        f"{WORKER_URL}/rejected",
        params={"days": days, "limit": REJECTED_FETCH_LIMIT},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def fmt_time(value) -> str:
    parsed = parse_time(value)
    if parsed == MIN_TIME:
        return "time unavailable" if value == MIN_TIME else str(value or "time unavailable")
    return parsed.astimezone(ET).strftime("%b %-d, %Y · %-I:%M %p ET")


def fmt_short_time(value) -> str:
    parsed = parse_time(value)
    if parsed == MIN_TIME:
        return "digest"
    return parsed.astimezone(ET).strftime("%b %-d · %-I:%M %p")


def sort_posts(posts):
    return sorted(
        posts or [],
        key=lambda post: parse_time(post.get("posted_at", "")),
        reverse=True,
    )


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.replace("www.", "")
        return "Google News" if host == "news.google.com" else host
    except Exception:
        return "source"


def item_rank_key(item):
    try:
        return int(item.get("rank"))
    except (TypeError, ValueError):
        return 10_000


def render_items(items) -> str:
    rows = []
    for item in sorted(items or [], key=item_rank_key):
        rank = html.escape(str(item.get("rank", "–")))
        text = html.escape(str(item.get("text", "")))
        value = item.get("value")
        url = item.get("url")
        worker = str(item.get("worker") or "").strip()
        domain = domain_of(str(url)) if url else ""

        metadata = []
        if worker:
            metadata.append(f'<span class="feed-worker">{html.escape(worker)}</span>')
        if domain and domain.lower() != worker.lower():
            metadata.append(f"<span>{html.escape(domain)}</span>")
        meta_html = '<span>·</span>'.join(metadata)

        badge = (
            f'<span class="value-badge">{html.escape(str(value))}</span>'
            if value
            else ""
        )
        link = (
            f'<a class="source-link" href="{html.escape(str(url), quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">Read source ↗</a>'
            if url
            else '<span class="feed-meta">No source link captured</span>'
        )

        item_class = "feed-item has-value" if value else "feed-item"
        rows.append(
            f'<article class="{item_class}">'
            f'<div class="rank-marker">{rank}</div>'
            '<div class="feed-copy">'
            f'<div class="feed-meta">{meta_html}</div>'
            f'<div class="feed-text">{text}</div>'
            f'<div class="feed-meta">{badge}{link}</div>'
            "</div></article>"
        )
    return "".join(rows)


def edition_header(post, latest=False) -> str:
    label = str(post.get("trigger_label") or "Digest")
    posted_at = str(post.get("posted_at") or "")
    item_count = len(post.get("items") or [])
    latest_html = '<span class="latest-badge">LATEST</span>' if latest else ""
    headline = str(post.get("headline") or "").strip()
    headline_html = (
        f'<div class="edition-headline">{html.escape(headline)}</div>'
        if headline
        else ""
    )
    return (
        '<div class="edition-head">'
        '<div class="edition-kicker">'
        f'{latest_html}<span class="edition-label">{html.escape(label)}</span>'
        f'<span>·</span><span>{html.escape(relative_time(posted_at))}</span>'
        f'<span>·</span><span>{html.escape(fmt_time(posted_at))}</span>'
        f'<span>·</span><span>{item_count} item{"s" if item_count != 1 else ""}</span>'
        "</div>"
        f"{headline_html}"
        "</div>"
    )


def daily_edition(post, latest=False) -> str:
    edition_class = "feed-edition latest-edition" if latest else "feed-edition"
    return (
        f'<section class="{edition_class}">'
        f"{edition_header(post, latest=latest)}"
        f'{render_items(post.get("items") or [])}'
        "</section>"
    )


def rejected_diagnostics(item) -> str:
    chips = []

    tier = item.get("tier")
    if tier not in (None, ""):
        text = str(tier).replace("_", " ").strip()
        if text:
            chips.append((text, ""))

    score = item.get("score")
    if score is not None and str(score).strip() != "":
        chips.append((f"score {score}", "score"))

    category = item.get("category")
    if category not in (None, ""):
        chips.append((str(category).replace("_", " ").strip(), ""))

    novelty = item.get("novelty")
    if novelty not in (None, ""):
        chips.append((f"novelty {str(novelty).replace('_', ' ').strip()}", ""))

    chip_html = ""
    if chips:
        chip_html = '<div class="rejected-signals">' + "".join(
            f'<span class="rejected-chip {css}">{html.escape(text)}</span>'
            for text, css in chips
            if text
        ) + "</div>"

    rationale = str(item.get("rationale") or "").strip()
    rationale_html = (
        '<div class="rejected-rationale"><strong>Model rationale</strong> · '
        f"{html.escape(rationale)}</div>"
        if rationale
        else ""
    )
    return chip_html + rationale_html


def render_rejected(items) -> str:
    rows = []
    for item in items:
        item_id = html.escape(str(item.get("id") or "–"))
        title = html.escape(str(item.get("title") or ""))
        url = item.get("canonical_url") or item.get("url")
        worker = html.escape(str(item.get("worker") or ""))
        item_time = fmt_time(rejected_time(item))
        source = (
            f'<a class="source-link" href="{html.escape(str(url), quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{html.escape(domain_of(str(url)))} ↗</a>'
            if url
            else ""
        )
        rows.append(
            '<article class="rejected-item">'
            f'<div class="rejected-id">#{item_id}</div>'
            '<div>'
            f'<div class="rejected-title">{title}</div>'
            f'<div class="rejected-meta">{worker} · {html.escape(item_time)}</div>'
            f"{rejected_diagnostics(item)}"
            f'<div class="feed-meta" style="margin-top:.42rem">{source}</div>'
            "</div></article>"
        )
    return f'<div class="rejected-feed">{"".join(rows)}</div>' if rows else ""


def handle_grade_response(response, success_message: str):
    if response.status_code == 200:
        st.success(success_message)
    elif response.status_code == 403:
        st.error("Bad PIN.")
    elif response.status_code == 404:
        st.error("That item is no longer available.")
    else:
        st.error(f"Error {response.status_code}: {response.text[:200]}")


def grade_popover(post_type, post):
    post_id = post.get("id")
    if post_id is None:
        return

    graded = int(post.get("graded") or 0)
    timestamp = fmt_short_time(str(post.get("posted_at") or ""))
    label = f"Rated {graded} · {timestamp}" if graded else f"Rate digest · {timestamp}"

    with st.popover(label):
        if not str(st.session_state.get("grader_pin", "")).strip():
            st.caption("Enter the grader PIN in Owner mode at the top of the feed.")

        for item in sorted(post.get("items") or [], key=item_rank_key):
            rank = item.get("rank")
            if rank is None:
                continue
            st.radio(
                f"{rank}. {str(item.get('text', ''))[:96]}",
                ["–", "👍", "👎"],
                horizontal=True,
                key=f"g_{post_type}_{post_id}_{rank}",
            )

        st.text_area(
            "Note to the ranking engine (optional)",
            key=f"note_{post_type}_{post_id}",
            placeholder="e.g. item 4 was noise · the Kodiak item deserved #1",
            height=80,
        )

        if st.button("Submit grades", key=f"sub_{post_type}_{post_id}", type="primary"):
            pin = str(st.session_state.get("grader_pin", "")).strip()
            if not pin:
                st.warning("Enter the grader PIN in Owner mode first.")
                return

            grades = []
            for item in post.get("items") or []:
                rank = item.get("rank")
                verdict = st.session_state.get(f"g_{post_type}_{post_id}_{rank}")
                if verdict == "👍":
                    grades.append({"rank": rank, "verdict": "up"})
                elif verdict == "👎":
                    grades.append({"rank": rank, "verdict": "down"})

            note = str(st.session_state.get(f"note_{post_type}_{post_id}", "")).strip()
            if not grades and not note:
                st.info("Nothing to submit — rate an item or write a note.")
                return

            try:
                response = requests.post(
                    f"{WORKER_URL}/grade",
                    json={
                        "pin": pin,
                        "post_type": post_type,
                        "post_id": post_id,
                        "grades": grades,
                        "note": note,
                    },
                    timeout=10,
                )
                stored = response.json().get("stored", len(grades)) if response.status_code == 200 else 0
                handle_grade_response(
                    response,
                    f"Stored {stored} — the next digest run will absorb the feedback.",
                )
            except Exception as exc:
                st.error(f"Could not reach the aggregator: {exc}")


def rejected_grading_panel(items, scope_key: str):
    item_map = {
        int(item["id"]): item
        for item in items
        if item.get("id") is not None and str(item.get("id")).isdigit()
    }
    if not item_map:
        return

    with st.container(border=True):
        st.markdown(
            '<div class="rejected-grader-title">Grade a rejected item</div>'
            '<div class="rejected-grader-copy">Choose an item from this page, '
            "confirm whether it should have ranked, and optionally explain why.</div>",
            unsafe_allow_html=True,
        )
        with st.form(f"rejected_grading_{scope_key}", border=False):
            selected_id = st.selectbox(
                "Rejected item",
                list(item_map),
                format_func=lambda item_id: (
                    f"#{item_id} · {str(item_map[item_id].get('title') or '')[:88]}"
                ),
            )
            verdict = st.radio(
                "Verdict",
                ["👍 should have ranked", "👎 correct rejection"],
                horizontal=True,
            )
            note = st.text_area(
                "Written feedback (optional)",
                height=80,
                placeholder="e.g. this major partnership should have ranked",
            )

            submitted = st.form_submit_button("Submit grade", type="primary")
            if submitted:
                pin = str(st.session_state.get("grader_pin", "")).strip()
                if not pin:
                    st.warning("Enter the grader PIN in Owner mode first.")
                    return
                try:
                    response = requests.post(
                        f"{WORKER_URL}/grade",
                        json={
                            "pin": pin,
                            "post_type": "rejected",
                            "post_id": int(selected_id),
                            "verdict": "up" if verdict.startswith("👍") else "down",
                            "note": str(note).strip(),
                        },
                        timeout=10,
                    )
                    handle_grade_response(
                        response,
                        "Grade stored — the next digest run will absorb the feedback.",
                    )
                except Exception as exc:
                    st.error(f"Could not reach the aggregator: {exc}")


def load_more_button(state_key: str, total: int, step: int, label: str):
    current = min(int(st.session_state.get(state_key, step)), total)
    if current >= total:
        return
    remaining = total - current
    if st.button(f"{label} ({remaining})", key=f"button_{state_key}"):
        st.session_state[state_key] = min(current + step, total)
        st.rerun()


st.markdown(
    '<header class="digest-hero">'
    '<div class="digest-masthead"><div class="digest-title" role="heading" aria-level="1">The Physical AI Universe</div></div>'
    "</header>",
    unsafe_allow_html=True,
)

def render_owner_panel(health):
    with st.popover("Owner mode", use_container_width=True):
        st.text_input("Grader PIN", type="password", key="grader_pin")
        st.checkbox(
            "Load grading controls",
            key="grading_enabled",
            help="Off by default so digest item widgets are not built on every refresh.",
        )
        if health:
            stale = health.get("staleness") or {}
            st.caption(
                " · ".join(
                    value
                    for value in [
                        f"Schema v{health.get('schema_version')}" if health.get("schema_version") else "",
                        f"{health.get('unread')} awaiting review" if health.get("unread") is not None else "",
                        f"Last outcome: {stale.get('lastOutcome')}" if stale.get("lastOutcome") else "",
                        f"Review boundary: {stale.get('reviewBoundary')}" if stale.get("reviewBoundary") is not None else "",
                    ]
                    if value
                )
            )
        st.caption(
            "Enable grading only when needed, then use Rate digest or the "
            "Rejected grading panel to create ranking feedback."
        )


def render_feed(data):
    daily = sort_posts((data or {}).get("daily", []))
    if not daily:
        st.markdown(
            '<div class="empty-state">No digest editions yet — the next run will populate this feed.</div>',
            unsafe_allow_html=True,
        )
        return

    daily_limit = min(int(st.session_state.get("daily_limit", DAILY_PAGE_SIZE)), len(daily))
    for index, post in enumerate(daily[:daily_limit]):
        st.markdown(daily_edition(post, latest=index == 0), unsafe_allow_html=True)
        if st.session_state.get("grading_enabled") and index < GRADE_PANEL_DAILY:
            grade_popover("daily", post)
    load_more_button("daily_limit", len(daily), DAILY_PAGE_SIZE, "Load earlier digests")


def render_prefilter_kills(items):
    if not items:
        return
    with st.expander(f"Prefilter kills ({len(items)})"):
        rows = []
        for item in items:
            rows.append(
                '<article class="rejected-item">'
                f'<div class="rejected-id">#{html.escape(str(item.get("id") or "–"))}</div>'
                '<div>'
                f'<div class="rejected-title">{html.escape(str(item.get("title") or ""))}</div>'
                f'<div class="rejected-meta">{html.escape(str(item.get("worker") or ""))} · '
                f'{html.escape(str(item.get("rule") or ""))}</div>'
                "</div></article>"
            )
        st.markdown(
            f'<div class="rejected-feed">{"".join(rows)}</div>',
            unsafe_allow_html=True,
        )


def render_rejected_view():
    filter_window, filter_worker, filter_page = st.columns([1, 1.5, 1])
    with filter_window:
        days = st.selectbox(
            "Window",
            [1, 3, 7, 14],
            index=1,
            format_func=lambda value: f"{value} day{'s' if value != 1 else ''}",
        )

    try:
        rejected = fetch_rejected(days)
    except Exception as exc:
        st.markdown(
            '<div class="empty-state">Could not load rejected items.<br>'
            f"<code>{html.escape(str(exc))}</code></div>",
            unsafe_allow_html=True,
        )
        return

    raw_items = sort_rejected(rejected.get("items", []))
    rejected_items = raw_items
    workers = sorted({str(item.get("worker")) for item in raw_items if item.get("worker")})
    with filter_worker:
        selected_worker = st.selectbox("Worker", ["All workers"] + workers)
    if selected_worker != "All workers":
        rejected_items = [item for item in raw_items if item.get("worker") == selected_worker]

    page_count = max(1, (len(rejected_items) + REJECTED_PAGE_SIZE - 1) // REJECTED_PAGE_SIZE)
    with filter_page:
        page_number = st.selectbox(
            "Page",
            range(1, page_count + 1),
            format_func=lambda value: f"{value} of {page_count} loaded",
            key=f"rejected_page_{days}_{selected_worker}",
        )

    page_start = (page_number - 1) * REJECTED_PAGE_SIZE
    page_items = rejected_items[page_start : page_start + REJECTED_PAGE_SIZE]
    showing_start = page_start + 1 if page_items else 0
    showing_end = page_start + len(page_items)

    reported_total = rejected.get("total")
    total_is_authoritative = isinstance(reported_total, int) and selected_worker == "All workers"
    if total_is_authoritative:
        count_text = f"{reported_total} total"
    else:
        count_text = f"{len(rejected_items)} loaded"
    cap_note = ""
    if len(raw_items) >= REJECTED_FETCH_LIMIT and not total_is_authoritative:
        cap_note = f" · API cap reached at {REJECTED_FETCH_LIMIT}; more may exist"

    st.markdown(
        '<div class="rejected-summary">'
        f"Showing {showing_start}–{showing_end} of {count_text} rejected items · newest first"
        f"{cap_note}</div>",
        unsafe_allow_html=True,
    )

    if st.session_state.get("grading_enabled"):
        rejected_grading_panel(page_items, f"{days}_{selected_worker}_{page_number}")

    if not page_items:
        st.markdown(
            '<div class="empty-state">Nothing rejected in this loaded window.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(render_rejected(page_items), unsafe_allow_html=True)

    render_prefilter_kills(rejected.get("prefilter_kills", []))


@st.fragment(run_every=120)
def render_dashboard():
    health = None
    health_error = None
    try:
        health = fetch_health()
    except Exception as exc:
        health_error = exc

    # /health may not exist on an older aggregator. Load the digest feed only
    # in that fallback case so the status can still show useful recency.
    fallback_data = None
    latest_post = None
    if health is None:
        try:
            fallback_data = fetch_digests()
            fallback_daily = sort_posts(fallback_data.get("daily", []))
            latest_post = fallback_daily[0] if fallback_daily else None
        except Exception:
            fallback_data = None

    status = pipeline_status(health, latest_post)
    status_col, owner_col = st.columns([4.35, 1.4], vertical_alignment="center")
    with status_col:
        detail = f" · {status.detail}" if status.detail else ""
        tooltip = f' title="{html.escape(status.detail, quote=True)}"' if status.detail else ""
        st.markdown(
            f'<div class="digest-status"{tooltip}>'
            f'<span class="digest-status-dot status-{status.level}"></span>'
            f'{html.escape(status.text + detail)}</div>',
            unsafe_allow_html=True,
        )
    with owner_col:
        render_owner_panel(health)

    view = st.radio(
        "Dashboard view",
        ["Feed", "Rejected"],
        horizontal=True,
        label_visibility="collapsed",
        key="dashboard_view",
    )

    if view == "Feed":
        try:
            data = fallback_data if fallback_data is not None else fetch_digests()
        except Exception as exc:
            st.markdown(
                '<div class="empty-state">Could not reach the digest feed.<br>'
                f"<code>{html.escape(str(exc))}</code></div>",
                unsafe_allow_html=True,
            )
        else:
            render_feed(data)
    else:
        render_rejected_view()

    if health_error:
        st.caption("Pipeline health endpoint unavailable; status is based on the latest loaded digest.")

    st.markdown(
        '<div class="digest-footer">Live view refreshes every 2 min · '
        f'<a href="{html.escape(WORKER_URL, quote=True)}/health" target="_blank" rel="noopener noreferrer">pipeline health</a> · '
        f'<a href="{html.escape(WORKER_URL, quote=True)}/digests" target="_blank" rel="noopener noreferrer">raw digest JSON</a> · '
        f'<a href="{html.escape(WORKER_URL, quote=True)}/rejected" target="_blank" rel="noopener noreferrer">rejected JSON</a>'
        "</div>",
        unsafe_allow_html=True,
    )


render_dashboard()
