"""Rules tab: pending drafts to approve, active rules with state badges, supersede.

Every read and write here goes through the aggregator's /rules endpoints with
the runtime Owner PIN in a header. Nothing is cached across sessions and no
secret is stored in this repo.
"""

import html

import requests
import streamlit as st


STATE_ORDER = ["ignored", "misapplied", "dormant", "working", None]
STATE_LABEL = {
    "working": ("working", "#2f855a"),
    "ignored": ("ignored", "#c05621"),
    "misapplied": ("misapplied", "#c53030"),
    "dormant": ("dormant", "#718096"),
    None: ("no data yet", "#4a5568"),
}


def api(base, pin, path="", payload=None, method=None):
    headers = {"X-Owner-Pin": pin}
    if payload is None and method != "POST":
        response = requests.get(f"{base}/rules{path}", headers=headers, timeout=20)
    else:
        response = requests.post(f"{base}/rules{path}", headers=headers, json=payload or {}, timeout=20)
    try:
        result = response.json()
    except ValueError:
        raise ValueError("The rules service is temporarily unavailable. Try refreshing.") from None
    if response.status_code == 403:
        raise ValueError("Bad PIN.")
    if response.status_code >= 400 or not result.get("ok"):
        raise ValueError(result.get("error") or "The change could not be completed.")
    return result


def badge(state) -> str:
    label, color = STATE_LABEL.get(state, STATE_LABEL[None])
    return (
        f'<span class="rule-badge" style="background:{color}">{html.escape(label)}</span>'
    )


def signature_text(signature) -> str:
    parts = []
    for key in ("workers", "tickers", "categories", "keywords"):
        values = (signature or {}).get(key) or []
        if values:
            parts.append(f"{key}: {', '.join(str(v) for v in values)}")
    return " · ".join(parts) or "no signature"


def parse_signature(raw: str) -> dict:
    """'workers: a, b; tickers: X' -> {workers:[a,b], tickers:[X]}."""
    signature = {}
    for chunk in str(raw or "").split(";"):
        if ":" not in chunk:
            continue
        key, values = chunk.split(":", 1)
        key = key.strip().lower()
        if key in ("workers", "tickers", "categories", "keywords"):
            signature[key] = [v.strip() for v in values.split(",") if v.strip()]
    return signature


def sort_rules(rules):
    order = {state: index for index, state in enumerate(STATE_ORDER)}
    return sorted(rules, key=lambda r: (order.get(r.get("state"), len(order)), r.get("id") or 0))


def render_drafts(base, pin, drafts):
    st.markdown(
        f'<div class="rules-section">Pending drafts · {len(drafts)}</div>',
        unsafe_allow_html=True,
    )
    if not drafts:
        st.caption("No drafts waiting. The weekly distillation proposes new ones; rule-scoped grades add them immediately.")
        return
    for draft in drafts:
        draft_id = draft.get("id")
        with st.container(border=True):
            st.markdown(
                f'<div class="rule-meta">Draft #{draft_id} · {html.escape(str(draft.get("run_id") or "owner grade"))} · '
                f'{html.escape(str(draft.get("created_at") or "")[:10])} · '
                f'sources: {", ".join(str(i) for i in draft.get("source_feedback_ids") or []) or "none"}</div>',
                unsafe_allow_html=True,
            )
            with st.form(f"draft_{draft_id}", border=False):
                text = st.text_area("Rule text", value=str(draft.get("text") or ""), key=f"draft_text_{draft_id}", height=110)
                signature = st.text_input(
                    "Signature (workers: a, b; tickers: X; keywords: k)",
                    value="; ".join(
                        f"{k}: {', '.join(v)}" for k, v in (draft.get("signature") or {}).items() if v
                    ),
                    key=f"draft_sig_{draft_id}",
                )
                approve, reject, save = st.columns(3)
                if approve.form_submit_button("Approve", type="primary"):
                    _act(base, pin, f"/drafts/{draft_id}/approve", {"text": text.strip(), "signature": parse_signature(signature)},
                         lambda r: f"Approved as {r.get('rule_id')} · {r.get('distilled')} grade(s) distilled")
                if reject.form_submit_button("Reject"):
                    _act(base, pin, f"/drafts/{draft_id}/reject", {}, lambda r: f"Draft #{draft_id} rejected")
                if save.form_submit_button("Save edit"):
                    _act(base, pin, f"/drafts/{draft_id}/edit", {"text": text.strip(), "signature": parse_signature(signature)},
                         lambda r: f"Draft #{draft_id} updated")


def _act(base, pin, path, payload, message):
    try:
        result = api(base, pin, path, payload, method="POST")
    except ValueError as exc:
        st.error(str(exc))
        return
    st.success(message(result))
    st.session_state["rules_dirty"] = True


def render_rules(base, pin, rules, include_inactive):
    st.markdown(
        f'<div class="rules-section">{"All" if include_inactive else "Active"} rules · {len(rules)}</div>',
        unsafe_allow_html=True,
    )
    rows = []
    for rule in sort_rules(rules):
        inactive = not rule.get("active")
        rows.append(
            '<div class="rule-row' + (" inactive" if inactive else "") + '">'
            f'<div class="rule-head"><span class="rule-id">{html.escape(str(rule.get("rule_id")))}</span>'
            f'{badge(rule.get("state"))}'
            + (f'<span class="rule-meta">superseded by #{rule.get("superseded_by")}</span>' if rule.get("superseded_by") else "")
            + (f'<span class="rule-meta">folded into brief {html.escape(str(rule.get("folded_into_brief_at"))[:10])}</span>' if rule.get("folded_into_brief_at") else "")
            + "</div>"
            f'<div class="rule-text">{html.escape(str(rule.get("text") or ""))}</div>'
            f'<div class="rule-meta">{html.escape(signature_text(rule.get("signature")))} · '
            f'{html.escape(str(rule.get("source") or ""))} · {html.escape(str(rule.get("created_at") or "")[:10])}</div>'
            "</div>"
        )
    st.markdown('<div class="rules-list">' + "".join(rows) + "</div>", unsafe_allow_html=True)

    active_ids = [r["rule_id"] for r in rules if r.get("active")]
    if not active_ids:
        return
    with st.expander("Supersede or deactivate a rule"):
        with st.form("rule_action", border=False):
            rule_id = st.selectbox("Rule", active_ids, key="rule_action_id")
            text = st.text_area("Replacement text (supersede only)", key="rule_action_text", height=100,
                                placeholder="State the principle, then the boundary. The old rule becomes inactive and points at the new one.")
            signature = st.text_input("Signature (workers: a, b; tickers: X; keywords: k) — sets what calibration counts as applicable", key="rule_action_signature")
            fold_version = st.text_input("Fold into brief version (e.g. 2026.10.1) — the rule is archived when that brief deploys", key="rule_action_fold")
            supersede, deactivate, set_sig, fold = st.columns(4)
            if set_sig.form_submit_button("Set signature"):
                _act(base, pin, f"/{rule_id}/signature", {"signature": parse_signature(signature)}, lambda r: f"{r.get('rule_id')} signature updated")
            if fold.form_submit_button("Fold into brief"):
                if not fold_version.strip():
                    st.info("Enter the brief version the rule was folded into.")
                else:
                    _act(base, pin, f"/{rule_id}/fold", {"brief_version": fold_version.strip()}, lambda r: f"{r.get('rule_id')} folded into {r.get('brief_version')} · archived when it deploys")
            if supersede.form_submit_button("Supersede", type="primary"):
                if len(text.strip()) < 20:
                    st.info("Replacement text needs at least 20 characters.")
                else:
                    _act(base, pin, f"/{rule_id}/supersede", {"text": text.strip()}, lambda r: f"{r.get('superseded')} superseded by {r.get('rule_id')}")
            if deactivate.form_submit_button("Deactivate"):
                _act(base, pin, f"/{rule_id}/deactivate", {}, lambda r: f"{r.get('rule_id')} deactivated")


def render_rules_view(base):
    pin = str(st.session_state.get("grader_pin", "")).strip()
    if not pin:
        st.markdown('<div class="empty-state">Open Owner mode and enter the grader PIN to manage rules.</div>', unsafe_allow_html=True)
        return
    include_inactive = st.checkbox("Show inactive and superseded rules", key="rules_include_inactive")
    try:
        drafts = api(base, pin, "/drafts?status=pending")["drafts"]
        rules = api(base, pin, "?include=inactive" if include_inactive else "")["rules"]
    except ValueError as exc:
        st.error(str(exc))
        return
    render_drafts(base, pin, drafts)
    render_rules(base, pin, rules, include_inactive)
