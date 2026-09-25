"""Rules tab: write a rule, sign off ChatGPT's rewrite, manage active rules.

The loop: the owner writes a rule in their own words (here, or as a
rule-scoped grade); the aggregator queues it; the scheduled ChatGPT reviewer
proposes a universal rewrite after its next edition; the owner approves it,
edits it, sends it back with a note, or rejects it. Only approval activates.

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


SIGNATURE_LABEL = "Signature (workers: a, b; tickers: X; keywords: k)"
WAIT_NOTE = "ChatGPT answers after the next edition, or now if you run the rule-refiner prompt in ChatGPT."


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


def signature_value(signature) -> str:
    """The inverse of parse_signature, for prefilling a signature field."""
    return "; ".join(f"{k}: {', '.join(str(x) for x in v)}" for k, v in (signature or {}).items() if v)


def signature_is_empty(signature) -> bool:
    return not any((signature or {}).get(k) for k in ("workers", "tickers", "keywords"))


def effect_text(effect) -> str:
    parts = []
    if (effect or {}).get("min_score") is not None:
        parts.append(f"score floor {effect['min_score']}")
    if (effect or {}).get("max_score") is not None:
        parts.append(f"score ceiling {effect['max_score']}")
    return " · ".join(parts)


def effect_payload(floor, ceiling):
    """Two optional number inputs -> {min_score?, max_score?} or None."""
    effect = {}
    if floor is not None:
        effect["min_score"] = int(floor)
    if ceiling is not None:
        effect["max_score"] = int(ceiling)
    return effect or None


def effect_inputs(key: str, effect) -> tuple:
    floor_col, ceiling_col = st.columns(2)
    floor = floor_col.number_input(
        "Score floor (optional)", min_value=0, max_value=100, step=1, value=(effect or {}).get("min_score"), key=f"{key}_floor",
        help="A hard minimum for every matching item. With rule binding on, a lower score is refused unless ChatGPT waives the rule with a reason.",
    )
    ceiling = ceiling_col.number_input(
        "Score ceiling (optional)", min_value=0, max_value=100, step=1, value=(effect or {}).get("max_score"), key=f"{key}_ceiling",
        help="A hard maximum for every matching item, e.g. 39 for 'never in the digest'.",
    )
    return floor, ceiling


def draft_origin(draft) -> str:
    run_id = str(draft.get("run_id") or "")
    if run_id == "reviewer-drop":
        return f"ChatGPT proposes retiring {draft.get('target_rule_id')}"
    if draft.get("target_rule_id"):
        return f"revision of {draft['target_rule_id']}"
    if run_id == "owner":
        return "written on the Rules tab"
    if not run_id:
        return "rule-scoped grade"
    return run_id


def approved_message(result) -> str:
    if result.get("updated_in_place"):
        return f"Updated {result.get('rule_id')} in place (signature and score bounds)"
    message = f"Approved as {result.get('rule_id')}"
    if result.get("superseded"):
        message += f" · replaces {result['superseded']}"
    if result.get("distilled"):
        message += f" · {result.get('distilled')} grade(s) distilled"
    return message


def sort_rules(rules):
    order = {state: index for index, state in enumerate(STATE_ORDER)}
    return sorted(rules, key=lambda r: (order.get(r.get("state"), len(order)), r.get("id") or 0))


def render_composer(base, pin):
    st.markdown('<div class="rules-section">Write a rule</div>', unsafe_allow_html=True)
    with st.form("rule_composer", border=True):
        text = st.text_area(
            "In your own words", key="composer_text", height=100,
            placeholder="e.g. that Navy USV marketplace should have led — anything opening a program to new vendors is big",
        )
        event_id = st.number_input(
            "About item (event id, optional)", min_value=1, step=1, value=None, key="composer_event",
            help="The # on the Rejected tab. Gives ChatGPT the item your rule came from.",
        )
        st.caption("ChatGPT rewrites it as a universal rule (principle, boundary, score band, signature) for you to sign off. " + WAIT_NOTE)
        if st.form_submit_button("Send to ChatGPT for a rewrite", type="primary"):
            if len(text.strip()) < 20:
                st.info("Write at least a sentence (20 characters) so ChatGPT has something to generalize.")
            else:
                _act(base, pin, "/drafts", {"text": text.strip(), "event_id": int(event_id) if event_id else None},
                     lambda r: f"Draft #{r.get('draft_id')} {'was already queued' if r.get('duplicate') else 'queued for ChatGPT'} · {WAIT_NOTE}")


def feedback_html(draft) -> str:
    notes = [f for f in draft.get("owner_feedback") or [] if f.get("text")]
    return "".join(
        f'<div class="refine-note">Your note after round {html.escape(str(f.get("round", "")))}: {html.escape(str(f["text"]))}</div>'
        for f in notes
    )


def proposal_chips(proposal, target=None) -> str:
    chips = []
    sig = signature_text(proposal.get("signature"))
    chips.append(f'<span class="refine-chip">{html.escape(sig)}</span>')
    if effect_text(proposal.get("effect")):
        chips.append(f'<span class="refine-chip">{html.escape(effect_text(proposal["effect"]))}</span>')
    if proposal.get("supersedes") and proposal["supersedes"] != target:
        chips.append(f'<span class="refine-chip warn">would replace {html.escape(proposal["supersedes"])}</span>')
    for rule_id in proposal.get("conflicts") or []:
        chips.append(f'<span class="refine-chip warn">conflicts with {html.escape(rule_id)}</span>')
    for rule_id in proposal.get("overlaps") or []:
        chips.append(f'<span class="refine-chip">overlaps {html.escape(rule_id)}</span>')
    return '<div class="refine-chips">' + "".join(chips) + "</div>"


def is_drop(draft) -> bool:
    return (draft.get("proposal") or {}).get("action") == "drop"


def render_drop_proposal(base, pin, draft):
    """ChatGPT proposes dropping instead of rewriting; the owner decides."""
    draft_id = draft.get("id")
    proposal = draft.get("proposal") or {}
    target = draft.get("target_rule_id")
    subject = target or "this draft"
    chips = []
    if proposal.get("duplicate_of"):
        chips.append(f'<span class="refine-chip warn">covered by {html.escape(proposal["duplicate_of"])}</span>')
    for rule_id in proposal.get("conflicts") or []:
        chips.append(f'<span class="refine-chip warn">conflicts with {html.escape(rule_id)}</span>')
    for rule_id in proposal.get("overlaps") or []:
        chips.append(f'<span class="refine-chip">overlaps {html.escape(rule_id)}</span>')
    with st.container(border=True):
        st.markdown(
            f'<div class="rule-meta">Draft #{draft_id} · {html.escape(draft_origin(draft))} · '
            f'round {draft.get("refine_round") or 1} · ChatGPT proposes dropping {html.escape(subject)}</div>',
            unsafe_allow_html=True,
        )
        rule, reason = st.columns(2)
        rule.markdown(
            f'<div class="refine-label">{"The rule" if target else "Your words"}</div>'
            f'<div class="refine-owner">{html.escape(str(draft.get("raw_text") or draft.get("text") or ""))}</div>'
            + feedback_html(draft),
            unsafe_allow_html=True,
        )
        reason.markdown(
            "<div class=\"refine-label\">Why ChatGPT would drop it</div>"
            f'<div class="rule-text">{html.escape(str(proposal.get("rationale") or ""))}</div>'
            + ('<div class="refine-chips">' + "".join(chips) + "</div>" if chips else ""),
            unsafe_allow_html=True,
        )
        with st.form(f"drop_{draft_id}", border=False):
            if target:
                st.caption(f"Dropping retires {target}: it moves to inactive rules and can be reactivated. Keeping leaves it exactly as it is.")
            note = st.text_input("Or send back for a rewrite (what should the rule say?)", key=f"drop_note_{draft_id}")
            drop, keep, rewrite = st.columns(3)
            if drop.form_submit_button(f"Drop {subject}", type="primary"):
                _act(base, pin, f"/drafts/{draft_id}/drop", {},
                     lambda r: f"Dropped {r['dropped']} · reactivate it from inactive rules if needed" if r.get("dropped") else f"Draft #{draft_id} dropped")
            if keep.form_submit_button(f"Keep {subject}"):
                _act(base, pin, f"/drafts/{draft_id}/reject", {}, lambda r: f"Kept {target}, unchanged" if target else f"Draft #{draft_id} closed")
            if rewrite.form_submit_button("Rewrite instead"):
                if len(note.strip()) < 5:
                    st.info("Add a note saying what the rule should say, so the rewrite answers exactly that.")
                else:
                    _act(base, pin, f"/drafts/{draft_id}/refine", {"feedback": note.strip()}, lambda r: f"Draft #{draft_id} sent back · {WAIT_NOTE}")


def render_proposal(base, pin, draft):
    """ChatGPT's rewrite beside the owner's words, with the sign-off form."""
    if is_drop(draft):
        render_drop_proposal(base, pin, draft)
        return
    draft_id = draft.get("id")
    proposal = draft.get("proposal") or {}
    target = draft.get("target_rule_id")
    with st.container(border=True):
        st.markdown(
            f'<div class="rule-meta">Draft #{draft_id} · {html.escape(draft_origin(draft))} · '
            f'round {draft.get("refine_round") or 1} · ready to sign off</div>',
            unsafe_allow_html=True,
        )
        mine, theirs = st.columns(2)
        mine.markdown(
            '<div class="refine-label">Your words</div>'
            f'<div class="refine-owner">{html.escape(str(draft.get("raw_text") or draft.get("text") or ""))}</div>'
            + feedback_html(draft),
            unsafe_allow_html=True,
        )
        theirs.markdown(
            "<div class=\"refine-label\">ChatGPT's rule</div>"
            f'<div class="rule-text">{html.escape(str(proposal.get("text") or ""))}</div>'
            + (f'<div class="refine-note">{html.escape(str(proposal["rationale"]))}</div>' if proposal.get("rationale") else "")
            + proposal_chips(proposal, target),
            unsafe_allow_html=True,
        )
        with st.form(f"proposal_{draft_id}", border=False):
            text = st.text_area("Rule text to approve (edit if one word is off)", value=str(proposal.get("text") or ""),
                                key=f"proposal_text_{draft_id}", height=150)
            signature = st.text_input(SIGNATURE_LABEL, value=signature_value(proposal.get("signature")), key=f"proposal_sig_{draft_id}")
            floor, ceiling = effect_inputs(f"proposal_{draft_id}", proposal.get("effect"))
            replace = False
            if target:
                st.caption(f"Approving updates {target} in place when the text is unchanged, and supersedes it otherwise.")
            elif proposal.get("supersedes"):
                replace = st.checkbox(f"Replace {proposal['supersedes']} with this rule (it is superseded, history kept)", key=f"proposal_replace_{draft_id}")
            note = st.text_input("Send-back note (what did the rewrite get wrong?)", key=f"proposal_note_{draft_id}")
            approve, send_back, reject = st.columns(3)
            if approve.form_submit_button("Approve", type="primary"):
                payload = {"text": text.strip(), "signature": parse_signature(signature), "effect": effect_payload(floor, ceiling)}
                if replace:
                    payload["supersedes"] = proposal["supersedes"]
                _act(base, pin, f"/drafts/{draft_id}/approve", payload, approved_message)
            if send_back.form_submit_button("Send back to ChatGPT"):
                if len(note.strip()) < 5:
                    st.info("Add a send-back note saying what the rewrite got wrong, so the next one can fix exactly that.")
                else:
                    _act(base, pin, f"/drafts/{draft_id}/refine", {"feedback": note.strip()}, lambda r: f"Draft #{draft_id} sent back · {WAIT_NOTE}")
            if reject.form_submit_button("Reject"):
                _act(base, pin, f"/drafts/{draft_id}/reject", {}, lambda r: f"Draft #{draft_id} rejected")


def render_queued(base, pin, draft):
    """Waiting for ChatGPT: the owner's words, and a way out."""
    draft_id = draft.get("id")
    words = str(draft.get("raw_text") or draft.get("text") or "")
    with st.container(border=True):
        st.markdown(
            f'<div class="rule-meta">Draft #{draft_id} · {html.escape(draft_origin(draft))} · waiting for ChatGPT\'s rewrite · '
            f'queued {html.escape(str(draft.get("created_at") or "")[:10])}</div>'
            f'<div class="refine-owner">{html.escape(words)}</div>' + feedback_html(draft),
            unsafe_allow_html=True,
        )
        with st.form(f"queued_{draft_id}", border=False):
            if draft.get("target_rule_id"):
                if st.form_submit_button("Withdraw"):
                    _act(base, pin, f"/drafts/{draft_id}/reject", {}, lambda r: f"Draft #{draft_id} withdrawn")
                return
            text = st.text_area("Or approve your own wording now", value=words, key=f"queued_text_{draft_id}", height=90)
            approve, reject = st.columns(2)
            if approve.form_submit_button("Approve my wording"):
                _act(base, pin, f"/drafts/{draft_id}/approve", {"text": text.strip(), "signature": draft.get("signature") or {}}, approved_message)
            if reject.form_submit_button("Withdraw"):
                _act(base, pin, f"/drafts/{draft_id}/reject", {}, lambda r: f"Draft #{draft_id} withdrawn")


def render_plain_draft(base, pin, draft):
    """A weekly-distillation draft: edit and approve directly, or ask for a rewrite."""
    draft_id = draft.get("id")
    with st.container(border=True):
        st.markdown(
            f'<div class="rule-meta">Draft #{draft_id} · {html.escape(draft_origin(draft))} · '
            f'{html.escape(str(draft.get("created_at") or "")[:10])} · '
            f'sources: {", ".join(str(i) for i in draft.get("source_feedback_ids") or []) or "none"}</div>',
            unsafe_allow_html=True,
        )
        with st.form(f"draft_{draft_id}", border=False):
            text = st.text_area("Rule text", value=str(draft.get("text") or ""), key=f"draft_text_{draft_id}", height=110)
            signature = st.text_input(SIGNATURE_LABEL, value=signature_value(draft.get("signature")), key=f"draft_sig_{draft_id}")
            approve, reject, save, refine = st.columns(4)
            if approve.form_submit_button("Approve", type="primary"):
                _act(base, pin, f"/drafts/{draft_id}/approve", {"text": text.strip(), "signature": parse_signature(signature)}, approved_message)
            if reject.form_submit_button("Reject"):
                _act(base, pin, f"/drafts/{draft_id}/reject", {}, lambda r: f"Draft #{draft_id} rejected")
            if save.form_submit_button("Save edit"):
                _act(base, pin, f"/drafts/{draft_id}/edit", {"text": text.strip(), "signature": parse_signature(signature)},
                     lambda r: f"Draft #{draft_id} updated")
            if refine.form_submit_button("Ask ChatGPT to refine"):
                _act(base, pin, f"/drafts/{draft_id}/refine", {}, lambda r: f"Draft #{draft_id} queued for ChatGPT · {WAIT_NOTE}")


def render_drafts(base, pin, drafts):
    st.markdown(
        f'<div class="rules-section">Pending drafts · {len(drafts)}</div>',
        unsafe_allow_html=True,
    )
    if not drafts:
        st.caption("No drafts waiting. Write a rule above, grade with rule scope, or wait for the weekly distillation.")
        return
    proposed = [d for d in drafts if d.get("refine_status") == "proposed"]
    queued = [d for d in drafts if d.get("refine_status") == "queued"]
    plain = [d for d in drafts if d.get("refine_status") not in ("proposed", "queued")]
    signature_only = [d for d in proposed if is_signature_only(d)]
    drops = [d for d in proposed if is_drop(d)]
    if proposed or queued:
        st.caption(f"{len(proposed)} ready to sign off"
                   + (f" ({len(drops)} proposed drop{'s' if len(drops) != 1 else ''})" if drops else "")
                   + f" · {len(queued)} waiting for ChatGPT's rewrite")
    if signature_only:
        render_signature_only(base, pin, signature_only)
    for draft in proposed:
        if draft not in signature_only:
            render_proposal(base, pin, draft)
    for draft in plain:
        render_plain_draft(base, pin, draft)
    if len(queued) > 3:
        with st.expander(f"Waiting for ChatGPT's rewrite · {len(queued)}"):
            for draft in queued:
                render_queued(base, pin, draft)
    else:
        for draft in queued:
            render_queued(base, pin, draft)


def normalized(text) -> str:
    return " ".join(str(text or "").split())


def is_signature_only(draft) -> bool:
    """A revision whose rewrite keeps the rule's text and sets no score bounds:
    approving it only changes when the rule applies, not what it says."""
    proposal = draft.get("proposal") or {}
    return bool(draft.get("target_rule_id")) and not is_drop(draft) \
        and normalized(proposal.get("text")) == normalized(draft.get("raw_text")) and not proposal.get("effect")


def render_signature_only(base, pin, drafts):
    """Signature passes arrive in bulk; list them compactly with one approval."""
    with st.expander(f"Signature-only updates · {len(drafts)} (text unchanged, no score bounds)", expanded=True):
        st.markdown(
            '<div class="rules-list">' + "".join(
                '<div class="rule-row">'
                f'<div class="rule-head"><span class="rule-id">{html.escape(str(d.get("target_rule_id")))}</span>'
                f'<span class="rule-meta">draft #{d.get("id")}</span></div>'
                f'<div class="rule-meta">{html.escape(signature_text((d.get("proposal") or {}).get("signature")))}</div>'
                + (f'<div class="refine-note">{html.escape(str(d["proposal"]["rationale"]))}</div>' if (d.get("proposal") or {}).get("rationale") else "")
                + "</div>"
                for d in drafts
            ) + "</div>",
            unsafe_allow_html=True,
        )
        st.caption("Approving sets each rule's signature in place; the rule text and its score bounds stay as they are. "
                   "To edit, send back or reject one, pick it below.")
        if st.button(f"Approve all {len(drafts)} signature updates", type="primary", key="approve_signature_only"):
            approved, errors = 0, []
            for draft in drafts:
                try:
                    api(base, pin, f"/drafts/{draft['id']}/approve", {}, method="POST")
                    approved += 1
                except ValueError as exc:
                    errors.append(f"#{draft['id']}: {exc}")
            if errors:
                st.error(f"{approved} approved; {len(errors)} failed: " + "; ".join(errors[:5]))
            else:
                flash(f"Approved {approved} signature updates · calibration and binding can now tell when those rules apply")
        labels = {f"{d.get('target_rule_id')} · draft #{d.get('id')}": d for d in drafts}
        pick = st.selectbox("Review one individually", ["—"] + list(labels), key="signature_only_pick")
        if pick in labels:
            render_proposal(base, pin, labels[pick])


def flash(message: str) -> None:
    """Show a success message after a full rerun, so every list on the tab
    reflects the change that was just made."""
    st.session_state["rules_flash"] = message
    st.rerun()


def _act(base, pin, path, payload, message):
    try:
        result = api(base, pin, path, payload, method="POST")
    except ValueError as exc:
        st.error(str(exc))
        return
    flash(message(result))


def render_signature_pass(base, pin, rules):
    """Rules with no signature never match an item, so calibration cannot judge
    them and the reviewer's packet hints never show them."""
    missing = [r for r in rules if r.get("active") and str(r.get("rule_id") or "").startswith("R-0") and signature_is_empty(r.get("signature"))]
    if not missing:
        return
    st.caption(
        f"{len(missing)} active rule{'s have' if len(missing) != 1 else ' has'} no signature, so nothing can tell when "
        f"{'they apply' if len(missing) != 1 else 'it applies'}: calibration shows no data and binding cannot check them."
    )
    if st.button(f"Ask ChatGPT to write signatures ({len(missing)})", key="rules_signature_pass"):
        _act(base, pin, "/refine-missing", {}, lambda r: f"{r.get('queued')} revision(s) queued for ChatGPT · you sign off each one · {WAIT_NOTE}")


def render_rules(base, pin, rules, include_inactive):
    st.markdown(
        f'<div class="rules-section">{"All" if include_inactive else "Active"} rules · {len(rules)}</div>',
        unsafe_allow_html=True,
    )
    render_signature_pass(base, pin, rules)
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
            + (f'{html.escape(effect_text(rule.get("effect")))} · ' if effect_text(rule.get("effect")) else "")
            + f'{html.escape(str(rule.get("source") or ""))} · {html.escape(str(rule.get("created_at") or "")[:10])}</div>'
            "</div>"
        )
    st.markdown('<div class="rules-list">' + "".join(rows) + "</div>", unsafe_allow_html=True)

    active_ids = [r["rule_id"] for r in rules if r.get("active")]
    if not active_ids:
        return
    with st.expander("Change a rule: revise with ChatGPT, supersede, score bounds, deactivate"):
        with st.form("rule_action", border=False):
            rule_id = st.selectbox("Rule", active_ids, key="rule_action_id")
            revise_note = st.text_input("Note for ChatGPT (revise) — what should change?", key="rule_action_revise",
                                        placeholder="e.g. too broad: only uncrewed maritime and air programs")
            text = st.text_area("Replacement text (supersede only)", key="rule_action_text", height=100,
                                placeholder="State the principle, then the boundary. The old rule becomes inactive and points at the new one.")
            signature = st.text_input("Signature (workers: a, b; tickers: X; keywords: k) — sets what calibration counts as applicable", key="rule_action_signature")
            floor, ceiling = effect_inputs("rule_action", None)
            fold_version = st.text_input("Fold into brief version (e.g. 2026.10.1) — the rule is archived when that brief deploys", key="rule_action_fold")
            revise, set_bounds = st.columns(2)
            if revise.form_submit_button("Ask ChatGPT to revise"):
                _act(base, pin, f"/{rule_id}/refine", {"feedback": revise_note.strip()}, lambda r: f"Revision of {r.get('rule_id')} queued as draft #{r.get('draft_id')} · {WAIT_NOTE}")
            if set_bounds.form_submit_button("Set score bounds"):
                effect = effect_payload(floor, ceiling)
                _act(base, pin, f"/{rule_id}/effect", {"effect": effect},
                     lambda r: f"{r.get('rule_id')} score bounds: {effect_text(r.get('effect')) or 'none'}")
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


@st.cache_data(ttl=300, show_spinner=False)
def fetch_guides(base):
    """The monthly-audit and how-to-grade pages, served by the aggregator from
    the same files as its runbook so this tab never drifts from it."""
    try:
        response = requests.get(f"{base}/grades/guide", timeout=15)
        if response.status_code != 200:
            return {}
        return dict((response.json() or {}).get("guides") or {})
    except Exception:
        return {}


def render_guide(guides, key, fallback_title):
    guide = (guides or {}).get(key) or {}
    text = str(guide.get("text") or "").strip()
    if text:
        st.markdown(text)
    else:
        st.markdown(f"### {fallback_title}")
        st.caption("Guide unavailable: the aggregator did not serve it. The canonical page is in the aggregator repo under docs/.")


def render_rules_view(base):
    from calibration_view import fetch_summary, render_audit, render_calibration_sections

    pin = str(st.session_state.get("grader_pin", "")).strip()
    if not pin:
        st.markdown('<div class="empty-state">Open Owner mode and enter the grader PIN to manage rules.</div>', unsafe_allow_html=True)
        return
    message = st.session_state.pop("rules_flash", None)
    if message:
        st.success(message)
    guides = fetch_guides(base)
    drafts_tab, calibration_tab, audit_tab, grade_tab = st.tabs(["Drafts and rules", "Calibration", "Monthly audit", "How to grade"])

    with drafts_tab:
        render_composer(base, pin)
        include_inactive = st.checkbox("Show inactive and superseded rules", key="rules_include_inactive")
        try:
            drafts = api(base, pin, "/drafts?status=pending")["drafts"]
            rules = api(base, pin, "?include=inactive" if include_inactive else "")["rules"]
        except ValueError as exc:
            st.error(str(exc))
        else:
            render_drafts(base, pin, drafts)
            render_rules(base, pin, rules, include_inactive)

    summary = None
    try:
        summary = fetch_summary(base, pin)
    except ValueError as exc:
        with calibration_tab:
            st.error(str(exc))
    with calibration_tab:
        if summary:
            render_calibration_sections(base, pin, summary)
    with audit_tab:
        render_guide(guides, "monthly_audit", "Monthly audit — 20 minutes")
        if summary:
            render_audit(base, pin, summary)
    with grade_tab:
        render_guide(guides, "how_to_grade", "How to grade")
