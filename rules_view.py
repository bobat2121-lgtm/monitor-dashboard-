"""Rules page: one loop for tuning the grader.

Grade an item on the feed (or write here) as a Rule or an Item; ChatGPT drafts
it at its next run; the owner edits ChatGPT's version and sends it back (the
edit travels with the card) or publishes it; calibration watches the owner's
grades and starts new drafts when a pattern holds. Three tabs:

- Drafts: cards pinned in the order that needs the owner (back from ChatGPT,
  with ChatGPT, your turn, waiting), with Publish / Send back / Discard, and
  Undo for anything decided in the last 24 hours.
- Rules & Items: what the grader uses, searchable, with Revise and Retire.
- Calibration: trends that become drafts, the scoreboard, the monthly audit.

A Rule is a standing principle (optionally a hard score floor or ceiling). An
Item is a worked example (this story, the owner's grade, the principle): the
grader follows it for similar stories; it never binds.

Every read and write goes through the aggregator's /rules and /calibration
endpoints with the runtime Owner PIN in a header. Nothing is cached across
sessions and no secret is stored in this repo.
"""

import html
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - tzdata missing
    EASTERN = timezone(timedelta(hours=-4))


STATE_ORDER = ["ignored", "misapplied", "dormant", "working", None]
STATE_LABEL = {
    "working": ("working", "#2f855a"),
    "ignored": ("ignored", "#c05621"),
    "misapplied": ("misapplied", "#c53030"),
    "dormant": ("dormant", "#718096"),
    None: ("no data yet", "#4a5568"),
}
KIND_LABEL = {"rule": "Rule", "item": "Item"}
SIGNATURE_LABEL = "Applies to (workers: a, b; tickers: X; keywords: k)"
# When ChatGPT answers drafts (America/New_York): right after each edition
# (the review task's step 10) and at each Rule Refiner run.
PICKUPS_ET = ["06:50", "08:50", "10:30", "11:50", "15:00", "16:50", "18:50", "21:30"]
WAIT_NOTE = "ChatGPT answers at its next run."


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
    return f'<span class="rule-badge" style="background:{color}">{html.escape(label)}</span>'


def kind_chip(kind) -> str:
    kind = "item" if kind in ("item", "case") else "rule"
    return f'<span class="loop-kind loop-kind-{kind}">{KIND_LABEL[kind]}</span>'


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
    if run_id == "calibration-trend":
        return f"from calibration · {len(draft.get('source_feedback_ids') or [])} grades"
    if draft.get("target_rule_id"):
        return f"revision of {draft['target_rule_id']}"
    if run_id == "owner":
        return "written here"
    if not run_id:
        return "from a grade"
    return run_id


def approved_message(result) -> str:
    noun = "item" if result.get("kind") == "item" else "rule"
    if result.get("updated_in_place"):
        return f"Updated {result.get('rule_id')} in place · undo within 24 h below"
    message = f"Published {noun} {result.get('rule_id')}"
    if result.get("superseded"):
        message += f" · replaces {result['superseded']}"
    return message + " · the grader uses it from the next edition · undo within 24 h"


def sort_rules(rules):
    order = {state: index for index, state in enumerate(STATE_ORDER)}
    return sorted(rules, key=lambda r: (order.get(r.get("state"), len(order)), r.get("id") or 0))


def normalized(text) -> str:
    return " ".join(str(text or "").split())


def next_pickup_label(now=None) -> str:
    """The next time ChatGPT answers drafts, as '~6:50 PM ET' (or 'tomorrow ~…')."""
    now_et = (now or datetime.now(timezone.utc)).astimezone(EASTERN)
    for day in (0, 1):
        date = (now_et + timedelta(days=day)).date()
        for hhmm in PICKUPS_ET:
            hour, minute = (int(x) for x in hhmm.split(":"))
            at = datetime(date.year, date.month, date.day, hour, minute, tzinfo=EASTERN)
            if at > now_et:
                clock = at.strftime("%I:%M %p").lstrip("0")
                return f"{'tomorrow ' if day else ''}~{clock} ET"
    return "at its next run"


# ---------------------------------------------------------------- draft states

def sent_back(draft) -> bool:
    """The owner answered a ChatGPT version (round >= 1), so the card is pinned."""
    return any(int(f.get("round") or 0) >= 1 for f in draft.get("owner_feedback") or [])


def is_drop(draft) -> bool:
    return (draft.get("proposal") or {}).get("action") == "drop"


def is_signature_only(draft) -> bool:
    """A revision whose rewrite keeps the rule's text and sets no score bounds:
    publishing it only changes when the rule applies, not what it says."""
    proposal = draft.get("proposal") or {}
    return bool(draft.get("target_rule_id")) and not is_drop(draft) and not sent_back(draft) \
        and normalized(proposal.get("text")) == normalized(draft.get("raw_text")) and not proposal.get("effect")


def classify(drafts) -> dict:
    groups = {"back": [], "with_chatgpt": [], "your_turn": [], "signature_only": [], "waiting": []}
    for draft in drafts:
        status = draft.get("refine_status")
        if status == "queued":
            groups["with_chatgpt" if sent_back(draft) else "waiting"].append(draft)
        elif status == "proposed" and sent_back(draft):
            groups["back"].append(draft)
        elif status == "proposed" and is_signature_only(draft):
            groups["signature_only"].append(draft)
        else:
            groups["your_turn"].append(draft)
    return groups


# ---------------------------------------------------------------- actions

def flash(message: str) -> None:
    """Show a success message after a full rerun, so every list on the page
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


# ---------------------------------------------------------------- drafts tab

def render_composer(base, pin):
    with st.form("rule_composer", border=True):
        st.markdown('<div class="rules-section" style="margin-top:0">New</div>', unsafe_allow_html=True)
        kind = st.radio("This is", ["Rule", "Item"], horizontal=True, key="composer_kind",
                        help="Rule: a standing principle. Item: a worked example that guides the grader but never binds. "
                             "Items are best made from the feed's Grade row, which links the story.")
        text = st.text_area("In your own words", key="composer_text", height=90,
                            placeholder="e.g. counter-drone orders under $1M are borderline unless it's a covered company")
        if st.form_submit_button("Send to ChatGPT", type="primary"):
            if len(text.strip()) < 20:
                st.info("Write at least a sentence (20 characters) so ChatGPT has something to work with.")
            else:
                _act(base, pin, "/drafts", {"text": text.strip(), "kind": kind.lower()},
                     lambda r: f"{KIND_LABEL.get(r.get('kind'), 'Draft')} draft #{r.get('draft_id')} "
                               f"{'was already queued' if r.get('duplicate') else 'sent to ChatGPT'} · back {next_pickup_label()}")


def recent_label(draft) -> str:
    undo = draft.get("undo") or {}
    target = draft.get("precedent_rule_id") or draft.get("target_rule_id") or f"draft #{draft.get('id')}"
    if draft.get("status") == "rejected":
        return f"Discarded draft #{draft.get('id')}"
    if undo.get("type") == "dropped" or draft.get("approved_variant") == "drop":
        return f"Dropped {target}"
    if undo.get("type") == "in_place":
        return f"Updated {target} in place"
    return f"Published {target}"


def render_recent(base, pin, recent):
    if not recent:
        return
    with st.expander(f"Just decided · {len(recent)} · undo within 24 h"):
        for draft in recent:
            label, button = st.columns([5, 1])
            label.markdown(
                f'<div class="rule-meta" style="margin-top:8px">{html.escape(recent_label(draft))} · '
                f'{html.escape(str(draft.get("decided_at") or "")[11:16])} UTC</div>',
                unsafe_allow_html=True,
            )
            if button.button("Undo", key=f"undo_{draft['id']}"):
                _act(base, pin, f"/drafts/{draft['id']}/undo", {}, lambda r: f"Undone · draft #{r.get('draft_id')} is back in Drafts")


def card_header(draft, status) -> str:
    return (
        '<div class="loop-card-head">'
        + kind_chip(draft.get("kind"))
        + f'<span class="rule-meta" style="margin-top:0">Draft #{draft.get("id")} · {html.escape(draft_origin(draft))}'
        + f' · round {draft.get("refine_round") or 0} · {html.escape(status)}</span></div>'
    )


def history_html(draft) -> str:
    rows = []
    for f in draft.get("owner_feedback") or []:
        if f.get("edit"):
            rows.append(f'<div class="refine-note">You sent back (round {html.escape(str(f.get("round", "")))}): {html.escape(str(f["edit"]))}</div>')
        if f.get("text"):
            rows.append(f'<div class="refine-note">Your note (round {html.escape(str(f.get("round", "")))}): {html.escape(str(f["text"]))}</div>')
    return "".join(rows)


def applies_html(proposal, target=None, kind="rule") -> str:
    chips = [f'<span class="refine-chip">{html.escape(signature_text(proposal.get("signature")))}</span>']
    if kind != "item" and effect_text(proposal.get("effect")):
        chips.append(f'<span class="refine-chip">{html.escape(effect_text(proposal["effect"]))}</span>')
    if proposal.get("supersedes") and proposal["supersedes"] != target:
        chips.append(f'<span class="refine-chip warn">would replace {html.escape(proposal["supersedes"])}</span>')
    for rule_id in proposal.get("conflicts") or []:
        chips.append(f'<span class="refine-chip warn">conflicts with {html.escape(rule_id)}</span>')
    for rule_id in proposal.get("overlaps") or []:
        chips.append(f'<span class="refine-chip">overlaps {html.escape(rule_id)}</span>')
    return '<div class="refine-chips">' + "".join(chips) + "</div>"


def render_card(base, pin, draft, status):
    """One draft: ChatGPT's version in an editable box, and three buttons."""
    draft_id = draft.get("id")
    proposal = draft.get("proposal") or {}
    target = draft.get("target_rule_id")
    kind = draft.get("kind") or "rule"
    base_text = str(proposal.get("text") or draft.get("text") or "")
    with st.container(border=True):
        st.markdown(card_header(draft, status), unsafe_allow_html=True)
        text = st.text_area("ChatGPT's version (edit it, then publish or send back)" if proposal.get("text") else "Your draft",
                            value=base_text, key=f"card_text_{draft_id}", height=110)
        st.markdown(
            applies_html(proposal or {"signature": draft.get("signature")}, target, kind)
            + (f'<div class="refine-note">{html.escape(str(proposal["rationale"]))}</div>' if proposal.get("rationale") else ""),
            unsafe_allow_html=True,
        )
        note = st.text_input("Note to ChatGPT (optional)", key=f"card_note_{draft_id}",
                             placeholder="what else to change; your edits above go back with the card")
        details = st.toggle("Details", key=f"card_details_{draft_id}")
        signature, floor, ceiling, replace = None, None, None, False
        if details:
            st.markdown(
                f'<div class="refine-label">{"The rule now" if target else "Your words"}</div>'
                f'<div class="refine-owner">{html.escape(str(draft.get("raw_text") or draft.get("text") or ""))}</div>'
                + history_html(draft),
                unsafe_allow_html=True,
            )
            signature = st.text_input(SIGNATURE_LABEL, value=signature_value(proposal.get("signature") or draft.get("signature")), key=f"card_sig_{draft_id}")
            if kind != "item":
                floor, ceiling = effect_inputs(f"card_{draft_id}", proposal.get("effect"))
                if proposal.get("supersedes") and not target:
                    replace = st.checkbox(f"Replace {proposal['supersedes']} with this rule (history kept)", key=f"card_replace_{draft_id}")
        publish, send, discard = st.columns(3)
        if publish.button("Publish", type="primary", key=f"publish_{draft_id}"):
            payload = {"text": text.strip()}
            if details:
                payload["signature"] = parse_signature(signature)
                if kind != "item":
                    payload["effect"] = effect_payload(floor, ceiling)
                if replace:
                    payload["supersedes"] = proposal["supersedes"]
            _act(base, pin, f"/drafts/{draft_id}/approve", payload, approved_message)
        if send.button("Send back to ChatGPT", key=f"sendback_{draft_id}"):
            edited = text.strip()
            payload = {}
            if normalized(edited) != normalized(base_text):
                payload["text"] = edited
            if note.strip():
                payload["feedback"] = note.strip()
            if not payload:
                st.info("Edit the text or add a note, so ChatGPT knows what to change.")
            else:
                _act(base, pin, f"/drafts/{draft_id}/refine", payload,
                     lambda r: f"Draft #{draft_id} sent back{' with your edit' if r.get('edit') else ''} · pinned at the top until ChatGPT returns it {next_pickup_label()}")
        if discard.button("Discard", key=f"discard_{draft_id}"):
            _act(base, pin, f"/drafts/{draft_id}/reject", {},
                 lambda r: f"Draft #{draft_id} discarded{f'; {target} unchanged' if target else ''} · undo within 24 h")


def render_drop_card(base, pin, draft):
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
    with st.container(border=True):
        st.markdown(card_header(draft, f"ChatGPT proposes dropping {subject}"), unsafe_allow_html=True)
        st.markdown(
            f'<div class="refine-owner">{html.escape(str(draft.get("raw_text") or draft.get("text") or ""))}</div>'
            '<div class="refine-label" style="margin-top:10px">Why ChatGPT would drop it</div>'
            f'<div class="rule-text">{html.escape(str(proposal.get("rationale") or ""))}</div>'
            + ('<div class="refine-chips">' + "".join(chips) + "</div>" if chips else ""),
            unsafe_allow_html=True,
        )
        note = st.text_input("Or say what it should say, and send it back for a rewrite", key=f"drop_note_{draft_id}")
        drop, keep, rewrite = st.columns(3)
        if drop.button(f"Drop {subject}", type="primary", key=f"drop_{draft_id}"):
            _act(base, pin, f"/drafts/{draft_id}/drop", {},
                 lambda r: f"Dropped {r['dropped']} · undo within 24 h" if r.get("dropped") else f"Draft #{draft_id} dropped")
        if keep.button(f"Keep {subject}", key=f"keep_{draft_id}"):
            _act(base, pin, f"/drafts/{draft_id}/reject", {}, lambda r: f"Kept {target}, unchanged" if target else f"Draft #{draft_id} closed")
        if rewrite.button("Rewrite instead", key=f"rewrite_{draft_id}"):
            if len(note.strip()) < 5:
                st.info("Add a note saying what it should say, so the rewrite answers exactly that.")
            else:
                _act(base, pin, f"/drafts/{draft_id}/refine", {"feedback": note.strip()},
                     lambda r: f"Draft #{draft_id} sent back · back {next_pickup_label()}")


def render_waiting_row(base, pin, draft, pinned: bool):
    draft_id = draft.get("id")
    sent = draft.get("owner_edit") or next((f.get("text") for f in reversed(draft.get("owner_feedback") or []) if f.get("text")), None)
    words = sent if pinned and sent else str(draft.get("raw_text") or draft.get("text") or "")
    with st.container(border=True):
        text_col, button_col = st.columns([6, 1])
        text_col.markdown(
            card_header(draft, f"with ChatGPT · back {next_pickup_label()}")
            + f'<div class="refine-owner">{"You sent: " if pinned and sent else ""}{html.escape(words)}</div>',
            unsafe_allow_html=True,
        )
        if button_col.button("Withdraw", key=f"withdraw_{draft_id}"):
            _act(base, pin, f"/drafts/{draft_id}/reject", {}, lambda r: f"Draft #{draft_id} withdrawn · undo within 24 h")


def render_signature_only(base, pin, drafts):
    """Signature passes arrive in bulk; list them compactly with one approval."""
    with st.expander(f"Signature-only updates · {len(drafts)} (text unchanged, no score bounds)"):
        st.markdown(
            '<div class="rules-list">' + "".join(
                '<div class="rule-row">'
                f'<div class="rule-head"><span class="rule-id">{html.escape(str(d.get("target_rule_id")))}</span>'
                f'<span class="rule-meta">draft #{d.get("id")}</span></div>'
                f'<div class="rule-meta">{html.escape(signature_text((d.get("proposal") or {}).get("signature")))}</div>'
                + "</div>"
                for d in drafts
            ) + "</div>",
            unsafe_allow_html=True,
        )
        if st.button(f"Publish all {len(drafts)} signature updates", type="primary", key="approve_signature_only"):
            approved, errors = 0, []
            for draft in drafts:
                try:
                    api(base, pin, f"/drafts/{draft['id']}/approve", {}, method="POST")
                    approved += 1
                except ValueError as exc:
                    errors.append(f"#{draft['id']}: {exc}")
            if errors:
                st.error(f"{approved} published; {len(errors)} failed: " + "; ".join(errors[:5]))
            else:
                flash(f"Published {approved} signature updates · undo any of them within 24 h")


def section(title: str, count: int) -> None:
    st.markdown(f'<div class="rules-section">{html.escape(title)} · {count}</div>', unsafe_allow_html=True)


def render_drafts_tab(base, pin):
    render_composer(base, pin)
    try:
        drafts = api(base, pin, "/drafts?status=pending")["drafts"]
        recent = api(base, pin, "/drafts?status=recent")["drafts"]
    except ValueError as exc:
        st.error(str(exc))
        return
    render_recent(base, pin, recent)
    groups = classify(drafts)
    if not drafts:
        st.caption("Nothing waiting. Grade an item on the feed with a ruling, or write one above.")
        return
    st.caption(
        f"{len(groups['back']) + len(groups['your_turn']) + len(groups['signature_only'])} for you · "
        f"{len(groups['with_chatgpt']) + len(groups['waiting'])} with ChatGPT · next ChatGPT run {next_pickup_label()}"
    )
    if groups["back"]:
        section("Back from ChatGPT", len(groups["back"]))
        for draft in groups["back"]:
            render_drop_card(base, pin, draft) if is_drop(draft) else render_card(base, pin, draft, "your edit applied · ready")
    if groups["with_chatgpt"]:
        section("With ChatGPT", len(groups["with_chatgpt"]))
        for draft in groups["with_chatgpt"]:
            render_waiting_row(base, pin, draft, pinned=True)
    if groups["your_turn"] or groups["signature_only"]:
        section("Your turn", len(groups["your_turn"]) + len(groups["signature_only"]))
        if groups["signature_only"]:
            render_signature_only(base, pin, groups["signature_only"])
        for draft in groups["your_turn"]:
            if is_drop(draft):
                render_drop_card(base, pin, draft)
            else:
                render_card(base, pin, draft, "ready" if draft.get("refine_status") == "proposed" else "not sent to ChatGPT")
    if groups["waiting"]:
        with st.expander(f"Waiting for ChatGPT's first version · {len(groups['waiting'])}"):
            for draft in groups["waiting"]:
                render_waiting_row(base, pin, draft, pinned=False)


# ---------------------------------------------------------------- rules & items tab

def render_signature_pass(base, pin, rules):
    """Rules with no signature never match an item, so calibration cannot judge
    them and the reviewer's packet hints never show them."""
    missing = [r for r in rules if r.get("active") and str(r.get("rule_id") or "").startswith("R-0") and signature_is_empty(r.get("signature"))]
    if not missing:
        return
    st.caption(f"{len(missing)} active rule{'s have' if len(missing) != 1 else ' has'} no signature, so nothing can tell when it applies.")
    if st.button(f"Ask ChatGPT to write signatures ({len(missing)})", key="rules_signature_pass"):
        _act(base, pin, "/refine-missing", {}, lambda r: f"{r.get('queued')} revision(s) sent to ChatGPT · they come back to Drafts")


def matches(entry, query) -> bool:
    if not query:
        return True
    haystack = " ".join([str(entry.get("rule_id") or ""), str(entry.get("text") or ""), signature_text(entry.get("signature"))]).lower()
    return all(term in haystack for term in query.lower().split())


def render_rules_items_tab(base, pin):
    search_col, filter_col = st.columns([3, 2])
    query = search_col.text_input("Search", key="ri_search", placeholder="company, keyword or id")
    view = filter_col.radio("Show", ["All", "Rules", "Items", "Inactive"], horizontal=True, key="ri_filter")
    inactive = view == "Inactive"
    try:
        rules = api(base, pin, "?include=inactive" if inactive else "")["rules"]
        items = api(base, pin, "/items?include=inactive" if inactive else "/items")["items"]
    except ValueError as exc:
        st.error(str(exc))
        return
    entries = []
    if view in ("All", "Rules", "Inactive"):
        entries += [dict(r, type="rule") for r in sort_rules(rules)]
    if view in ("All", "Items", "Inactive"):
        entries += [dict(i, type="item") for i in items]
    if inactive:
        entries = [e for e in entries if not e.get("active")]
    shown = [e for e in entries if matches(e, query)]
    st.caption(f"{len([e for e in entries if e['type'] == 'rule'])} rules · {len([e for e in entries if e['type'] == 'item'])} items"
               + (f" · {len(shown)} match" if query else ""))
    for entry in shown:
        rule_id = str(entry.get("rule_id"))
        state = STATE_LABEL.get(entry.get("state"), STATE_LABEL[None])[0] if entry["type"] == "rule" else "guides"
        title = f"{rule_id} · {'Item' if entry['type'] == 'item' else 'Rule'} · {state}{'' if entry.get('active') else ' · inactive'} — {normalized(entry.get('text'))[:90]}"
        with st.expander(title):
            st.markdown(
                f'<div class="rule-text">{html.escape(str(entry.get("text") or ""))}</div>'
                f'<div class="rule-meta">{html.escape(signature_text(entry.get("signature")))}'
                + (f' · {html.escape(effect_text(entry.get("effect")))}' if effect_text(entry.get("effect")) else "")
                + (f' · superseded by #{entry.get("superseded_by")}' if entry.get("superseded_by") else "")
                + f' · {html.escape(str(entry.get("created_at") or "")[:10])}</div>',
                unsafe_allow_html=True,
            )
            if entry.get("active"):
                note = st.text_input("What should change?", key=f"ri_note_{rule_id}", placeholder="e.g. too broad: maritime and air programs only")
                revise, retire = st.columns(2)
                if revise.button("Revise with ChatGPT", key=f"ri_revise_{rule_id}"):
                    _act(base, pin, f"/{rule_id}/refine", {"feedback": note.strip()},
                         lambda r: f"Revision of {r.get('rule_id')} sent to ChatGPT as draft #{r.get('draft_id')} · back in Drafts {next_pickup_label()}")
                if retire.button("Retire", key=f"ri_retire_{rule_id}"):
                    _act(base, pin, f"/{rule_id}/deactivate", {}, lambda r: f"{r.get('rule_id')} retired · restore it from Inactive")
            elif not entry.get("superseded_by"):
                if st.button("Restore", key=f"ri_restore_{rule_id}"):
                    _act(base, pin, f"/{rule_id}/reactivate", {}, lambda r: f"{r.get('rule_id')} restored")
    if view in ("All", "Rules"):
        render_signature_pass(base, pin, rules)


# ---------------------------------------------------------------- calibration tab

TREND_STATUS = {
    "drafted": ("drafted", "#2b6cb0"),
    "ready": ("ready", "#2f855a"),
    "watching": ("watching", "#4a5568"),
    "covered": ("covered", "#718096"),
    "dismissed": ("dismissed", "#718096"),
}


def render_trends(base, pin):
    from calibration_view import api as calibration_api

    st.markdown('<div class="rules-section" style="margin-top:0">Trends in your grades</div>', unsafe_allow_html=True)
    try:
        data = calibration_api(base, pin, "/trends")
    except ValueError as exc:
        st.error(str(exc))
        return
    cfg = data.get("config") or {}
    trends = [t for t in data.get("trends") or [] if t.get("status") in ("drafted", "ready", "watching")]
    st.caption(
        f"A trend becomes a draft for you when at least {cfg.get('min_grades', 5)} of your grades in {cfg.get('window_days', 30)} days "
        f"lean the same way against the grader ({int(float(cfg.get('min_share', 0.75)) * 100)}% or more of that area) and no rule or item covers them."
    )
    if not trends:
        st.caption("No trends yet. Every grade with a reason (especially “not my focus”) brings one closer.")
        return
    for trend in trends[:12]:
        label, color = TREND_STATUS.get(trend.get("status"), ("", "#4a5568"))
        progress = f"{trend.get('n')}/{trend.get('needed')}" if trend.get("status") == "watching" else f"{int(float(trend.get('share') or 0) * 100)}% of {trend.get('comparable')}"
        text_col, button_col = st.columns([6, 1])
        text_col.markdown(
            f'<div class="rule-row"><div class="rule-head"><span class="rule-badge" style="background:{color}">{html.escape(label)}</span>'
            f'<span class="rule-meta" style="margin-top:0">{html.escape(progress)}'
            + (f' · draft #{trend["draft_id"]} in Drafts' if trend.get("draft_id") else "")
            + f'</span></div><div class="rule-text">{html.escape(str(trend.get("summary") or ""))}</div></div>',
            unsafe_allow_html=True,
        )
        if trend.get("status") in ("ready", "watching") and button_col.button("Draft now", key=f"trend_draft_{trend['key']}"):
            try:
                result = calibration_api(base, pin, "/trends/draft", {"key": trend["key"]})
            except ValueError as exc:
                st.error(str(exc))
            else:
                flash(f"Trend sent to ChatGPT as draft #{result.get('draft_id')} · back in Drafts {next_pickup_label()}")


def render_calibration_tab(base, pin, guides):
    from calibration_view import fetch_summary, render_audit, render_calibration_sections

    render_trends(base, pin)
    summary = None
    try:
        summary = fetch_summary(base, pin)
    except ValueError as exc:
        st.error(str(exc))
    if summary:
        render_calibration_sections(base, pin, summary)
    with st.expander("Monthly audit"):
        render_guide(guides, "monthly_audit", "Monthly audit — 20 minutes")
        if summary:
            render_audit(base, pin, summary)
    with st.expander("How to grade"):
        render_guide(guides, "how_to_grade", "How to grade")


# ---------------------------------------------------------------- page

@st.cache_data(ttl=300, show_spinner=False)
def fetch_guides(base):
    """The monthly-audit and how-to-grade pages, served by the aggregator from
    the same files as its runbook so this page never drifts from it."""
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
    pin = str(st.session_state.get("grader_pin", "")).strip()
    if not pin:
        st.markdown('<div class="empty-state">Open Owner mode and enter the grader PIN to manage rules.</div>', unsafe_allow_html=True)
        return
    message = st.session_state.pop("rules_flash", None)
    if message:
        st.success(message)
    guides = fetch_guides(base)
    drafts_tab, rules_tab, calibration_tab = st.tabs(["Drafts", "Rules & Items", "Calibration"])
    with drafts_tab:
        render_drafts_tab(base, pin)
    with rules_tab:
        render_rules_items_tab(base, pin)
    with calibration_tab:
        render_calibration_tab(base, pin, guides)
