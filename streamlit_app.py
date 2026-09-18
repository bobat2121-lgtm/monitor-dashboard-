"""The Physical AI Universe — tablet-first editorial feed over the digest aggregator.

Data source: GET {WORKER_URL}/digests. Daily editions are shown in the Feed,
newest first. The Rejected lane remains the audit and feedback surface for
reviewed items that did not make a digest.
"""

import html
import os
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
import streamlit as st

from universe_view import render_universe
from rules_view import render_rules_view
from calibration_view import render_calibration_view
from grading_ui import (
    context_table,
    feed_options,
    fetch_grade_context,
    fetch_vocabulary,
    grade_widgets,
    rejected_options,
    submit as submit_grade_form,
)

from dashboard_utils import (
    MIN_TIME,
    parse_time,
    rejected_time,
    relative_time,
    sort_rejected,
)


st.set_page_config(
    page_title="The Physical AI Universe",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
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


st.markdown(
    "<style>" + Path(__file__).with_name("feed.css").read_text(encoding="utf-8") + "</style>",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=120, show_spinner=False)
def fetch_digests():
    response = requests.get(f"{WORKER_URL}/digests", timeout=15)
    response.raise_for_status()
    return response.json()


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
    local = parsed.astimezone(ET)
    return f"{local:%b} {local.day}, {local.year} · {local.hour % 12 or 12}:{local:%M %p} ET"


def fmt_short_time(value) -> str:
    parsed = parse_time(value)
    if parsed == MIN_TIME:
        return "digest"
    local = parsed.astimezone(ET)
    return f"{local:%b} {local.day} · {local.hour % 12 or 12}:{local:%M %p}"


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
        rank = html.escape(str(item.get("rank", "–")).zfill(2))
        text = html.escape(str(item.get("text", "")))
        item_headline = str(item.get("headline") or "").strip()
        value = item.get("value")
        url = item.get("url")
        worker = str(item.get("worker") or "").strip()
        domain = domain_of(str(url)) if url else ""

        metadata = []
        if domain:
            metadata.append(f'<span class="feed-worker">{html.escape(domain)}</span>')
        elif worker:
            metadata.append(f'<span class="feed-worker">{html.escape(worker.replace("-", " ").title())}</span>')
        meta_html = '<span>·</span>'.join(metadata)

        badge = (
            f'<span class="value-badge">{html.escape(str(value))}</span>'
            if value
            else ""
        )
        headline_html = (
            f'<div class="feed-item-headline">{html.escape(item_headline)}</div>'
            if item_headline
            else '<span class="feed-summary-label">Read summary</span>'
        )
        link = (
            f'<a class="source-link" href="{html.escape(str(url), quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">Open source ↗</a>'
            if url
            else '<span class="feed-meta">No source link captured</span>'
        )

        item_class = "feed-item has-value" if value else "feed-item"
        rows.append(
            f'<article class="{item_class}">'
            f'<div class="rank-marker">{rank}</div>'
            '<div class="feed-copy">'
            f'<div class="feed-meta">{meta_html}</div>'
            # Native disclosure stays in the browser and starts collapsed.
            '<details class="feed-details">'
            f'<summary class="feed-toggle">{headline_html}</summary>'
            f'<div class="feed-text">{text}</div>'
            '</details>'
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


def daily_edition(post, latest=False, grading=False) -> str:
    edition_class = "feed-edition latest-edition" if latest else "feed-edition"
    if grading:
        edition_class += " owner-edition"
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


def grading_panel(post_type, post):
    """One grade at a time for the selected item of this edition (inside its form)."""
    post_id = post.get("id")
    if post_id is None:
        return

    graded = int(post.get("graded") or 0)
    timestamp = fmt_short_time(str(post.get("posted_at") or ""))
    label = f"Graded {graded} · {timestamp}" if graded else f"Grade an item · {timestamp}"
    key = f"{post_type}_{post_id}"

    with st.container():
        st.markdown(
            f'<div class="digest-grading-title">{html.escape(label)}</div>',
            unsafe_allow_html=True,
        )
        if not str(st.session_state.get("grader_pin", "")).strip():
            st.caption("Enter the grader PIN in Owner mode at the top of the feed.")

        options, ungradable = feed_options(post)
        if ungradable:
            st.caption(
                "Not gradable with the new form (edition predates event ids): "
                + ", ".join(f"#{rank}" for rank in ungradable)
            )
        if not options:
            st.caption("Nothing in this edition can be graded.")
            return
        context = fetch_grade_context(WORKER_URL, tuple(o["event_id"] for o in options))
        st.markdown(context_table(options, context), unsafe_allow_html=True)
        vocab = fetch_vocabulary(WORKER_URL)
        grade_widgets(key, options, vocab)

        if st.form_submit_button("Submit grade", type="primary"):
            submit_grade_form(WORKER_URL, post_type, int(post_id), key, vocab)


def rejected_grading_panel(items, scope_key: str):
    options = rejected_options(items)
    if not options:
        return

    key = f"rejected_{scope_key}"
    with st.container(border=True):
        st.markdown(
            '<div class="rejected-grader-title">Grade a rejected item</div>'
            '<div class="rejected-grader-copy">Choose an item from this page, score it '
            "against the grader's decision, and name the reason.</div>",
            unsafe_allow_html=True,
        )
        context = fetch_grade_context(WORKER_URL, tuple(o["event_id"] for o in options))
        st.markdown(context_table(options, context), unsafe_allow_html=True)
        vocab = fetch_vocabulary(WORKER_URL)
        with st.form(f"rejected_grading_{scope_key}", border=False):
            grade_widgets(key, options, vocab)
            if st.form_submit_button("Submit grade", type="primary"):
                submit_grade_form(WORKER_URL, "rejected", 0, key, vocab)


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
    '<div class="digest-title" role="heading" aria-level="1" aria-label="The Physical AI Universe">'
    '<div class="brand-primary"><span class="brand-prefix">THE</span>'
    '<span class="brand-core">PHYSICAL <span class="brand-ai">AI</span></span>'
    '<span class="brand-terminal" aria-hidden="true"></span></div>'
    '<div class="brand-universe">UNIVERSE</div></div></header>',
    unsafe_allow_html=True,
)

def render_owner_panel(health):
    with st.popover("Owner", use_container_width=True):
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
            "Enable grading to rate articles below each digest in its own panel, "
            "or use the Rejected grading panel."
        )


def search_editions(daily, query):
    """Filter loaded published stories without changing their source records."""
    terms = query.casefold().split()
    if not terms:
        return daily
    matches = []
    for post in daily:
        items = [
            item for item in post.get("items") or []
            if all(term in " ".join(str(item.get(field) or "") for field in
                ("headline", "text", "worker", "url", "value")).casefold() for term in terms)
        ]
        if items:
            matches.append({**post, "items": items})
    return matches


def render_feed(data):
    daily = sort_posts((data or {}).get("daily", []))
    if not daily:
        st.markdown(
            '<div class="empty-state">No published digests yet.</div>',
            unsafe_allow_html=True,
        )
        return

    query = str(st.session_state.get("feed_search", "")).strip()
    if st.session_state.get("_previous_feed_search", "") != query:
        st.session_state["daily_limit"] = DAILY_PAGE_SIZE
        st.session_state["_previous_feed_search"] = query
    matching = search_editions(daily, query)
    daily_limit = min(int(st.session_state.get("daily_limit", DAILY_PAGE_SIZE)), len(matching))
    visible = matching[:daily_limit]
    if query:
        matched_count = sum(len(post.get("items") or []) for post in matching)
        label = f"{matched_count} search result{'s' if matched_count != 1 else ''}"
    else:
        label = ""
    if label:
        st.markdown(f'<div class="section-label">{html.escape(label)}</div>', unsafe_allow_html=True)
    if not matching:
        st.markdown(
            '<div class="empty-state">No matching stories.<br>'
            'Try another company, topic or source.</div>',
            unsafe_allow_html=True,
        )
    elif st.session_state.get("grading_enabled"):
        for index, post in enumerate(visible):
            latest = not query and index == 0
            if post.get("id") is None:
                st.markdown(daily_edition(post, latest=latest), unsafe_allow_html=True)
                continue
            # One native form encloses the edition and its feedback controls.
            # Stable digest/rank keys keep votes attached when the feed changes.
            with st.form(f"grade_daily_{post['id']}", border=False):
                st.markdown(daily_edition(post, latest=latest, grading=True), unsafe_allow_html=True)
                grading_panel("daily", post)
    else:
        editions = "".join(
            daily_edition(post, latest=not query and index == 0)
            for index, post in enumerate(visible)
        )
        st.markdown(
            '<main class="edition-stack" aria-label="Published editions">'
            + f'{editions}</main>',
            unsafe_allow_html=True,
        )
    load_more_button("daily_limit", len(matching), DAILY_PAGE_SIZE, "Load earlier digests")


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


def render_dashboard(view):
    if view == "Feed":
        try:
            data = fetch_digests()
        except Exception as exc:
            st.markdown(
                '<div class="empty-state">Could not reach the digest feed.<br>'
                f"<code>{html.escape(str(exc))}</code></div>",
                unsafe_allow_html=True,
            )
        else:
            render_feed(data)
    elif view == "Rejected":
        render_rejected_view()
    elif view == "Rules":
        render_rules_view(WORKER_URL)
    elif view == "Calibration":
        render_calibration_view(WORKER_URL)
    else:
        render_universe(WORKER_URL)



@st.fragment(run_every=120)
def render_live_dashboard(view):
    render_dashboard(view)


navigation, search_control, owner_control = st.columns([3, 1, 1], gap="small", vertical_alignment="center")
with navigation:
    view = st.radio(
        "Dashboard view", ["Feed", "Rejected", "Rules", "Calibration", "Universe"], horizontal=True,
        label_visibility="collapsed", key="dashboard_view",
    )
with search_control:
    if view == "Feed":
        with st.popover("Search", use_container_width=True):
            st.text_input("Search published stories", placeholder="Company, topic or source", key="feed_search")
with owner_control:
    render_owner_panel(None)
# Owner editing has no periodic rerun: unsaved form values remain stable.
if view in ("Universe", "Rules", "Calibration"):
    render_dashboard(view)
else:
    render_live_dashboard(view)
