"""Owner grade form shared by the Feed and Rejected tabs.

One row shape for both tabs: the aggregator's POST /grades endpoint stores a
self-contained feedback row (event, title, url, worker, the owner's
score/action/reason, and a snapshot of the grader decision it disputes).
Feed items resolve their event_id client-side from the edition's items; the
Worker verifies it against the item at that rank. Nothing secret lives here:
the runtime PIN travels in the request and is never stored.
"""

import html
from typing import Any, Mapping

import requests
import streamlit as st


# Fallback vocabulary when /grades/vocabulary is unreachable; the Worker's copy
# (src/grading-schema.js) is authoritative and replaces this at runtime.
SCALE = [
    {"action": "lead", "min": 90, "max": 100, "label": "Lead item"},
    {"action": "digest", "min": 70, "max": 89, "label": "In the digest"},
    {"action": "borderline", "min": 40, "max": 69, "label": "Borderline"},
    {"action": "reject", "min": 0, "max": 39, "label": "Correct rejection"},
]
ACTIONS = ["lead", "digest", "borderline", "reject", "urgent"]
REASON_CODES = [
    "material", "rubric_priority", "primary_source", "new_information", "direct_company_signal",
    "sovereign_budget", "duplicate_coverage", "below_materiality", "low_confidence", "stale",
    "out_of_scope", "insufficient_evidence", "already_covered", "superseded", "source_quality", "roundup_member",
    "wrong_tier", "missed_ticker_link", "duplicate_handling", "wrong_action",
]
AUTO_ACTION = "auto (from score)"
DEFAULT_SCORE = 70


def action_for_score(score: int, scale=None) -> str:
    for band in scale or SCALE:
        if band["min"] <= score <= band["max"]:
            return band["action"]
    return "borderline"


def scale_caption(scale=None) -> str:
    return " · ".join(f"{b['min']}–{b['max']} {b['action']}" for b in scale or SCALE)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_vocabulary(base: str) -> dict:
    try:
        response = requests.get(f"{base}/grades/vocabulary", timeout=10)
        data = response.json() if response.status_code == 200 else {}
    except Exception:
        data = {}
    return {
        "reason_codes": list(data.get("reason_codes") or REASON_CODES),
        "actions": list(data.get("actions") or ACTIONS),
        "scale": list(data.get("scale") or SCALE),
    }


@st.cache_data(ttl=60, show_spinner=False)
def fetch_grade_context(base: str, event_ids: tuple) -> dict:
    ids = [int(i) for i in event_ids if i is not None]
    if not ids:
        return {}
    try:
        response = requests.get(
            f"{base}/grades/context", params={"event_ids": ",".join(str(i) for i in ids[:50])}, timeout=10
        )
        return dict((response.json() if response.status_code == 200 else {}).get("events") or {})
    except Exception:
        return {}


def feed_options(post: Mapping[str, Any]) -> tuple[list[dict], list[int]]:
    """Gradable items of an edition, plus the ranks that carry no event id."""
    options, ungradable = [], []
    for item in sorted(post.get("items") or [], key=lambda it: (it.get("rank") is None, it.get("rank") or 0)):
        rank = item.get("rank")
        if rank is None:
            continue
        event_id = item.get("event_id")
        if event_id is None:
            ids = item.get("event_ids")
            event_id = ids[0] if isinstance(ids, list) and len(ids) == 1 else None
        title = str(item.get("headline") or item.get("text") or "")[:96]
        if event_id is None:
            ungradable.append(int(rank))
            continue
        options.append({"label": f"{rank}. {title}", "event_id": int(event_id), "item_rank": int(rank), "title": title})
    return options, ungradable


def rejected_options(items) -> list[dict]:
    options = []
    for item in items:
        raw = item.get("id")
        if raw is None or not str(raw).isdigit():
            continue
        title = str(item.get("title") or "")[:88]
        options.append({"label": f"#{raw} · {title}", "event_id": int(raw), "item_rank": None, "title": title})
    return options


def grader_line(ctx: Mapping[str, Any] | None) -> str:
    grader = (ctx or {}).get("grader") or {}
    if not grader:
        return "Grader: no saved decision for this item"
    parts = [f"Grader: {grader.get('action') or grader.get('decision') or '–'}"]
    if grader.get("score") is not None:
        parts.append(f"score {grader['score']}")
    if grader.get("reason_code"):
        parts.append(str(grader["reason_code"]))
    count = int((ctx or {}).get("grade_count") or 0)
    if count:
        latest = (ctx or {}).get("latest_grade") or {}
        mine = f"you {latest.get('target_score')} {latest.get('target_action') or ''}".strip()
        parts.append(f"{count} prior grade{'s' if count != 1 else ''} · last {mine}")
    return " · ".join(parts)


def context_table(options: list[dict], context: Mapping[str, Any]) -> str:
    rows = []
    for option in options:
        ctx = context.get(str(option["event_id"])) or context.get(option["event_id"]) or {}
        rows.append(
            f"<div class='grade-context-row'><span class='grade-context-item'>{html.escape(option['label'])}</span>"
            f"<span class='grade-context-grader'>{html.escape(grader_line(ctx))}</span></div>"
        )
    return "<div class='grade-context'>" + "".join(rows) + "</div>" if rows else ""


def grade_widgets(key: str, options: list[dict], vocab: Mapping[str, Any]) -> None:
    """Widgets for one grade. Values are read back from session_state on submit."""
    st.selectbox("Item", options, format_func=lambda o: o["label"], key=f"gitem_{key}")
    st.slider(
        "Score", 0, 100, DEFAULT_SCORE, key=f"gscore_{key}",
        help=scale_caption(vocab.get("scale")),
    )
    st.caption(scale_caption(vocab.get("scale")))
    st.selectbox("Action", [AUTO_ACTION] + list(vocab.get("actions") or ACTIONS), key=f"gaction_{key}")
    st.selectbox("Reason code", list(vocab.get("reason_codes") or REASON_CODES), key=f"greason_{key}")
    st.radio(
        "Scope", ["item", "rule"], horizontal=True, key=f"gscope_{key}",
        help="item: this event only. rule: a principle you would apply unseen. Write it however it comes out; "
             "ChatGPT rewrites it as a universal rule and you sign it off on the Rules tab.",
    )
    st.text_area(
        "Note (optional for an item, required for a rule)", key=f"note_{key}", height=80,
        placeholder="State the principle, then the instance. Name the boundary. For a rule, your own words are fine.",
    )


def read_grade(key: str, vocab: Mapping[str, Any]) -> dict:
    option = st.session_state.get(f"gitem_{key}") or {}
    score = int(st.session_state.get(f"gscore_{key}", DEFAULT_SCORE))
    action = st.session_state.get(f"gaction_{key}", AUTO_ACTION)
    return {
        "option": option,
        "target_score": score,
        "target_action": None if action == AUTO_ACTION else action,
        "derived_action": action_for_score(score, vocab.get("scale")),
        "reason_code": st.session_state.get(f"greason_{key}"),
        "scope": st.session_state.get(f"gscope_{key}", "item"),
        "note": str(st.session_state.get(f"note_{key}", "")).strip(),
    }


def submit_grade(base: str, pin: str, payload: dict):
    return requests.post(f"{base}/grades", json=payload, headers={"X-Owner-Pin": pin}, timeout=10)


def handle_response(response) -> None:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code == 200:
        grade = body.get("grade") or {}
        draft = body.get("rule_draft_id")
        suffix = f" · draft rule #{draft} queued for ChatGPT's rewrite; sign it off on the Rules tab" if draft else ""
        st.success(f"Stored grade #{body.get('id')} · {grade.get('target_score')} {grade.get('target_action')}{suffix}")
    elif response.status_code == 403:
        st.error("Bad PIN.")
    elif response.status_code == 404:
        st.error("That item is no longer available.")
    elif response.status_code == 409:
        st.error("The edition changed under you; reload and grade again.")
    elif response.status_code in (400, 422):
        detail = "; ".join(body.get("errors") or [body.get("error") or ""]) or response.text[:200]
        st.error(detail)
    else:
        st.error(f"Error {response.status_code}: {response.text[:200]}")


def submit(base: str, post_type: str, post_id: int, key: str, vocab: Mapping[str, Any]) -> bool:
    """Validate, post and report. Returns True when a grade was stored."""
    pin = str(st.session_state.get("grader_pin", "")).strip()
    if not pin:
        st.warning("Enter the grader PIN in Owner mode first.")
        return False
    values = read_grade(key, vocab)
    option = values["option"]
    if not option:
        st.info("Choose an item to grade.")
        return False
    if values["scope"] == "rule" and len(values["note"]) < 20:
        st.info("A rule grade needs a note of at least 20 characters stating the principle.")
        return False
    payload = {
        "post_type": post_type,
        "post_id": post_id if post_type == "daily" else option["event_id"],
        "item_rank": option.get("item_rank"),
        "event_id": option["event_id"],
        "target_score": values["target_score"],
        "target_action": values["target_action"],
        "reason_code": values["reason_code"],
        "scope": values["scope"],
        "note": values["note"],
    }
    try:
        response = submit_grade(base, pin, payload)
    except Exception as exc:
        st.error(f"Could not reach the aggregator: {exc}")
        return False
    handle_response(response)
    if response.status_code == 200:
        fetch_grade_context.clear()
        return True
    return False
