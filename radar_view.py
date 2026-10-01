"""Radar page: every change to what the Universe collects, signed off here.

Ask in your own words (track a company or relationship, or a story we
missed); the Radar Scout, a scheduled Claude routine, drafts a card at its
next run and adds its own cards from deal news and newsroom gaps. The owner
approves a card (the Worker re-checks the newsroom and saves a registry
revision), edits it and sends it back, or discards it. A trial result card
(a discovery source's 21-day trial is up, or ended early by its grades) is
answered with Promote, Extend 21 days or Retire. A missed-story card (a
story you reported that we collected but the Grader ranked low) is sent to
Rules or discarded. Anything decided in the last 24 hours can be undone.
Top to bottom:

- New request: the composer.
- Just decided: undo within 24 hours.
- Your turn: Claude's cards, send-backs that came back first.
- With Claude: requests and send-backs waiting for the next run, with
  Withdraw (none on a sent-back trial result).
- Lane health: the sources Radar manages and whether they are collecting,
  then each trial source's scorecard, then recall by industry from the
  evening recall audit.

Every read and write goes through the aggregator's /radar endpoints with the
runtime Owner PIN in a header. Nothing is cached across sessions and no
secret is stored in this repo.
"""

import html
import math
import string
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

from grading_ui import reason_label

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - tzdata missing
    EASTERN = timezone(timedelta(hours=-4))


LANE_LABEL = {"relationship": "Relationship source", "discovery": "Discovery lane"}
# A card about a company's own newsroom (a newsroom gap), not a relationship.
NEWSROOM_LABEL = "Company newsroom"
ACTION_LABEL = {
    "request": "Your request", "new_source": "New source", "registry_only": "Registry only",
    "deal_update": "Deal update", "fix_source": "Fix source", "retire_source": "Retire", "no_change": "No change",
    # The trial lane (phase 3).
    "start_trial": "Start trial", "trial_result": "Trial result",
    # Phase 4: the answer to a missed-story request whose story was collected
    # but ranked low; Send to Rules files it as a Rules draft.
    "missed_story": "Missed story",
}
OPERATION_LABEL = {"source_upsert": "Source", "knowledge_upsert": "Relationship record", "entity_upsert": "Company"}
EFFECT_LABEL = {"source_upsert": "source", "knowledge_upsert": "relationship record", "entity_upsert": "company"}
# The fields the Worker's `effects` name, as the owner reads them.
FIELD_LABEL = {
    "endpoint": "newsroom URL", "adapter": "method", "cadence_minutes": "cadence", "source_role": "role", "companyStatus": "company status",
    "radar_lane": "lane", "entity_ids": "companies", "knowledge_ids": "relationship links", "industry_ids": "industries",
    "path_prefix": "article path", "include_terms": "topic filter", "exclude_paths": "excluded sections", "tracking_notes": "notes",
    "match_mode": "matching", "context_terms": "guard words", "evidence_note": "evidence", "evidence_source": "evidence",
    "evidence_as_of": "evidence", "memberships": "industries", "sec_cik": "SEC CIK", "cage_codes": "CAGE codes", "uei_codes": "UEI codes",
    "procurement_identity_evidence": "procurement evidence", "relationship": "relationship",
    "config": "collection settings", "trial": "trial dates",
}
# Read-only facts a card's Details show for each operation.
STATUS_LABEL = {"configured": "configured, collected once approved", "draft": "draft, saved but not collected",
                "paused": "paused, not collected", "needs_adapter": "needs an adapter, not collected"}
ROLE_LABEL = {"company_newsroom": "company newsroom", "official_customer_partner": "customer or partner newsroom",
              "issuer_release_distribution": "release distributor"}
COMPOSER_KINDS = {"Track a company or relationship": "track", "We missed this story": "missed"}
MISSED_CAPTION = ("For a missed story, paste its link: at its next run Claude checks whether we collected it and why it was missed "
                  "(no source, a filter, a broken source or a low ranking), and answers with a card.")
# When the Radar Scout runs (America/New_York).
PICKUPS_ET = ["13:30", "20:30"]
# A comma before one of these belongs to a legal name ("Acme Robotics, Inc."),
# not to the alias list.
NAME_SUFFIXES = {"inc", "inc.", "llc", "l.l.c.", "ltd", "ltd.", "limited", "corp", "corp.", "co", "co.", "plc",
                 "ag", "gmbh", "sa", "s.a.", "nv", "n.v.", "bv", "b.v.", "lp", "l.p.", "llp", "pte. ltd."}
# The Worker's slowest check for a Radar relationship source
# (digest_config.radar.relationship_cadence_minutes; contract default).
RELATIONSHIP_CADENCE_MINUTES = 30
# The Worker's slowest check for a discovery source on a trial
# (applyOwnerChange's trial-lane rule, digest_config.radar.trial_cadence_max_minutes),
# and how long a trial or an Extend runs (digest_config.radar.trial_days).
TRIAL_CADENCE_MINUTES = 60
TRIAL_DAYS = 21
# A trial result card: why it is due, the owner's three answers (each posts
# exactly {"verdict"}) and how Just decided names the one taken.
TRIAL_REASON_LABEL = {"day_21": "Day 21 result", "early_promote": "Early: 3 grades of 70+", "early_retire": "Early: 3 grades below 40"}
VERDICT_LABEL = {"promote": "Promote", "extend": f"Extend {TRIAL_DAYS} days", "retire": "Retire"}
VERDICT_DONE = {"promote": "Promoted", "extend": "Extended", "retire": "Retired"}
# The Details label and help of a source's include_terms. On a relationship
# source of any kind but acquired, the Worker's relationship filter already
# keeps posts naming the covered company or pairing a deal word with an
# autonomy topic, and include_terms only adds posts to those.
TOPIC_FILTER_FIELD = ("Topic filter words (one per line)",
                      "A post must mention at least one of these. Leave empty to collect every company update.")
EXTRA_NAMES_FIELD = ("Extra names to keep (one per line)",
                     "Posts naming the covered company, its subsidiaries or products, or with a deal word plus an autonomy topic, "
                     "are kept automatically. A post naming one of these is kept too.")


def api(base, pin, path="", payload=None, method=None):
    headers = {"X-Owner-Pin": pin}
    try:
        if payload is None and method != "POST":
            response = requests.get(f"{base}/radar{path}", headers=headers, timeout=20)
        else:
            # Approve re-checks the newsroom before saving, so writes get longer.
            response = requests.post(f"{base}/radar{path}", headers=headers, json=payload or {}, timeout=60)
    except requests.RequestException:
        raise ValueError("The Radar service is temporarily unavailable. Try refreshing.") from None
    try:
        result = response.json()
    except ValueError:
        raise ValueError("The Radar service is temporarily unavailable. Try refreshing.") from None
    if response.status_code == 403:
        raise ValueError("Bad PIN.")
    if response.status_code >= 400 or not result.get("ok"):
        raise ValueError(result.get("error") or "The change could not be completed.")
    return result


def next_pickup_label(now=None) -> str:
    """The next Radar Scout run, as '~1:30 PM ET' (or 'tomorrow ~…')."""
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


def short_time(value) -> str:
    """'2026-10-02T17:35:00Z' -> 'Oct 2, 1:35 PM ET'. Midnight UTC exactly is
    how the Worker stores a date with no time (a newsroom's '2026-09-28'), so
    it reads as that date, 'Sep 28', never the evening before in ET."""
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:24]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    utc = parsed.astimezone(timezone.utc)
    if (utc.hour, utc.minute, utc.second, utc.microsecond) == (0, 0, 0, 0):
        return f"{utc:%b} {utc.day}"
    local = parsed.astimezone(EASTERN)
    return f"{local:%b} {local.day}, {local.hour % 12 or 12}:{local:%M %p} ET"


def dicts(value) -> list:
    """The objects in a list the Scout wrote by hand (samples, results,
    collisions): [] for anything that is not a list, so a malformed summary
    never stops the page, and a count always matches what is listed."""
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def number(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def count_text(value) -> str:
    """A Lane health count as text, '—' for null or a missing field: ints
    mixed with '—' would make one table column two Arrow types."""
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else "—"


def average_text(value) -> str:
    """A trial's average grade, rounded half up (62.5 reads 63), or '—' when
    it has none."""
    try:
        return count_text(math.floor(value + 0.5)) if isinstance(value, (int, float)) and not isinstance(value, bool) else "—"
    except (ValueError, OverflowError):  # NaN or infinity
        return "—"


def percent_text(value) -> str:
    """An industry's recall as text, '83%', or '—' before its first audit."""
    rounded = average_text(value)
    return rounded if rounded == "—" else rounded + "%"


def lines(text) -> list:
    return [x.strip() for x in str(text or "").splitlines() if x.strip()]


def split_aliases(text) -> list:
    """'Acme, Acme Robotics, Inc.' -> ['Acme', 'Acme Robotics, Inc.']."""
    aliases = []
    for part in str(text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if aliases and part.lower() in NAME_SUFFIXES:
            aliases[-1] += ", " + part
        else:
            aliases.append(part)
    return aliases


def esc(text) -> str:
    """Escaped text for an unsafe_allow_html block, on one line. A blank line
    ends a raw HTML block in Markdown and whatever follows renders as Markdown
    (remote images, links), so every run of whitespace becomes one space."""
    return html.escape(" ".join(("" if text is None else str(text)).split()))


def md_escape(text) -> str:
    """Plain text inside a Markdown message (st.success, st.error): every ASCII
    punctuation mark is backslash-escaped, so '![x](url)' stays literal."""
    escaped = "".join("\\" + ch if ch in string.punctuation else ch for ch in " ".join(str(text or "").split()))
    # GFM links bare addresses after the escapes are resolved; a zero-width
    # space after ':' and before '.' breaks 'https://', 'www.' and 'a@b.c'.
    return escaped.replace("\\:", "\\:\u200b").replace("\\.", "\u200b\\.")


def link(url, text, css="source-link") -> str:
    """An escaped outbound link; anything but http(s) stays plain text."""
    # Browsers drop tabs and line breaks from a URL; so does this, so the
    # href can never carry a blank line out of its HTML block.
    url = "".join(ch for ch in str(url or "") if ch not in "\t\n\r").strip()
    label = esc(text or url)
    if not url.lower().startswith(("https://", "http://")):
        return label
    css = f' class="{css}"' if css else ""
    return f'<a{css} href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{label}</a>'


# ---------------------------------------------------------------- draft states

def proposal_of(draft, field="proposal") -> dict:
    proposal = draft.get(field)
    return proposal if isinstance(proposal, dict) else {}


def lane_of(draft) -> str:
    return str(proposal_of(draft).get("lane") or draft.get("lane") or "")


def action_of(draft) -> str:
    return str(proposal_of(draft).get("action") or draft.get("action") or "")


def sent_back(draft) -> bool:
    """The owner answered a Claude version at least once."""
    return number(draft.get("refine_round")) >= 1 or bool(draft.get("owner_feedback"))


def operations_of(draft) -> list:
    return [op for op in proposal_of(draft).get("operations") or [] if isinstance(op, dict)]


def approvable(draft) -> bool:
    return action_of(draft) != "no_change" and bool(operations_of(draft))


def trial_result(draft) -> bool:
    """A trial's verdict card: no operations; the owner picks Promote, Extend
    or Retire and the Worker builds that change from the current registry."""
    return action_of(draft) == "trial_result"


def missed_story(draft) -> bool:
    """The answer to the owner's missed-story request when the story was
    collected but ranked low: no operations; the owner sends it to Rules (a
    Rules draft about that event) or discards it."""
    return action_of(draft) == "missed_story"


def result_of(draft) -> dict:
    """What a decided card recorded: a trial's verdict, a missed story's
    Rules draft id; {} when absent."""
    return proposal_of(draft, "result")


def classify(drafts) -> dict:
    """Your turn (send-backs that came back first) and With Claude."""
    your_turn = [d for d in drafts if d.get("refine_status") == "proposed"]
    with_claude = [d for d in drafts if d.get("refine_status") == "queued"]
    return {"your_turn": sorted(your_turn, key=lambda d: not sent_back(d)), "with_claude": with_claude}


def last_feedback(draft) -> dict:
    """The latest send-back: {round, text, at, edited_operations?}, or {}."""
    feedback = [f for f in draft.get("owner_feedback") or [] if isinstance(f, dict)]
    return feedback[-1] if feedback else {}


def sent_words(draft) -> str:
    """What the owner last sent Claude: the latest send-back's note ('' when
    it carried only edits to the card), else the request."""
    latest = last_feedback(draft)
    if latest:
        return str(latest.get("text") or "")
    return str(draft.get("owner_text") or "")


def draft_title(draft, limit: int = 140) -> str:
    title = proposal_of(draft).get("title") or proposal_of(draft, "previous_proposal").get("title") or draft.get("owner_text")
    title = " ".join(str(title or f"Draft #{draft.get('id')}").split())
    return title if len(title) <= limit else title[: limit - 1].rsplit(" ", 1)[0] + "…"


# ---------------------------------------------------------------- html

def company_newsroom(draft) -> bool:
    """A relationship-lane card about a company's own newsroom (a newsroom
    gap) rather than a relationship: no relationship kind, and every source
    it adds or changes stays out of the relationship lane; with no source, a
    Scout no_change keyed to the company."""
    proposal = proposal_of(draft) or proposal_of(draft, "previous_proposal")
    if lane_of(draft) != "relationship" or proposal.get("relationship_kind"):
        return False
    sources = [op.get("value") for op in proposal.get("operations") or []
               if isinstance(op, dict) and op.get("kind") == "source_upsert"]
    if sources:
        # An update that leaves the lane out keeps the stored one, unknown here.
        return all(isinstance(v, dict) and not v.get("radar_lane") and ("radar_lane" in v or not v.get("key"))
                   for v in sources)
    return (draft.get("origin") == "scout" and action_of(draft) == "no_change"
            and str(proposal.get("dedupe_key") or "").startswith("entity:"))


def chips_html(draft) -> str:
    lane, action = lane_of(draft), action_of(draft)
    chips = []
    if lane and company_newsroom(draft):
        chips.append(f'<span class="loop-kind loop-kind-newsroom">{esc(NEWSROOM_LABEL)}</span>')
    elif lane:
        chips.append(f'<span class="loop-kind loop-kind-{"discovery" if lane == "discovery" else "relationship"}">'
                     f'{esc(LANE_LABEL.get(lane, lane))}</span>')
    if action:
        chips.append(f'<span class="refine-chip">{esc(ACTION_LABEL.get(action, action.replace("_", " ")))}</span>')
    return "".join(chips)


def card_header(draft, status=None) -> str:
    origin = "your request" if draft.get("origin") == "owner" else "from the Scout"
    meta = f"#{html.escape(str(draft.get('id')))} · {origin}"
    if number(draft.get("refine_round")):
        meta += f" · round {number(draft.get('refine_round'))}"
    applied = '<span class="refine-chip applied">your edit applied</span>' \
        if draft.get("refine_status") == "proposed" and sent_back(draft) else ""
    return (
        '<div class="loop-card-head">' + chips_html(draft) + applied
        + f'<span class="rule-meta" style="margin-top:0">{meta}{" · " + html.escape(status) if status else ""}</span></div>'
    )


def unfiltered_of(probe) -> dict:
    """The same newsroom probed without the topic filter, which the Scout adds
    when the filtered probe found no post; {} when absent."""
    unfiltered = probe.get("unfiltered") if isinstance(probe, dict) else None
    return unfiltered if isinstance(unfiltered, dict) else {}


def evidence_html(proposal) -> str:
    """'Probe: 38 posts · 4 excluded · checked Sep 30, 1:35 PM ET · Backtest:
    3 matches in 60 days, 1 with guard words', then a warn chip for every name
    that also matches something else. A probe whose topic filter let nothing
    through adds how many posts the newsroom has without it; a backtest the
    Worker cut short shows its count as a lower bound ('5000+')."""
    parts, chips = [], []
    probe = proposal.get("probe") if isinstance(proposal.get("probe"), dict) else {}
    if probe:
        excluded = sum(number(n) for n in (probe.get("excluded") or {}).values()) if isinstance(probe.get("excluded"), dict) else 0
        line = f"Probe: {number(probe.get('total_found'))} posts · {excluded} excluded"
        unfiltered = unfiltered_of(probe)
        if unfiltered:
            line += f" · {number(unfiltered.get('total_found'))} without the topic filter"
        if probe.get("checked_at"):
            line += f" · checked {short_time(probe['checked_at'])}"
        parts.append(line)
    backtest = proposal.get("backtest") if isinstance(proposal.get("backtest"), dict) else {}
    results = dicts(backtest.get("results"))
    if results:
        hits = sum(number(r.get("hits")) for r in results)
        more = "+" if any(r.get("truncated") for r in results) else ""
        line = f"Backtest: {hits}{more} match{'es' if hits != 1 or more else ''} in {number(backtest.get('window_days')) or 60} days"
        guarded = [r for r in results if r.get("context_hits") is not None]
        if guarded:
            line += f", {sum(number(r.get('context_hits')) for r in guarded)}{more} with guard words"
        parts.append(line)
    for collision in dicts(backtest.get("collisions")):
        if collision.get("term"):
            example = " ".join(str(collision.get("example_title") or "").split())
            chips.append(f'<span class="refine-chip warn">{esc(collision["term"])} also matches'
                         + (f' “{esc(example[:80])}”' if example else " other stories") + "</span>")
    if not parts and not chips:
        return ""
    # short_time passes an unreadable timestamp through as text: escape it.
    return ((f'<div class="rule-meta">{esc(" · ".join(parts))}</div>' if parts else "")
            + ('<div class="refine-chips">' + "".join(chips) + "</div>" if chips else ""))


def effects_html(draft) -> str:
    """A warn chip for every existing registry record the card would change,
    from the Worker's `effects` (worked out on the current registry), so the
    owner sees what Approve changes whatever the card's title says:
    'Changes existing source: Draganfly news · configured → paused'."""
    chips = []
    for effect in draft.get("effects") or []:
        if not isinstance(effect, dict) or effect.get("is_new"):
            continue
        changes = effect.get("changes") if isinstance(effect.get("changes"), dict) else {}
        if not changes:
            continue
        parts = []
        status = changes.get("configuration_status")
        if isinstance(status, list) and len(status) == 2:
            parts.append(f"{status[0]} → {status[1]}")
        for field in changes:
            label = FIELD_LABEL.get(field, str(field).replace("_", " "))
            if field != "configuration_status" and label not in parts:
                parts.append(label)
        chips.append(f'<span class="refine-chip warn">Changes existing {esc(EFFECT_LABEL.get(effect.get("kind"), "record"))}: '
                     f'{esc(effect.get("name") or effect.get("target"))} · {esc(", ".join(parts))}</span>')
    return '<div class="refine-chips">' + "".join(chips) + "</div>" if chips else ""


def scorecard_of(draft) -> dict:
    """A trial's numbers: the Worker's live scorecard when it sends one, else
    the snapshot Claude put on the card."""
    for card in (draft.get("trial_scorecard"), proposal_of(draft).get("scorecard")):
        if isinstance(card, dict):
            return card
    return {}


def trial_html(draft) -> str:
    """A trial result card's body: why it is due, the trial's numbers, and
    Claude's pick with what Promote does: 'Early: 3 grades of 70+' · 'Day 9
    of 21 · 4 shown in the panel · average grade 78 · 3 graded 70+ · 0 below
    40' · '12 collected · 9 unique · 3 duplicates · last article Sep 30' ·
    'Claude recommends Promote · Promote: becomes a regular source'."""
    proposal, card = proposal_of(draft), scorecard_of(draft)
    reason = str(proposal.get("reason") or "")
    rows = []
    if reason:
        rows.append(f'<div class="refine-chips"><span class="refine-chip">{esc(TRIAL_REASON_LABEL.get(reason, reason.replace("_", " ")))}</span></div>')
    day, of_days = number(card.get("day")), number(card.get("of_days"))
    grades = ([f"Day {day} of {of_days}"] if day and of_days else []) + [
        f"{number(card.get('shown'))} shown in the panel", f"average grade {average_text(card.get('avg_grade'))}",
        f"{number(card.get('grades_70_plus'))} graded 70+", f"{number(card.get('grades_below_40'))} below 40"]
    collection = [f"{number(card.get('collected'))} collected", f"{number(card.get('unique_catches'))} unique",
                  f"{number(card.get('duplicates'))} duplicates"]
    if card.get("last_article"):
        collection.append(f"last article {short_time(card['last_article'])}")
    target = proposal.get("promote_to") if isinstance(proposal.get("promote_to"), dict) else {}
    relationship = target.get("relationship") if isinstance(target.get("relationship"), dict) else {}
    promote = (f"becomes a relationship source of {relationship.get('covered_entity_id') or 'its covered company'}"
               if target.get("radar_lane") == "relationship" else "becomes a regular source")
    pick = VERDICT_LABEL.get(str(proposal.get("verdict") or ""))
    # short_time passes an unreadable timestamp through as text: escape it.
    rows += [f'<div class="rule-meta">{esc(" · ".join(grades))}</div>', f'<div class="rule-meta">{esc(" · ".join(collection))}</div>',
             f'<div class="rule-meta">{esc((f"Claude recommends {pick} · " if pick else "") + "Promote: " + promote)}</div>']
    return "".join(rows)


def missed_story_html(draft) -> str:
    """A missed-story card's diagnosis in plain words, from what the Worker
    stamped (its own match and review read, never the Scout's): 'Collected
    Sep 30, 1:00 PM ET as event 4512; the Grader rejected it (score 35,
    below materiality)'. A story matched by its title adds the event's link,
    so the owner can check it is the same story before sending it to Rules."""
    diagnosis = proposal_of(draft).get("diagnosis")
    if not isinstance(diagnosis, dict):
        return ""
    event_id, decision = number(diagnosis.get("event_id")), str(diagnosis.get("decision") or "")
    line = ("Collected" + (f" {short_time(diagnosis['collected_at'])}" if diagnosis.get("collected_at") else "")
            + (f" as event {event_id}" if event_id else "") + "; ")
    if decision == "rejected":
        score, reason = average_text(diagnosis.get("score")), diagnosis.get("reason_code")
        grade = ([f"score {score}"] if score != "—" else []) + ([reason_label(str(reason))] if reason else [])
        line += "the Grader rejected it" + (f" ({', '.join(grade)})" if grade else "")
    elif decision == "duplicate":
        canonical = number(diagnosis.get("canonical_event_id"))
        line += "the Grader marked it a duplicate" + (f" of event {canonical}" if canonical else "")
    elif decision == "selected":
        line += "the Grader selected it, but the edition did not publish it"
    else:
        line += "no Grader run has reviewed it yet"
    # short_time passes an unreadable timestamp through as text: escape it.
    rows = [f'<div class="rule-meta">{esc(line)}</div>']
    if diagnosis.get("matched_by") == "title":
        title = diagnosis.get("event_title") or diagnosis.get("event_url") or f"event {event_id}"
        rows.append(f'<div class="rule-meta">Matched by title: {link(diagnosis.get("event_url"), title, "")}</div>')
    return "".join(rows)


def start_trial_evidence_html(proposal) -> str:
    """A start_trial card's gate evidence as the Worker verified and stored
    it (contract P4.5), under the probe line: '2 misses in 30 days · 1
    unique', then each miss: its link, when it was first seen elsewhere,
    whether and how late a source collected it, and 'you reported it (#41)'
    or 'you graded it 78'. A card without evidence (phase 3) shows nothing."""
    evidence = proposal.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    counted = number(evidence.get("counted"))
    # The Worker stores window_days (digest_config.radar.discovery_window_days).
    rows = [f'<div class="rule-meta">{counted} miss{"" if counted == 1 else "es"} in {number(evidence.get("window_days")) or 30} days'
            f' · {number(evidence.get("unique_catches"))} unique</div>']
    for miss in dicts(evidence.get("misses")):
        parts = [f"first seen elsewhere {short_time(miss.get('first_seen_elsewhere'))}"]
        lead = miss.get("lead_hours")
        lead = lead if isinstance(lead, (int, float)) and not isinstance(lead, bool) and math.isfinite(lead) else None
        if not miss.get("collected_at"):
            parts.append("not collected")
        elif lead is None:
            parts.append(f"collected {short_time(miss['collected_at'])}")
        elif lead <= 0:
            parts.append("collected first")
        else:
            # number() truncates; a lead is rounded half up (6.5 reads 7).
            hours = math.floor(lead + 0.5)
            parts.append(f"collected {hours} h later" if hours else "collected under 1 h later")
        grade = average_text(miss.get("owner_grade"))
        if miss.get("owner_flagged"):
            request = number(miss.get("owner_request_id"))
            parts.append(f"you reported it (#{request})" if request else "you reported it")
        elif grade != "—":
            parts.append(f"you graded it {grade}")
        rows.append(f'<div class="rule-meta">{link(miss.get("url"), miss.get("url"), "")} · {esc(" · ".join(parts))}</div>')
    return "".join(rows)


def samples_html(proposal) -> str:
    rows = []
    probe = proposal.get("probe") if isinstance(proposal.get("probe"), dict) else {}
    newsroom = [("From the newsroom", dicts(probe.get("samples"))),
                ("From the newsroom, without the topic filter", dicts(unfiltered_of(probe).get("samples")))]
    for label, samples in newsroom:
        if not samples:
            continue
        spacing = ' style="margin-top:10px"' if rows else ""
        rows.append(f'<div class="refine-label"{spacing}>{esc(label)}</div>')
        rows += [f'<div class="refine-note">{link(s.get("url"), s.get("title"), "")}'
                 + (f' · {esc(short_time(s["published"]))}' if s.get("published") else "") + "</div>" for s in samples]
    backtest = proposal.get("backtest") if isinstance(proposal.get("backtest"), dict) else {}
    for result in dicts(backtest.get("results")):
        found = dicts(result.get("samples"))
        if not found:
            continue
        hits, more = number(result.get("hits")), "+" if result.get("truncated") else ""
        counts = f"{hits}{more} match{'es' if hits != 1 or more else ''}"
        if result.get("context_hits") is not None:
            counts += f", {number(result.get('context_hits'))}{more} with guard words"
        rows.append(f'<div class="refine-label" style="margin-top:10px">Past items matching “{esc(result.get("term"))}” · {esc(counts)}</div>')
        rows += [f'<div class="refine-note">{link(s.get("url"), s.get("title"), "")}'
                 + (f' · {esc(short_time(s["ts"]))}' if s.get("ts") else "") + "</div>" for s in found]
    return "".join(rows)


def sample_count(proposal) -> int:
    probe = proposal.get("probe") if isinstance(proposal.get("probe"), dict) else {}
    backtest = proposal.get("backtest") if isinstance(proposal.get("backtest"), dict) else {}
    return (len(dicts(probe.get("samples"))) + len(dicts(unfiltered_of(probe).get("samples")))
            + sum(len(dicts(r.get("samples"))) for r in dicts(backtest.get("results"))))


def history_html(draft) -> str:
    rows = []
    if draft.get("owner_text"):
        rows.append(f'<div class="refine-label">Your words</div><div class="refine-owner">{esc(draft["owner_text"])}</div>')
    if draft.get("owner_url"):
        rows.append(f'<div class="refine-note">Your link: {link(draft["owner_url"], draft["owner_url"], "")}</div>')
    for f in draft.get("owner_feedback") or []:
        if not isinstance(f, dict):
            continue
        edits = " · with your edits to the card" if f.get("edited_operations") else ""
        if f.get("text"):
            rows.append(f'<div class="refine-note">Your note (round {esc(f.get("round", ""))}){edits}: {esc(f["text"])}</div>')
        elif edits:
            rows.append(f'<div class="refine-note">You edited the card (round {esc(f.get("round", ""))})</div>')
    note = proposal_of(draft).get("notes")
    if note:
        rows.append(f'<div class="refine-note">Claude’s note: {esc(note)}</div>')
    return "".join(rows)


# ---------------------------------------------------------------- actions

def flash(message: str) -> None:
    """Show a success message after a full rerun, so every list on the page
    reflects the change that was just made."""
    st.session_state["radar_flash"] = message
    st.rerun()


def show_error(exc) -> None:
    """A Worker refusal as plain text. st.error renders Markdown, and a
    refusal can quote registry text the Scout wrote from web content (a
    trial source's name in 'X is no longer in the trial lane.'), so it is
    escaped like the success messages: no remote image, no link."""
    st.error(md_escape(str(exc)))


def _act(base, pin, path, payload, message):
    try:
        result = api(base, pin, path, payload, method="POST")
    except ValueError as exc:
        show_error(exc)
        return
    flash(message(result))


# ---------------------------------------------------------------- composer

def render_composer(base, pin):
    with st.form("radar_composer", border=True):
        st.markdown('<div class="rules-section" style="margin-top:0">New request</div>', unsafe_allow_html=True)
        kind = st.radio("This is", list(COMPOSER_KINDS), horizontal=True, key="radar_kind",
                        help="Track: a company, an acquisition, a customer or partner whose news should reach the digest. "
                             "Missed: a story the digest should have carried; paste its link.")
        text = st.text_area("In your own words", key="radar_text", height=90,
                            placeholder="e.g. Ondas bought Acme Robotics; follow Acme's newsroom for Ondas news")
        url = st.text_input("Link (required for a missed story)", key="radar_url", placeholder="https://…",
                            help="Optional when tracking (the deal announcement or the company's site). "
                                 "Required for a missed story: the story's own link.")
        # Static: a form widget does not rerun the page when it changes, so
        # nothing here can follow the radio.
        st.caption(MISSED_CAPTION)
        if st.form_submit_button("Send to Claude", type="primary"):
            kind, text, url = COMPOSER_KINDS[kind], text.strip(), url.strip()
            if len(text) < 10:
                st.info("Write a few words (10 characters or more) so Claude knows what to look for.")
            elif kind == "missed" and not url:
                st.info("Paste the story's link so Claude can see what we missed.")
            elif url and not url.lower().startswith(("https://", "http://")):
                st.info("The link must start with https:// or http://.")
            else:
                payload = {"text": text, "kind": kind}
                if url:
                    payload["url"] = url
                _act(base, pin, "/drafts", payload,
                     lambda r: f"Request #{r.get('draft_id')} {'was already with Claude' if r.get('duplicate') else 'sent to Claude'}"
                               f" · back {next_pickup_label()}")


# ---------------------------------------------------------------- just decided

def recent_label(draft) -> str:
    if draft.get("status") == "rejected":
        return f"Discarded #{draft.get('id')}"
    # A trial result records the owner's verdict; a missed story sent to
    # Rules, the Rules draft it filed.
    result = result_of(draft)
    if result.get("rules_draft_id"):
        return f"Sent to Rules #{draft.get('id')}"
    return f"{VERDICT_DONE.get(str(result.get('verdict')), 'Approved')} #{draft.get('id')}"


def render_recent(base, pin, recent):
    if not recent:
        return
    with st.expander(f"Just decided · {len(recent)} · undo within 24 h"):
        for draft in recent:
            label, button = st.columns([5, 1])
            label.markdown(
                '<div class="loop-card-head" style="margin-top:6px">' + chips_html(draft)
                + f'<span class="rule-meta" style="margin-top:0">{html.escape(recent_label(draft))} · '
                f'{html.escape(short_time(draft.get("decided_at")))}</span></div>'
                + f'<div class="recent-text">{html.escape(draft_title(draft, 240))}</div>',
                unsafe_allow_html=True,
            )
            if draft.get("undo_available") and button.button("Undo", key=f"radar_undo_{draft['id']}"):
                # Undoing a missed story sent to Rules withdraws its Rules
                # draft while that is still pending (the Worker answers 409
                # once it was decided on the Rules tab).
                rules_id = number(result_of(draft).get("rules_draft_id"))
                _act(base, pin, f"/drafts/{draft['id']}/undo", {},
                     lambda r: f"Undone · #{r.get('draft_id')} is back in Radar"
                               + (" · the registry change was reversed" if r.get("revision_id") else "")
                               + ((f" · Rules draft #{rules_id} withdrawn" if rules_id else " · its Rules draft withdrawn")
                                  if r.get("rules_draft_withdrawn") else ""))


# ---------------------------------------------------------------- your turn

def _text_field(value, field, label, key, shown, parse, area=False, **kwargs):
    """One editable field. The value changes only when the owner edits the
    text, so an untouched field goes back exactly as Claude wrote it."""
    widget = st.text_area if area else st.text_input
    entered = widget(label, value=shown, key=key, **kwargs)
    if entered != shown:
        value[field] = parse(entered)


def in_relationship_lane(value, draft=None) -> bool:
    """Whether Approve saves this source_upsert in the relationship lane, as
    applyOwnerChange decides it."""
    if "radar_lane" in value:
        return value.get("radar_lane") == "relationship"
    # An edit to an existing source that leaves the lane out keeps it.
    return bool(value.get("key")) and lane_of(draft or {}) == "relationship"


def include_terms_field(value, draft=None) -> tuple:
    """The label and help of a source's include_terms: EXTRA_NAMES_FIELD on a
    relationship source whose kind is not acquired, TOPIC_FILTER_FIELD
    anywhere else. The kind is the value's own relationship when it carries
    one (Approve stores that one), else the card's relationship_kind."""
    relationship = value.get("relationship")
    kind = relationship.get("kind") if isinstance(relationship, dict) else proposal_of(draft or {}).get("relationship_kind")
    return EXTRA_NAMES_FIELD if in_relationship_lane(value, draft) and kind != "acquired" else TOPIC_FILTER_FIELD


def cadence_ceiling(value, draft=None) -> int:
    """The slowest check applyOwnerChange accepts for this source_upsert, so
    the field never offers a cadence Approve would refuse: a relationship
    source RELATIONSHIP_CADENCE_MINUTES, a source on a trial
    TRIAL_CADENCE_MINUTES, a covered company's newsroom 8, another public
    company 60, anything else 120. Claude's own cadence always fits: the
    Worker checked it against the live settings."""
    draft = draft or {}
    relationship = in_relationship_lane(value, draft)
    covered = proposal_of(draft).get("covered_entity_id")
    # An edit that leaves the lane out keeps the stored one: on a trial card,
    # the trial lane.
    trial = value.get("radar_lane") == "trial" or (
        "radar_lane" not in value and bool(value.get("key")) and action_of(draft) in ("start_trial", "trial_result"))
    if trial:
        ceiling = TRIAL_CADENCE_MINUTES
    elif relationship:
        ceiling = RELATIONSHIP_CADENCE_MINUTES
    elif value.get("companyStatus") != "noncompany" and covered and covered in (value.get("entity_ids") or []):
        ceiling = 8
    elif value.get("companyStatus") == "public":
        ceiling = 60
    else:
        ceiling = 120
    return max(ceiling, min(120, number(value.get("cadence_minutes"))))


def facts_html(kind, value) -> str:
    """What an operation stores that the editable fields leave out, read-only:
    for a source, whether Approve configures it or leaves it as a draft, its
    company status, role, method and article path; for a relationship record,
    its kind, matching and the release (link and date) stored as evidence."""
    facts = []
    if kind == "source_upsert":
        # A protected source's routing-only value (no name, no URL) keeps its
        # status; any other source without one is saved as a draft.
        if value.get("name") or value.get("endpoint"):
            status = str(value.get("configuration_status") or "draft")
            facts.append(esc(f"Status: {STATUS_LABEL.get(status, status)}"))
        for field, label in (("companyStatus", "Company"), ("source_role", "Role"), ("adapter", "Method"), ("path_prefix", "Article path")):
            if value.get(field):
                shown = ROLE_LABEL.get(value[field], str(value[field]).replace("_", " ")) if field == "source_role" else value[field]
                facts.append(esc(f"{label}: {shown}"))
        if value.get("radar_lane") == "trial":
            # The Worker owns the dates: it sets them when a source joins the
            # lane and keeps the stored ones on any edit.
            dates = value.get("trial") if isinstance(value.get("trial"), dict) else {}
            facts.append(esc(f"Lane: discovery trial (until {short_time(dates['ends_at'])})" if dates.get("ends_at")
                             else f"Lane: discovery trial ({TRIAL_DAYS} days; dates set on approval)"))
        elif "radar_lane" in value:
            facts.append(esc("Lane: " + ("relationship" if value.get("radar_lane") == "relationship" else "none (the company's own sources)")))
    elif kind == "knowledge_upsert":
        for field, label in (("kind", "Kind"), ("match_mode", "Matching")):
            if value.get(field):
                facts.append(esc(f"{label}: {value[field]}"))
        source = str(value.get("evidence_source") or "").strip()
        if source or value.get("evidence_as_of"):
            # A link to the release; anything else (a repo path) as plain text.
            evidence = link(source, "release ↗", "") if source.lower().startswith(("https://", "http://")) else esc(source or "—")
            facts.append("Evidence: " + evidence + (f' as of {esc(value["evidence_as_of"])}' if value.get("evidence_as_of") else ""))
    return f'<div class="rule-meta">{" · ".join(facts)}</div>' if facts else ""


def operation_fields(draft_id, operations, draft=None) -> list:
    """Simple fields for each operation, under its read-only facts; returns
    the operations with the owner's edits applied (ids and every other field
    untouched)."""
    edited = []
    for index, operation in enumerate(operations):
        kind = operation.get("kind")
        value = dict(operation.get("value") or {})
        key = f"radar_{draft_id}_op{index}"
        st.markdown(f'<div class="radar-body"><div class="refine-label" style="margin-top:10px">{esc(OPERATION_LABEL.get(kind, kind))}'
                    f'{" · " + esc(value.get("name")) if value.get("name") else ""}</div>{facts_html(kind, value)}</div>', unsafe_allow_html=True)
        if kind in ("source_upsert", "knowledge_upsert", "entity_upsert"):
            _text_field(value, "name", "Name", f"{key}_name", str(value.get("name") or ""), str.strip)
        if kind == "source_upsert":
            _text_field(value, "endpoint", "Newsroom URL", f"{key}_endpoint", str(value.get("endpoint") or ""), str.strip)
            # Only the label and help depend on the lane: the same key and
            # parsing, so an untouched field goes back exactly as written.
            label, help_text = include_terms_field(value, draft)
            _text_field(value, "include_terms", label, f"{key}_include",
                        "\n".join(str(x) for x in value.get("include_terms") or []), lines, area=True, height=90, help=help_text)
            ceiling = cadence_ceiling(value, draft)
            shown = max(8, min(ceiling, number(value.get("cadence_minutes")) or 30))
            cadence = st.number_input("Check every (minutes)", min_value=8, max_value=ceiling, step=1, value=shown, key=f"{key}_cadence",
                                      help=f"8 to {ceiling} minutes for this kind of source.")
            if int(cadence) != shown:
                value["cadence_minutes"] = int(cadence)
        elif kind == "knowledge_upsert":
            _text_field(value, "aliases", "Aliases (comma separated)", f"{key}_aliases",
                        ", ".join(str(x) for x in value.get("aliases") or []), split_aliases)
            _text_field(value, "context_terms", "Guard words (one per line)", f"{key}_context",
                        "\n".join(str(x) for x in value.get("context_terms") or []), lines, area=True, height=90,
                        help="A story must also mention one of these for an alias to match. Use them for names shared with other companies.")
            _text_field(value, "evidence_note", "Evidence note", f"{key}_note", str(value.get("evidence_note") or ""), str.strip, area=True, height=90)
        elif kind == "entity_upsert":
            _text_field(value, "aliases", "Aliases (comma separated)", f"{key}_aliases",
                        ", ".join(str(x) for x in value.get("aliases") or []), split_aliases)
        edited.append({**operation, "value": value} if value != (operation.get("value") or {}) else operation)
    return edited


@st.fragment
def render_card(base, pin, draft):
    """One Claude card: what it would change (a warn chip for each existing
    record), why, the evidence, and three buttons. A trial result instead
    shows the trial's numbers and offers Promote, Extend and Retire (each
    posts exactly {"verdict"}) beside Send back, with no Discard: the trial
    stays due until the owner ends it. A missed story shows the Worker's
    diagnosis and offers Send to Rules and Discard only."""
    draft_id = draft.get("id")
    proposal = proposal_of(draft)
    operations = operations_of(draft)
    trial, missed = trial_result(draft), missed_story(draft)
    why = str(proposal.get("why") or "")
    with st.container(border=True):
        st.markdown(
            '<div class="radar-body">' + card_header(draft)
            + f'<div class="rule-text"><strong>{html.escape(draft_title(draft))}</strong></div>'
            + (f'<div class="refine-note">{esc(why)}'
               + (f' · {link(proposal.get("why_url"), "source ↗", "")}' if proposal.get("why_url") else "") + "</div>" if why else "")
            + effects_html(draft) + (trial_html(draft) if trial else "") + (missed_story_html(draft) if missed else "")
            + evidence_html(proposal) + (start_trial_evidence_html(proposal) if action_of(draft) == "start_trial" else "") + "</div>",
            unsafe_allow_html=True,
        )
        samples = sample_count(proposal)
        if samples:
            with st.expander(f"Samples · {samples}"):
                st.markdown(f'<div class="radar-body">{samples_html(proposal)}</div>', unsafe_allow_html=True)
        details = st.toggle("Details", key=f"radar_details_{draft_id}")
        edited = operations
        if details:
            history = history_html(draft)
            if history:
                st.markdown(f'<div class="radar-body">{history}</div>', unsafe_allow_html=True)
            # A trial result is sent back with a note only (the Worker answers
            # 400 to operations) and a verdict posts only {"verdict"}: the
            # built operation an undone verdict leaves on the card is not
            # offered for editing. A missed story has no operations.
            if not trial and not missed:
                edited = operation_fields(draft_id, operations, draft)
        changed = edited != operations
        if missed:
            # Sent as {text}; without it the Rules draft starts from your request's words.
            note = st.text_input("Your words for Rules (optional)", key=f"radar_note_{draft_id}",
                                 placeholder="what the Grader should learn; your request's words if empty")
        else:
            note = st.text_input("Note to Claude (optional)", key=f"radar_note_{draft_id}",
                                 placeholder="what to change" if trial else "what to change; your edits in Details go back with the card")
        discard = None
        if missed:
            # The Worker files a Rules draft about the diagnosed event and
            # closes the card (approved, undo within 24 h); 409 when the card
            # is no longer pending or another click is already filing it.
            to_rules, discard = st.columns(2)
            send = None
            if to_rules.button("Send to Rules", type="primary", key=f"radar_torules_{draft_id}"):
                _act(base, pin, f"/drafts/{draft_id}/to-rules", {"text": note.strip()} if note.strip() else {},
                     lambda r: f"{'Already in Rules' if r.get('duplicate') else 'Sent to Rules'} as draft #{number(r.get('rules_draft_id'))}")
        elif trial:
            # Claude's pick is the primary button; the Worker answers 422 when
            # the source has left the lane or the target lane is full.
            pick = str(proposal.get("verdict") or "")
            for column, (verdict, label) in zip(st.columns(3), VERDICT_LABEL.items()):
                if column.button(label, type="primary" if verdict == pick else "secondary", key=f"radar_{verdict}_{draft_id}"):
                    _act(base, pin, f"/drafts/{draft_id}/approve", {"verdict": verdict},
                         lambda r, done=VERDICT_DONE[verdict]: f"{done} · {md_escape(r.get('label')) or f'draft #{draft_id}'} · undo within 24 h")
            send = st.container()
        elif approvable(draft):
            approve, send, discard = st.columns(3)
            if approve.button("Approve", type="primary", key=f"radar_approve_{draft_id}"):
                _act(base, pin, f"/drafts/{draft_id}/approve", {"operations": edited} if changed else {},
                     # The label carries Claude's title: literal text, never Markdown.
                     lambda r: f"Approved · {md_escape(r.get('label')) or f'draft #{draft_id}'} · undo within 24 h")
        else:
            send, discard = st.columns(2)
        if send is not None and send.button("Send back to Claude", key=f"radar_sendback_{draft_id}"):
            payload = {}
            if note.strip():
                payload["feedback"] = note.strip()
            if changed:
                payload["operations"] = edited
            if not payload:
                st.info("Add a note, so Claude knows what to change." if trial
                        else "Add a note or edit the Details, so Claude knows what to change.")
            else:
                _act(base, pin, f"/drafts/{draft_id}/refine", payload,
                     lambda r: f"#{draft_id} sent back{' with your edits' if changed else ''} · back {next_pickup_label()}")
        if discard is not None and discard.button("Discard", key=f"radar_discard_{draft_id}"):
            _act(base, pin, f"/drafts/{draft_id}/reject", {}, lambda r: f"#{draft_id} discarded · undo within 24 h")


# ---------------------------------------------------------------- with claude

def render_waiting_row(base, pin, draft):
    draft_id = draft.get("id")
    words = sent_words(draft)
    edits = " · with your edits to the card" if last_feedback(draft).get("edited_operations") else ""
    with st.container(border=True):
        text_col, button_col = st.columns([6, 1])
        text_col.markdown(
            card_header(draft, f"with Claude · back {next_pickup_label()}")
            + (f'<div class="refine-owner">You sent: {esc(words)}{edits}</div>' if words
               else f'<div class="refine-owner">Your edits to: {esc(draft_title(draft))}</div>'),
            unsafe_allow_html=True,
        )
        # Withdraw is a reject: a sent-back trial result has none, as its card
        # has no Discard, so the verdict stays due until the owner picks one.
        if not trial_result(draft) and button_col.button("Withdraw", key=f"radar_withdraw_{draft_id}"):
            _act(base, pin, f"/drafts/{draft_id}/reject", {}, lambda r: f"#{draft_id} withdrawn · undo within 24 h")


# ---------------------------------------------------------------- lane health

def trial_day(source) -> str:
    """'4/21'; '25/21 · due' once a configured trial is past its end and waits
    for the owner's verdict (day 22 of 21 starts at ends_at); '—' without
    dates."""
    trial = source.get("trial") if isinstance(source.get("trial"), dict) else {}
    day, of_days = trial.get("day"), trial.get("of_days")
    if count_text(day) == "—" or count_text(of_days) == "—":
        return "—"
    due = day > of_days and source.get("configuration_status") == "configured"
    return f"{day}/{of_days}" + (" · due" if due else "")


def recall_rows(recall) -> list:
    """Lane health's recall table, one row per registry industry, every cell
    text ('—' before the industry's first audit), so a missing number never
    splits a column's type: Industry, Last audit ('Sep 30'), Found, Captured
    (late catches included), Late and Recall ('83%'). [] when the Worker
    sent no recall or no industry has been audited yet."""
    rows = dicts(recall)
    if not any(r.get("last_audit_date") for r in rows):
        return []
    return [{"Industry": str(r.get("name") or r.get("industry_id") or "—"),
             "Last audit": short_time(r.get("last_audit_date")),
             "Found": count_text(r.get("found_30d")), "Captured": count_text(r.get("captured_30d")),
             "Late": count_text(r.get("late_30d")), "Recall": percent_text(r.get("recall_pct"))} for r in rows]


def render_source_tables(sources):
    """The sources Radar manages, then each trial source's scorecard."""
    # 7-day counts: posts delivered and distinct URLs filtered out (the
    # seed poll's archive not counted). The Worker omits them from every
    # row when it cannot read the collector's tables, and sends null for a
    # source outside the managed manifest.
    counted = any("kept_7d" in s or "excluded_7d" in s for s in sources)
    st.dataframe(
        [{"Source": s.get("name") or s.get("key"), "Covered company": s.get("covered_entity_name") or "—",
          "Kind": "Trial" if s.get("radar_lane") == "trial" else str(s.get("relationship_kind") or "—").capitalize(),
          "Every (min)": s.get("cadence_minutes"),
          "Status": s.get("status") or "—", "Last check": short_time(s.get("last_ok")), "Last article": short_time(s.get("last_article")),
          **({"Kept (7d)": count_text(s.get("kept_7d")), "Filtered (7d)": count_text(s.get("excluded_7d"))} if counted else {})}
         for s in sources],
        hide_index=True,
    )
    # Each trial-lane source's scorecard (a retired, paused one included),
    # all text so a missing number never splits a column's type.
    trials = [s for s in sources if isinstance(s.get("trial"), dict)]
    if trials:
        st.caption("Trial sources")
        st.dataframe(
            [{"Source": str(s.get("name") or s.get("key") or "—"), "Day": trial_day(s), "Shown": count_text(s["trial"].get("shown")),
              "Avg grade": average_text(s["trial"].get("avg_grade")), "70+": count_text(s["trial"].get("grades_70_plus")),
              "<40": count_text(s["trial"].get("grades_below_40")), "Unique": count_text(s["trial"].get("unique_catches")),
              "Duplicates": count_text(s["trial"].get("duplicates")), "Collected": count_text(s["trial"].get("collected"))}
             for s in trials],
            hide_index=True,
        )


def render_lanes(base, pin):
    with st.expander("Lane health"):
        try:
            lanes = api(base, pin, "/lanes")
        except ValueError as exc:
            show_error(exc)
            return
        sources = lanes.get("sources") or []
        if sources:
            render_source_tables([s for s in sources if isinstance(s, dict)])
        else:
            st.caption("No Radar sources yet. Sources you approve here are listed with their collection status.")
        # Recall by industry (phase 4) does not depend on the sources: the
        # Worker sends one row per registry industry, or leaves it out when it
        # cannot read the audits. After the source and trial tables, so it is
        # dataframe[2] when both are shown.
        recall = lanes.get("recall")
        if isinstance(recall, list) and recall:
            rows = recall_rows(recall)
            if rows:
                st.caption("Recall by industry (30 days)")
                st.dataframe(rows, hide_index=True)
            else:
                st.caption("No recall audit yet; the 8:30 PM run audits a third of the industries each night.")


# ---------------------------------------------------------------- page

def section(title: str, count: int) -> None:
    st.markdown(f'<div class="rules-section">{html.escape(title)} · {count}</div>', unsafe_allow_html=True)


def render_radar_view(base):
    pin = str(st.session_state.get("grader_pin", "")).strip()
    if not pin:
        st.markdown('<div class="empty-state">Enter your Grader PIN in Owner mode to open Radar.</div>', unsafe_allow_html=True)
        return
    message = st.session_state.pop("radar_flash", None)
    if message:
        st.success(message)
    render_composer(base, pin)
    try:
        pending = api(base, pin, "/drafts?status=pending")
        recent = api(base, pin, "/drafts?status=recent")["drafts"]
    except ValueError as exc:
        show_error(exc)
        return
    groups = classify(pending.get("drafts") or [])
    counts = pending.get("counts") or {}
    st.caption(
        f"{counts.get('your_turn', len(groups['your_turn']))} for you · "
        f"{counts.get('with_claude', len(groups['with_claude']))} with Claude · next Claude run {next_pickup_label()}"
    )
    render_recent(base, pin, recent)
    if groups["your_turn"]:
        section("Your turn", len(groups["your_turn"]))
        for draft in groups["your_turn"]:
            render_card(base, pin, draft)
    if groups["with_claude"]:
        section("With Claude", len(groups["with_claude"]))
        for draft in groups["with_claude"]:
            render_waiting_row(base, pin, draft)
    if not groups["your_turn"] and not groups["with_claude"]:
        st.caption("Nothing waiting. Ask above; the Scout also drafts cards from deal news and newsroom gaps at each run.")
    render_lanes(base, pin)
