import copy
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from radar_view import (EXTRA_NAMES_FIELD, MISSED_CAPTION, TOPIC_FILTER_FIELD, average_text, cadence_ceiling, chips_html, classify, count_text,
                        effects_html, evidence_html, facts_html, history_html, include_terms_field, md_escape, missed_story_html, next_pickup_label,
                        percent_text, recall_rows, recent_label, sample_count, samples_html, sent_words, short_time, split_aliases,
                        start_trial_evidence_html, trial_day, trial_html)


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"


class StubResponse:
    text = ""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


TITLE = "Acme Robotics → Ondas · acquired business · every 30 min"
KNOWLEDGE = {"kind": "knowledge_upsert", "value": {
    "kind": "subsidiary", "name": "Acme Robotics", "aliases": ["Acme Robotics", "Acme Robotics, Inc.", "Acme"],
    "entity_ids": ["entity_ondas"], "industry_ids": [], "match_mode": "direct", "context_terms": [],
    "evidence_note": "Announced Oct 2, 2026; closing expected in Q4.", "evidence_source": "https://ir.ondas.com/news/acme", "evidence_as_of": "2026-10-02"}}
SOURCE = {"kind": "source_upsert", "value": {
    "name": "Acme Robotics newsroom", "endpoint": "https://acmerobotics.com/news", "adapter": "html", "path_prefix": "/news/",
    "entity_ids": ["entity_ondas"], "knowledge_ids": ["$op:0"], "source_role": "company_newsroom", "companyStatus": "private",
    "cadence_minutes": 30, "configuration_status": "configured", "include_terms": [],
    "radar_lane": "relationship", "relationship": {"covered_entity_id": "entity_ondas", "kind": "acquired", "counterpart": "Acme Robotics"}}}


def draft(draft_id, **fields):
    base = {"id": draft_id, "created_at": "2026-09-30T17:40:00Z", "updated_at": "2026-09-30T17:40:00Z", "decided_at": None,
            "origin": "scout", "lane": "relationship", "action": "new_source", "status": "pending", "refine_status": "proposed",
            "refine_round": 0, "owner_text": None, "owner_url": None, "owner_feedback": [], "proposal": None,
            "previous_proposal": None, "result": None, "undo_available": False}
    return {**base, **fields}


NEW_SOURCE = draft(12, proposal={
    "lane": "relationship", "action": "new_source", "title": TITLE,
    "why": "Ondas announced the acquisition of Acme Robotics on Oct 2, 2026.", "why_url": "https://ir.ondas.com/news/acme",
    "covered_entity_id": "entity_ondas", "counterpart": "Acme Robotics", "relationship_kind": "acquired",
    "dedupe_key": "source:acmerobotics.com/news", "operations": [KNOWLEDGE, SOURCE],
    "probe": {"endpoint": "https://acmerobotics.com/news", "adapter": "html", "total_found": 38,
              "excluded": {"outside_source_scope": 4, "external_media": 1},
              "samples": [{"title": "Acme ships <b>Model X</b>", "url": "https://acmerobotics.com/news/model-x", "published": "2026-09-28T14:00:00Z"}],
              "checked_at": "2026-09-30T17:35:00Z", "preview_id": "preview-1"},
    "backtest": {"window_days": 60, "results": [
        {"term": "Acme Robotics", "hits": 3, "samples": [{"event_id": 1, "title": "Acme Robotics wins Army order", "url": "https://example.com/a", "ts": "2026-09-01T12:00:00Z"}]},
        {"term": "Acme", "hits": 9, "samples": []}],
        "collisions": [{"term": "Acme", "example_title": "Acme Brick raises prices"}]},
})
MISSED = "<script>alert(1)</script> we missed the Navy's Skydio order"
NO_CHANGE = draft(13, origin="owner", lane="discovery", action="no_change", refine_round=1, owner_text=MISSED,
                  owner_url="https://news.example/skydio-navy", owner_feedback=[{"round": 1, "text": "Look again at the <Navy> release", "at": "2026-09-30T15:00:00Z"}],
                  proposal={"lane": "discovery", "action": "no_change", "title": "Skydio is already collected",
                            "why": "Skydio's newsroom is configured and carried this order on Sep 29.", "operations": []})
REQUEST = draft(20, origin="owner", action="request", refine_status="queued", owner_text="Track <Shield AI>'s customers")
SENT_BACK = draft(21, refine_status="queued", refine_round=1, owner_feedback=[{"round": 1, "text": "Use the investor newsroom instead", "at": "2026-09-30T16:00:00Z"}],
                  previous_proposal={"title": "Beta Corp → Kratos · customer · every 30 min"})
RECENT = [
    draft(9, status="approved", decided_at="2026-09-30T18:05:00Z", undo_available=True, result={"revision_id": "rev-7", "label": "Radar #9: Gamma"},
          proposal={"lane": "relationship", "action": "registry_only", "title": "Gamma Systems → AeroVironment · acquired business"}),
    draft(8, status="rejected", decided_at="2026-09-29T12:00:00Z", undo_available=False, lane="discovery", action="no_change",
          proposal={"title": "Nothing new for Zeta"}),
]
LANES = [{"key": "managed_acme", "name": "Acme Robotics newsroom", "endpoint": "https://acmerobotics.com/news", "radar_lane": "relationship",
          "relationship_kind": "acquired", "covered_entity_name": "Ondas", "cadence_minutes": 30, "configuration_status": "configured",
          "status": "Collecting", "last_ok": "2026-09-30T17:00:00Z", "last_article": "2026-09-29T15:00:00Z", "fail_count": 0, "last_error": None}]
PROBE_FAILED = "The newsroom no longer passes the probe: HTTP 404"
# Scout text a prompt-injected page could have steered: after a blank line,
# Markdown would turn these into a remote image or a link.
IMAGE = "\n\n![x](https://attacker.example/p.png)"
HOSTILE = draft(40, proposal={
    "lane": "relationship", "action": "new_source", "title": "![](https://attacker.example/t.png) Acme",
    "why": "Ondas bought Acme." + IMAGE, "why_url": "https://ir.ondas.com/news/acme", "notes": "Checked the newsroom." + IMAGE,
    "covered_entity_id": "entity_ondas", "operations": [{"kind": "source_upsert", "value": {**SOURCE["value"], "name": "Acme" + IMAGE}}],
    "probe": {"total_found": 2, "samples": [{"title": "Acme news" + IMAGE, "url": "https://acmerobotics.com/news/a" + IMAGE, "published": "2026-09-28T14:00:00Z"}]},
    "backtest": {"window_days": 60, "results": [{"term": "Acme" + IMAGE, "hits": 1, "samples": [{"title": "Acme wins" + IMAGE, "url": "https://example.com/a", "ts": "2026-09-01T12:00:00Z"}]}],
                 "collisions": [{"term": "Acme" + IMAGE, "example_title": "Acme Brick" + IMAGE}]},
}, owner_text="Track Acme" + IMAGE)
# With Claude after a send-back that carried only edits to the card.
EDITS_ONLY = draft(22, origin="owner", action="request", refine_status="queued", refine_round=1, owner_text="Track Ondas's Acme business",
                   owner_feedback=[{"round": 0, "text": None, "at": "2026-09-30T16:00:00Z", "edited_operations": True}],
                   previous_proposal={"title": "Acme Robotics → Ondas · acquired business"})
NOTE_THEN_EDITS = draft(23, refine_status="queued", refine_round=2, owner_feedback=[
    {"round": 0, "text": "Use the investor newsroom", "at": "2026-09-30T15:00:00Z"},
    {"round": 1, "text": None, "at": "2026-09-30T16:00:00Z", "edited_operations": True}],
    previous_proposal={"title": "Beta Corp → Kratos · customer · every 30 min"})
NOTE_AND_EDITS = draft(24, refine_status="queued", refine_round=1, owner_feedback=[
    {"round": 0, "text": "Watch the product blog too", "at": "2026-09-30T16:00:00Z", "edited_operations": True}],
    previous_proposal={"title": "Gamma → AeroVironment · acquired business"})
# A newsroom-gap card: the company's own newsroom, outside the relationship lane.
GAP_SOURCE = {"kind": "source_upsert", "value": {
    "name": "Athena Security — newsroom", "endpoint": "https://www.athena-security.com/press/", "adapter": "html", "path_prefix": "/press/",
    "entity_ids": ["athena"], "source_role": "company_newsroom", "companyStatus": "private", "cadence_minutes": 60, "configuration_status": "configured"}}
GAP = draft(15, proposal={
    "lane": "relationship", "action": "new_source", "title": "Athena Security newsroom · every 60 min",
    "why": "Athena Security has no configured newsroom; its press page passes the probe.", "why_url": "https://www.athena-security.com/press/",
    "covered_entity_id": None, "counterpart": None, "relationship_kind": None, "dedupe_key": "source:www.athena-security.com/press",
    "operations": [GAP_SOURCE]})
GAP_NONE = draft(16, action="no_change", proposal={"lane": "relationship", "action": "no_change", "title": "Ceva Logistics has no usable newsroom",
                                                   "why": "Its press page is blocked.", "relationship_kind": None, "dedupe_key": "entity:ceva logistics", "operations": []})
# A customer newsroom whose topic filter let nothing through, and a guarded,
# truncated backtest.
CUSTOMER = draft(17, proposal={
    "lane": "relationship", "action": "new_source", "title": "Beta Corp → Kratos · customer · every 30 min",
    "why": "Kratos named Beta Corp as a customer.", "why_url": "https://ir.kratosdefense.com/news/beta", "covered_entity_id": "kratos",
    "counterpart": "Beta Corp", "relationship_kind": "customer", "dedupe_key": "source:beta.example/news",
    "operations": [{"kind": "source_upsert", "value": {**SOURCE["value"], "name": "Beta Corp — newsroom", "source_role": "official_customer_partner",
                                                       "include_terms": ["Kratos"], "relationship": {"covered_entity_id": "kratos", "kind": "customer", "counterpart": "Beta Corp"}}}],
    "probe": {"total_found": 0, "excluded": {"outside_source_scope": 20}, "samples": [], "checked_at": "not a time <b>",
              "unfiltered": {"total_found": 20, "samples": [{"title": "Beta ships the X9", "url": "https://beta.example/news/x9", "published": "2026-09-28T14:00:00Z"}]}},
    "backtest": {"window_days": 60, "results": [
        {"term": "Mistral", "hits": 5000, "context_hits": 40, "truncated": True, "samples": [{"title": "Mistral AI raises", "url": "https://example.com/m", "ts": "2026-09-01T12:00:00Z"}]},
        {"term": "Mistral Defense", "hits": 1, "context_hits": 1, "samples": []}]},
})
# The trial lane (contract P3.1, P3.5): a trial's verdict card, as
# radar-propose stores it, with the recommended verdict's effects.
SCORECARD = {"source_key": "managed_beta", "name": "Beta Corp newsroom", "configuration_status": "configured", "day": 9, "of_days": 21,
             "shown": 4, "avg_grade": 77.6, "grades_70_plus": 3, "grades_below_40": 0, "unique_catches": 9, "duplicates": 3, "collected": 12,
             "last_article": "2026-09-30T17:00:00Z"}
TRIAL_RESULT = draft(50, lane="discovery", action="trial_result", proposal={
    "lane": "discovery", "action": "trial_result", "title": "Beta Corp newsroom trial · promote", "why": "Three trial items graded 70+ by day 9.",
    "why_url": None, "covered_entity_id": None, "counterpart": None, "relationship_kind": None,
    "dedupe_key": "trial:managed_beta:2026-10-21t17:00:00.000z:early_promote", "operations": [], "probe": None, "backtest": None, "notes": None,
    "source_key": "managed_beta", "verdict": "promote", "reason": "early_promote", "scorecard": SCORECARD, "promote_to": {"radar_lane": None}},
    effects=[{"kind": "source_upsert", "target": "managed_beta", "name": "Beta Corp newsroom", "is_new": False,
              "changes": {"radar_lane": ["trial", None], "trial": [{"started_at": "2026-09-30T17:00:00.000Z", "ends_at": "2026-10-21T17:00:00.000Z"}, None]}}])
# A start_trial on the owner's request: a configured newsroom in the trial lane.
START_TRIAL = draft(51, origin="owner", lane="discovery", action="start_trial", owner_text="Trial Beta Corp's newsroom", proposal={
    "lane": "discovery", "action": "start_trial", "title": "Trial: Beta Corp newsroom · every 60 min", "why": "You asked to trial Beta Corp's newsroom.",
    "covered_entity_id": None, "counterpart": None, "relationship_kind": None, "dedupe_key": "source:beta.example/news",
    "operations": [{"kind": "source_upsert", "value": {
        "name": "Beta Corp newsroom", "endpoint": "https://beta.example/news", "adapter": "html", "path_prefix": "/news/", "entity_ids": ["beta"],
        "source_role": "company_newsroom", "companyStatus": "public", "cadence_minutes": 60, "configuration_status": "configured",
        "include_terms": [], "radar_lane": "trial"}}]})
TRIAL_LANE = {"key": "managed_beta", "name": "Beta Corp newsroom", "endpoint": "https://beta.example/news", "radar_lane": "trial",
              "relationship_kind": None, "covered_entity_name": None, "cadence_minutes": 60, "configuration_status": "configured",
              "status": "Collecting", "last_ok": "2026-09-30T17:00:00Z", "last_article": "2026-09-30T15:00:00Z", "fail_count": 0, "last_error": None,
              "trial": {"day": 25, "of_days": 21, "shown": 4, "avg_grade": 61.5, "grades_70_plus": 2, "grades_below_40": 1, "unique_catches": 9,
                        "duplicates": 3, "collected": 12, "last_article": "2026-09-30T15:00:00Z"}}
# The discovery lane (contract P4.6, P4.8): the answer to a missed-story
# request whose story was collected but ranked low, with the diagnosis the
# Worker stamps from its own match and review read.
DIAGNOSIS = {"code": "collected_rejected", "event_id": 4512, "event_title": "Navy orders Skydio X10D drones", "event_url": "https://news.example/skydio-navy",
             "matched_by": "url", "collected_at": "2026-09-29T14:05:00Z", "decision": "rejected", "score": 35, "reason_code": "below_materiality",
             "canonical_event_id": None, "run_id": "run-2026-09-29", "post_id": None}
MISSED_STORY = draft(70, origin="owner", lane="discovery", action="missed_story", owner_text="We missed the Navy's Skydio order",
                     owner_url="https://news.example/skydio-navy", proposal={
                         "lane": "discovery", "action": "missed_story", "title": "Missed: Navy orders Skydio X10D drones",
                         "why": "Collected, but the Grader ranked it below materiality.", "covered_entity_id": None, "counterpart": None,
                         "relationship_kind": None, "dedupe_key": "missed:news.example/skydio-navy", "operations": [], "diagnosis": DIAGNOSIS})
# A start_trial's gate evidence as the Worker stores it (contract P4.5): a
# story you reported nobody collected, one collected 6.5 hours late that you
# graded 78 in the trial panel, and one a source collected first.
EVIDENCE = {"verified": True, "verified_at": "2026-10-01T00:40:00Z", "window_days": 30, "counted": 2, "unique_catches": 1, "misses": [
    {"url": "https://beta.example/news/x9", "first_seen_elsewhere": "2026-09-28T14:00:00Z", "collected_at": None, "lead_hours": None, "late": False,
     "counted": True, "diagnosis": "not_collected_no_source", "owner_request_id": 44, "owner_flagged": True, "owner_grade": None},
    {"url": "https://beta.example/news/y2", "first_seen_elsewhere": "2026-09-20T12:00:00Z", "collected_at": "2026-09-20T18:30:00Z", "lead_hours": 6.5,
     "late": True, "counted": True, "diagnosis": "collected_rejected", "owner_request_id": None, "owner_flagged": False, "owner_grade": 78},
    {"url": "https://beta.example/news/z1", "first_seen_elsewhere": "2026-09-18T12:00:00Z", "collected_at": "2026-09-18T11:00:00Z", "lead_hours": -1,
     "late": False, "counted": False, "diagnosis": "collected_published", "owner_request_id": None, "owner_flagged": False, "owner_grade": None}]}
# Lane health recall by industry (contract P4.3): one audited industry and
# one the rotation has not reached yet.
RECALL = [{"industry_id": "autonomous_vehicles", "name": "Autonomous vehicles", "last_audit_date": "2026-09-30", "found_30d": 12, "captured_30d": 10,
           "late_30d": 2, "recall_pct": 83},
          {"industry_id": "drones", "name": "Drones & UAS", "last_audit_date": None, "found_30d": None, "captured_30d": None, "late_30d": None,
           "recall_pct": None}]
RECALL_COLUMNS = ["Industry", "Last audit", "Found", "Captured", "Late", "Recall"]


class RadarTabTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        self.calls = []
        self.drafts = [NEW_SOURCE, NO_CHANGE, REQUEST, SENT_BACK]
        self.recent = RECENT
        self.lanes = LANES
        self.recall = None
        self.pending_error = None
        self.lanes_error = None
        self.approve_error = None
        self.approve_label = None
        self.request_error = None
        self.to_rules = {"rules_draft_id": 88, "duplicate": False}
        self.to_rules_error = None
        self.undo_result = None
        get_patch = patch("requests.get", side_effect=self.fake_get)
        get_patch.start(); self.addCleanup(get_patch.stop)
        post_patch = patch("requests.post", side_effect=self.fake_post)
        post_patch.start(); self.addCleanup(post_patch.stop)

    def fake_get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs.get("headers")))
        if url.endswith("/health"):
            return StubResponse({"ok": True})
        if url.endswith("/digests"):
            return StubResponse({"daily": [], "weekly": []})
        if "/radar/drafts" in url and "status=recent" in url:
            return StubResponse({"ok": True, "drafts": self.recent})
        if "/radar/drafts" in url and "status=pending" in url:
            if self.pending_error:
                return StubResponse({"ok": False, "error": self.pending_error}, 500)
            return StubResponse({"ok": True, "drafts": self.drafts, "counts": {
                "your_turn": len([d for d in self.drafts if d["refine_status"] == "proposed"]),
                "with_claude": len([d for d in self.drafts if d["refine_status"] == "queued"])}})
        if url.endswith("/radar/lanes"):
            if self.lanes_error:
                return StubResponse({"ok": False, "error": self.lanes_error}, 500)
            return StubResponse({"ok": True, "revision_id": "rev-7", "sources": self.lanes,
                                 **({"recall": self.recall} if self.recall is not None else {})})
        raise AssertionError(f"unexpected request: {url}")

    def fake_post(self, url, **kwargs):
        body = kwargs.get("json") or {}
        self.calls.append(("POST", url, body))
        self.assertEqual(kwargs.get("headers"), {"X-Owner-Pin": "test-pin"})
        if url.endswith("/radar/drafts"):
            if self.request_error:
                return StubResponse({"ok": False, "error": self.request_error}, 400)
            return StubResponse({"ok": True, "draft_id": 31, "duplicate": False})
        draft_id = int(url.split("/")[-2])
        if url.endswith("/to-rules"):
            if self.to_rules_error:
                return StubResponse({"ok": False, "error": self.to_rules_error[1]}, self.to_rules_error[0])
            return StubResponse({"ok": True, "draft_id": draft_id, "label": f"Radar #{draft_id}: Missed story", **self.to_rules})
        if url.endswith("/undo") and self.undo_result:
            return StubResponse(self.undo_result[1], self.undo_result[0])
        if url.endswith("/approve"):
            if self.approve_error:
                return StubResponse({"ok": False, "error": self.approve_error}, 422)
            return StubResponse({"ok": True, "draft_id": draft_id, "revision_id": "rev-8",
                                 "label": self.approve_label or f"Radar #{draft_id}: {TITLE}", "collection": {}})
        if url.endswith("/undo"):
            return StubResponse({"ok": True, "draft_id": draft_id, "revision_id": "rev-9"})
        return StubResponse({"ok": True, "draft_id": draft_id})

    def start(self, pin="test-pin"):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["grader_pin"] = pin
        app.session_state["dashboard_view"] = "Radar"
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def rendered(self, app):
        return "\n".join(m.value for m in app.markdown)

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]

    def composer_submit(self, app):
        form = next(f for f in app.get("form") if f.proto.form.form_id == "radar_composer")
        next(b for b in form.button if b.label == "Send to Claude").click().run()
        self.assertEqual(list(app.exception), [])

    def test_helpers(self):
        # Scout runs at 1:30 PM and 8:30 PM ET.
        self.assertEqual(next_pickup_label(datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)), "~1:30 PM ET")
        self.assertEqual(next_pickup_label(datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)), "~8:30 PM ET")
        self.assertEqual(next_pickup_label(datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)), "tomorrow ~1:30 PM ET")
        self.assertEqual(split_aliases("Acme, Acme Robotics, Inc., ACME Corp"), ["Acme", "Acme Robotics, Inc.", "ACME Corp"])
        groups = classify([NEW_SOURCE, REQUEST, NO_CHANGE, SENT_BACK])
        self.assertEqual([d["id"] for d in groups["your_turn"]], [13, 12], "a send-back that came back goes first")
        self.assertEqual([d["id"] for d in groups["with_claude"]], [20, 21])
        evidence = evidence_html(NEW_SOURCE["proposal"])
        self.assertIn("Probe: 38 posts · 5 excluded · checked Sep 30, 1:35 PM ET · Backtest: 12 matches in 60 days", evidence)
        self.assertIn('<span class="refine-chip warn">Acme also matches “Acme Brick raises prices”</span>', evidence)

    def test_newsroom_gap_cards_say_company_newsroom(self):
        self.assertIn('<span class="loop-kind loop-kind-newsroom">Company newsroom</span><span class="refine-chip">New source</span>', chips_html(GAP))
        self.assertIn('<span class="loop-kind loop-kind-newsroom">Company newsroom</span><span class="refine-chip">No change</span>', chips_html(GAP_NONE))
        self.assertIn("loop-kind-relationship", chips_html(NEW_SOURCE), "a source in the relationship lane")
        self.assertIn("loop-kind-relationship", chips_html(CUSTOMER))
        self.assertIn("loop-kind-discovery", chips_html(NO_CHANGE), "a missed-story answer keeps its lane")
        self.assertIn("loop-kind-relationship", chips_html(draft(18, action="no_change", proposal={
            "lane": "relationship", "action": "no_change", "relationship_kind": "customer", "dedupe_key": "entity:palantir", "operations": []})),
            "a customer already collected is still a relationship card")
        unknown = draft(19, action="fix_source", proposal={"lane": "relationship", "action": "fix_source", "relationship_kind": None,
                                                           "operations": [{"kind": "source_upsert", "value": {"key": "managed_x", "cadence_minutes": 20}}]})
        self.assertIn("loop-kind-relationship", chips_html(unknown), "an update that leaves the lane out keeps one the page cannot see")
        self.drafts = [GAP]
        app = self.start()
        self.assertIn("Company newsroom", self.rendered(app))

    def test_evidence_shows_the_unfiltered_probe_guard_words_and_lower_bounds(self):
        proposal = CUSTOMER["proposal"]
        evidence = evidence_html(proposal)
        self.assertIn("Probe: 0 posts · 20 excluded · 20 without the topic filter · checked not a time &lt;b&gt;"
                      " · Backtest: 5001+ matches in 60 days, 41+ with guard words", evidence)
        samples = samples_html(proposal)
        self.assertIn('<div class="refine-label">From the newsroom, without the topic filter</div>', samples)
        self.assertIn(">Beta ships the X9</a> · Sep 28, 10:00 AM ET", samples)
        self.assertIn("Past items matching “Mistral” · 5000+ matches, 40+ with guard words</div>", samples)
        self.assertEqual(sample_count(proposal), 2)
        plain = {"backtest": {"window_days": 30, "results": [{"term": "Acme", "hits": 1, "samples": []}]}}
        self.assertIn("Backtest: 1 match in 30 days</div>", evidence_html(plain), "no guard words, no lower bound")

    def test_details_show_what_approve_stores_read_only(self):
        source = facts_html("source_upsert", SOURCE["value"])
        self.assertEqual(source, '<div class="rule-meta">Status: configured, collected once approved · Company: private · Role: company newsroom'
                                 ' · Method: html · Article path: /news/ · Lane: relationship</div>')
        self.assertIn("Status: draft, saved but not collected", facts_html("source_upsert", {**SOURCE["value"], "configuration_status": "draft"}))
        self.assertIn("Lane: none (the company&#x27;s own sources)", facts_html("source_upsert", {**SOURCE["value"], "radar_lane": None}))
        self.assertIn("Role: customer or partner newsroom", facts_html("source_upsert", CUSTOMER["proposal"]["operations"][0]["value"]))
        record = facts_html("knowledge_upsert", KNOWLEDGE["value"])
        self.assertEqual(record, '<div class="rule-meta">Kind: subsidiary · Matching: direct · Evidence: <a href="https://ir.ondas.com/news/acme"'
                                 ' target="_blank" rel="noopener noreferrer">release ↗</a> as of 2026-10-02</div>')
        self.assertIn("Evidence: rubric/companies/RCAT.md as of 2026-09-05",
                      facts_html("knowledge_upsert", {**KNOWLEDGE["value"], "evidence_source": "rubric/companies/RCAT.md", "evidence_as_of": "2026-09-05"}))
        self.assertEqual(facts_html("entity_upsert", {"name": "Acme"}), "")
        app = self.start()
        app.toggle("radar_details_12").set_value(True).run()
        rendered = self.rendered(app)
        self.assertIn(record, rendered)
        self.assertIn(source, rendered)

    def test_navigation_replaces_universe_with_radar(self):
        app = self.start()
        view = next(radio for radio in app.radio if radio.label == "Dashboard view")
        self.assertEqual(list(view.options), ["Feed", "Rejected", "Rules", "Radar"])

    def test_pin_gate_makes_no_radar_calls(self):
        app = self.start(pin="")
        self.assertIn("Enter your Grader PIN in Owner mode", self.rendered(app))
        self.assertFalse(any("/radar" in c[1] for c in self.calls))

    def test_page_reads_with_the_pin_header_and_summarizes(self):
        app = self.start()
        radar_calls = [c for c in self.calls if "/radar" in c[1]]
        self.assertTrue(radar_calls and all(c[2] == {"X-Owner-Pin": "test-pin"} for c in radar_calls))
        self.assertTrue(any(c.value.startswith("2 for you · 2 with Claude · next Claude run ") for c in app.caption))
        rendered = self.rendered(app)
        self.assertLess(rendered.index("Your turn · 2"), rendered.index("With Claude · 2"))

    def test_composer_sends_a_track_request_or_a_missed_story(self):
        app = self.start()
        self.composer_submit(app)
        self.assertEqual(self.posts(), [], "empty words are not sent")
        app.radio("radar_kind").set_value("We missed this story")
        app.text_area("radar_text").set_value("The Navy's Skydio order never reached the digest")
        self.composer_submit(app)
        self.assertEqual(self.posts(), [], "a missed story needs its link")
        self.assertTrue(any("Paste the story's link" in i.value for i in app.info))
        app.text_input("radar_url").set_value("https://news.example/skydio-navy")
        self.composer_submit(app)
        post = self.posts()[-1]
        self.assertTrue(post[1].endswith("/radar/drafts"))
        self.assertEqual(post[2], {"text": "The Navy's Skydio order never reached the digest", "kind": "missed", "url": "https://news.example/skydio-navy"})
        self.assertTrue(any(s.value.startswith("Request #31 sent to Claude · back ") and s.value.endswith(" ET") for s in app.success))
        app.radio("radar_kind").set_value("Track a company or relationship")
        app.text_area("radar_text").set_value("Track Ondas's new Acme Robotics business")
        app.text_input("radar_url").set_value("")
        self.composer_submit(app)
        self.assertEqual(self.posts()[-1][2], {"text": "Track Ondas's new Acme Robotics business", "kind": "track"}, "the link is optional when tracking")

    def test_cards_show_both_lanes_their_action_and_the_evidence(self):
        app = self.start()
        rendered = self.rendered(app)
        self.assertIn('<span class="loop-kind loop-kind-relationship">Relationship source</span><span class="refine-chip">New source</span>', rendered)
        self.assertIn('<span class="loop-kind loop-kind-discovery">Discovery lane</span><span class="refine-chip">No change</span>'
                      '<span class="refine-chip applied">your edit applied</span>', rendered)
        self.assertLess(rendered.index("Skydio is already collected"), rendered.index(TITLE), "the send-back that came back is first")
        self.assertIn(f"<strong>{TITLE}</strong>", rendered)
        self.assertIn('Ondas announced the acquisition of Acme Robotics on Oct 2, 2026. · '
                      '<a href="https://ir.ondas.com/news/acme" target="_blank" rel="noopener noreferrer">source ↗</a>', rendered)
        self.assertIn("Probe: 38 posts · 5 excluded · checked Sep 30, 1:35 PM ET · Backtest: 12 matches in 60 days", rendered)
        self.assertIn("Acme also matches", rendered)
        self.assertIn("Samples · 2", "\n".join(e.label for e in app.expander))
        self.assertIn("Acme ships &lt;b&gt;Model X&lt;/b&gt;", rendered)
        buttons = {b.key for b in app.button}
        self.assertTrue({"radar_approve_12", "radar_sendback_12", "radar_discard_12"} <= buttons)
        self.assertNotIn("radar_approve_13", buttons, "no change: only Send back and Discard")
        self.assertTrue({"radar_sendback_13", "radar_discard_13"} <= buttons)

    def test_user_text_is_escaped(self):
        app = self.start()
        app.toggle("radar_details_13").set_value(True).run()
        rendered = self.rendered(app)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<Shield AI>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; we missed the Navy&#x27;s Skydio order", rendered)
        self.assertIn("Your note (round 1): Look again at the &lt;Navy&gt; release", rendered)
        self.assertIn("You sent: Track &lt;Shield AI&gt;&#x27;s customers", rendered)
        self.assertIn("You sent: Use the investor newsroom instead", rendered)

    def test_approve_sends_the_owners_edits_only(self):
        app = self.start()
        app.button("radar_approve_12").click().run()
        self.assertEqual(list(app.exception), [])
        post = self.posts()[-1]
        self.assertTrue(post[1].endswith("/radar/drafts/12/approve"))
        self.assertEqual(post[2], {}, "without edits, Claude's operations stand")
        # The Worker's label is Markdown-escaped; it renders as "Radar #12: …".
        self.assertTrue(any(s.value == f"Approved · Radar \\#12\\:​ {TITLE} · undo within 24 h" for s in app.success))

        # Each step starts a fresh session: Streamlit 1.37's AppTest drops the
        # next widget interaction inside a fragment after that fragment called
        # st.rerun (the Rules tab's tests use one action per session too).
        app = self.start()
        app.toggle("radar_details_12").set_value(True).run()
        self.assertEqual(app.text_input("radar_12_op1_endpoint").value, "https://acmerobotics.com/news")
        self.assertEqual(app.number_input("radar_12_op1_cadence").value, 30)
        self.assertEqual(app.number_input("radar_12_op1_cadence").max, 30, "a relationship source is checked every 8 to 30 minutes")
        sent = len(self.posts())
        app.button("radar_approve_12").click().run()
        self.assertEqual(len(self.posts()), sent + 1, "Approve posts again")
        self.assertEqual(self.posts()[-1][2], {}, "opening Details changes nothing")

        app = self.start()
        app.toggle("radar_details_12").set_value(True).run()
        app.text_input("radar_12_op1_endpoint").set_value("https://acmerobotics.com/press")
        app.text_area("radar_12_op1_include").set_value("Ondas\n\nAcme Robotics\n")
        app.number_input("radar_12_op1_cadence").set_value(20)
        sent = len(self.posts())
        app.button("radar_approve_12").click().run()
        self.assertEqual(len(self.posts()), sent + 1, "Approve posts the edits")
        operations = self.posts()[-1][2]["operations"]
        self.assertEqual(operations[0], KNOWLEDGE, "an untouched operation goes back exactly as written")
        expected = copy.deepcopy(SOURCE)
        expected["value"].update(endpoint="https://acmerobotics.com/press", include_terms=["Ondas", "Acme Robotics"], cadence_minutes=20)
        self.assertEqual(operations[1], expected)

    def test_cadence_field_offers_only_what_the_worker_accepts(self):
        proposal = {"covered_entity_id": "entity_ondas"}
        relationship = draft(1, lane="relationship", proposal=proposal)
        discovery = draft(2, lane="discovery", proposal=proposal)
        self.assertEqual(cadence_ceiling(SOURCE["value"], NEW_SOURCE), 30)
        self.assertEqual(cadence_ceiling({**SOURCE["value"], "cadence_minutes": 45}, NEW_SOURCE), 45,
                         "a cadence the Worker already accepted (a raised setting) is never clamped")
        existing = {"key": "managed_acme", "entity_ids": ["entity_ondas"], "companyStatus": "private", "cadence_minutes": 30}
        self.assertEqual(cadence_ceiling(existing, relationship), 30, "an edit that leaves the lane out keeps the stored one")
        self.assertEqual(cadence_ceiling({**existing, "radar_lane": None, "cadence_minutes": 8}, relationship), 8, "null takes the source out of the lane")
        new = {"entity_ids": ["entity_ondas"], "companyStatus": "public", "cadence_minutes": 8}
        self.assertEqual(cadence_ceiling(new, relationship), 8, "a covered company's newsroom")
        self.assertEqual(cadence_ceiling({**new, "companyStatus": "noncompany", "cadence_minutes": 60}, discovery), 120)
        self.assertEqual(cadence_ceiling({**new, "entity_ids": ["entity_other"], "cadence_minutes": 30}, discovery), 60, "another public company")
        self.assertEqual(cadence_ceiling({**new, "entity_ids": ["entity_other"], "companyStatus": "private", "cadence_minutes": 30}, discovery), 120)

    def test_include_terms_label_follows_the_relationship_filter(self):
        self.assertEqual(EXTRA_NAMES_FIELD, (
            "Extra names to keep (one per line)",
            "Posts naming the covered company, its subsidiaries or products, or with a deal word plus an autonomy topic, are kept automatically."
            " A post naming one of these is kept too."))
        self.assertEqual(TOPIC_FILTER_FIELD, ("Topic filter words (one per line)",
                                              "A post must mention at least one of these. Leave empty to collect every company update."))
        customer = CUSTOMER["proposal"]["operations"][0]["value"]
        self.assertEqual(include_terms_field(customer, CUSTOMER), EXTRA_NAMES_FIELD)
        self.assertEqual(include_terms_field(SOURCE["value"], NEW_SOURCE), TOPIC_FILTER_FIELD, "an acquired business keeps every post")
        for kind in ("partner", "supplier", "program", None, ""):
            value = {**SOURCE["value"], "relationship": {**SOURCE["value"]["relationship"], "kind": kind}}
            self.assertEqual(include_terms_field(value, NEW_SOURCE), EXTRA_NAMES_FIELD, f"kind {kind!r}: the value's own relationship wins")
        self.assertEqual(include_terms_field({**customer, "radar_lane": None, "relationship": None}, CUSTOMER), TOPIC_FILTER_FIELD,
                         "null takes the source out of the lane")
        self.assertEqual(include_terms_field(GAP_SOURCE["value"], GAP), TOPIC_FILTER_FIELD, "a company's own newsroom")
        # An edit to an existing source that leaves the lane and the
        # relationship out keeps the stored ones: the card's kind decides.
        existing = {"key": "managed_beta", "include_terms": ["Kratos"]}
        self.assertEqual(include_terms_field(existing, CUSTOMER), EXTRA_NAMES_FIELD)
        self.assertEqual(include_terms_field(existing, NEW_SOURCE), TOPIC_FILTER_FIELD)
        self.assertEqual(include_terms_field(existing, draft(3, lane="discovery", proposal={"relationship_kind": "customer"})), TOPIC_FILTER_FIELD)
        self.assertEqual(include_terms_field({"include_terms": []}, CUSTOMER), TOPIC_FILTER_FIELD, "a new source without a lane is outside it")
        self.assertEqual(include_terms_field(existing), TOPIC_FILTER_FIELD, "no card")

    def test_details_call_a_customer_sources_include_terms_extra_names(self):
        # One action per session (Streamlit 1.37 AppTest).
        self.drafts = [CUSTOMER]
        app = self.start()
        app.toggle("radar_details_17").set_value(True).run()
        self.assertEqual(list(app.exception), [])
        field = app.text_area("radar_17_op0_include")
        self.assertEqual((field.label, field.help), EXTRA_NAMES_FIELD)
        self.assertEqual(field.value, "Kratos", "the same text as before")

    def test_details_keep_the_topic_filter_label_for_an_acquired_business(self):
        app = self.start()
        app.toggle("radar_details_12").set_value(True).run()
        self.assertEqual(list(app.exception), [])
        field = app.text_area("radar_12_op1_include")
        self.assertEqual((field.label, field.help), TOPIC_FILTER_FIELD)

    def test_an_edited_extra_name_is_parsed_like_a_topic_word(self):
        self.drafts = [CUSTOMER]
        app = self.start()
        app.toggle("radar_details_17").set_value(True).run()
        app.text_area("radar_17_op0_include").set_value("Kratos\n\nKratos Defense\n")
        app.button("radar_approve_17").click().run()
        self.assertEqual(list(app.exception), [])
        operations = self.posts()[-1][2]["operations"]
        expected = copy.deepcopy(CUSTOMER["proposal"]["operations"][0])
        expected["value"]["include_terms"] = ["Kratos", "Kratos Defense"]
        self.assertEqual(operations, [expected])

    def test_a_failed_reprobe_stays_on_the_card(self):
        self.approve_error = PROBE_FAILED
        app = self.start()
        app.button("radar_approve_12").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual([e.value for e in app.error], [md_escape(PROBE_FAILED)])
        self.assertEqual(list(app.success), [])
        self.assertTrue(any(b.key == "radar_approve_12" for b in app.button), "the card is still there")

    def test_send_back_needs_a_note_or_an_edit_and_carries_both(self):
        app = self.start()
        app.button("radar_sendback_12").click().run()
        self.assertEqual(self.posts(), [], "nothing changed, nothing sent")
        self.assertTrue(any("Add a note or edit the Details" in i.value for i in app.info))
        app.text_input("radar_note_12").set_value("Also watch Acme's product blog")
        app.button("radar_sendback_12").click().run()
        post = self.posts()[-1]
        self.assertTrue(post[1].endswith("/radar/drafts/12/refine"))
        self.assertEqual(post[2], {"feedback": "Also watch Acme's product blog"})
        self.assertTrue(any(s.value.startswith("#12 sent back · back ") for s in app.success))

        app = self.start()
        app.toggle("radar_details_12").set_value(True).run()
        self.assertEqual(app.text_input("radar_12_op0_aliases").value, "Acme Robotics, Acme Robotics, Inc., Acme")
        app.text_input("radar_12_op0_aliases").set_value("Acme Robotics, Acme Robotics, Inc.")
        app.text_area("radar_12_op0_context").set_value("robot\ndrone")
        app.button("radar_sendback_12").click().run()
        payload = self.posts()[-1][2]
        self.assertNotIn("feedback", payload)
        self.assertEqual(payload["operations"][0]["value"]["aliases"], ["Acme Robotics", "Acme Robotics, Inc."])
        self.assertEqual(payload["operations"][0]["value"]["context_terms"], ["robot", "drone"])
        self.assertEqual(payload["operations"][1], SOURCE)
        self.assertTrue(any("sent back with your edits" in s.value for s in app.success))

    def test_with_claude_shows_the_latest_send_back(self):
        self.assertEqual(sent_words(EDITS_ONLY), "", "edits only: no words, not the original request")
        self.assertEqual(sent_words(NOTE_THEN_EDITS), "", "edits only: not the earlier round's note")
        self.assertEqual(sent_words(NOTE_AND_EDITS), "Watch the product blog too")
        self.assertEqual(sent_words(REQUEST), "Track <Shield AI>'s customers")
        self.drafts = [EDITS_ONLY, NOTE_THEN_EDITS, NOTE_AND_EDITS]
        app = self.start()
        rendered = self.rendered(app)
        self.assertIn("Your edits to: Acme Robotics → Ondas · acquired business", rendered)
        self.assertIn("Your edits to: Beta Corp → Kratos · customer · every 30 min", rendered)
        self.assertIn("You sent: Watch the product blog too · with your edits to the card", rendered)
        self.assertNotIn("You sent: Track Ondas", rendered)
        self.assertNotIn("Use the investor newsroom", rendered)
        history = history_html(draft(25, owner_feedback=[*NOTE_THEN_EDITS["owner_feedback"],
                                                        {**NOTE_AND_EDITS["owner_feedback"][0], "round": 2}]))
        self.assertIn("Your note (round 0): Use the investor newsroom", history)
        self.assertIn("You edited the card (round 1)", history)
        self.assertIn("Your note (round 2) · with your edits to the card: Watch the product blog too", history)

    def test_a_card_shows_every_existing_record_it_would_change(self):
        # A card titled as a new newsroom that would pause another source.
        misleading = draft(14, proposal={
            "lane": "relationship", "action": "retire_source", "title": "Acme Robotics newsroom", "why": "Acme runs a newsroom.",
            "operations": [{"kind": "source_upsert", "value": {"key": "managed_draganfly_news", "configuration_status": "paused"}}]},
            effects=[{"kind": "source_upsert", "target": "managed_draganfly_news", "name": "Draganfly <news>", "is_new": False,
                      "changes": {"configuration_status": ["configured", "paused"], "entity_ids": [["draganfly"], ["redcat"]], "knowledge_ids": [[], ["x"]]}},
                     {"kind": "knowledge_upsert", "target": None, "name": "Acme", "is_new": True, "changes": {}},
                     {"kind": "entity_upsert", "target": "redcat", "name": "Red Cat", "is_new": False, "changes": {}},
                     {"kind": "knowledge_upsert", "target": "k1", "name": "Teal", "is_new": False,
                      "changes": {"evidence_note": ["a", "b"], "evidence_as_of": ["2026-09-05", "2026-10-01"]}}])
        self.drafts = [misleading]
        app = self.start()
        rendered = self.rendered(app)
        self.assertIn('<span class="refine-chip warn">Changes existing source: Draganfly &lt;news&gt; · configured → paused, companies, relationship links</span>'
                      '<span class="refine-chip warn">Changes existing relationship record: Teal · evidence</span>', rendered)
        self.assertNotIn("Changes existing company", rendered, "a record the card leaves unchanged is not flagged")
        self.assertLess(rendered.index("Acme runs a newsroom."), rendered.index("Changes existing source"), "right under the why")
        self.assertFalse(app.toggle("radar_details_14").value, "shown with Details closed")
        self.assertEqual(effects_html(NEW_SOURCE), "", "a card that only adds records shows no warning")

    def test_scout_text_cannot_leave_its_html_block(self):
        self.drafts, self.recent = [HOSTILE], []
        self.approve_label = "Radar #40: ![](https://attacker.example/t.png) [Acme](https://phish.example)"
        app = self.start()
        app.toggle("radar_details_40").set_value(True).run()
        hostile = [m.value for m in app.markdown if "attacker.example" in m.value]
        self.assertEqual(len(hostile), 4, "card, samples, Details history and operation label")
        for value in hostile:
            # A blank line would end the raw HTML block and let Markdown
            # render the rest; nothing in the block spans lines at all.
            self.assertNotIn("\n", value)
        rendered = self.rendered(app)
        self.assertIn("Ondas bought Acme. ![x](https://attacker.example/p.png)", rendered)
        self.assertIn('<a href="https://acmerobotics.com/news/a![x](https://attacker.example/p.png)"', rendered)
        self.assertIn("Claude’s note: Checked the newsroom. ![x]", rendered)
        self.assertIn('Your words</div><div class="refine-owner">Track Acme ![x]', rendered)
        # Backslash escapes keep Markdown literal; a zero-width space ("|"
        # below) after ':' and before '.' stops GFM linking bare addresses.
        self.assertEqual(md_escape("Radar #40: ![](https://a.example/t.png)\n\nwww.b.example c@d.example"),
                         r"Radar \#40\:| \!\[\]\(https\:|\/\/a|\.example\/t|\.png\) www|\.b|\.example c\@d|\.example".replace("|", "​"))
        app.button("radar_approve_40").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual([s.value for s in app.success], [
            r"Approved · Radar \#40\:| \!\[\]\(https\:|\/\/attacker|\.example\/t|\.png\) \[Acme\]\(https\:|\/\/phish|\.example\) · undo within 24 h"
            .replace("|", "​")])

    def test_discard_and_withdraw_reject_the_draft(self):
        app = self.start()
        app.button("radar_discard_12").click().run()
        self.assertTrue(self.posts()[-1][1].endswith("/radar/drafts/12/reject"))
        self.assertTrue(any("#12 discarded · undo within 24 h" in s.value for s in app.success))
        app.button("radar_withdraw_20").click().run()
        post = self.posts()[-1]
        self.assertTrue(post[1].endswith("/radar/drafts/20/reject"))
        self.assertEqual(post[2], {})
        self.assertTrue(any("#20 withdrawn · undo within 24 h" in s.value for s in app.success))

    def test_anything_decided_in_the_last_day_can_be_undone(self):
        app = self.start()
        self.assertIn("Just decided · 2 · undo within 24 h", "\n".join(e.label for e in app.expander))
        rendered = self.rendered(app)
        self.assertIn("Approved #9 · Sep 30, 2:05 PM ET", rendered)
        self.assertIn("Discarded #8", rendered)
        keys = {b.key for b in app.button}
        self.assertIn("radar_undo_9", keys)
        self.assertNotIn("radar_undo_8", keys, "no undo once the window has passed")
        app.button("radar_undo_9").click().run()
        self.assertTrue(self.posts()[-1][1].endswith("/radar/drafts/9/undo"))
        self.assertTrue(any(s.value.startswith("Undone · #9 is back in Radar") for s in app.success))

    def test_lane_health_table(self):
        app = self.start()
        self.assertIn("Lane health", [e.label for e in app.expander])
        table = app.dataframe[0].value
        self.assertEqual(list(table.columns), ["Source", "Covered company", "Kind", "Every (min)", "Status", "Last check", "Last article"])
        self.assertEqual(table.iloc[0].tolist(), ["Acme Robotics newsroom", "Ondas", "Acquired", 30, "Collecting", "Sep 30, 1:00 PM ET", "Sep 29, 11:00 AM ET"])
        self.assertEqual(len(app.dataframe), 1, "no trial source, no trial table")

    def test_lane_health_lists_trial_sources_in_a_second_table(self):
        # A trial past its end (due), a retired one (paused: never due) and
        # one whose scorecard has no numbers yet.
        retired = {**TRIAL_LANE, "key": "managed_gamma", "name": "Gamma newsroom", "configuration_status": "paused", "status": "Paused",
                   "trial": {**TRIAL_LANE["trial"], "day": 30, "avg_grade": 33.4}}
        fresh = {**TRIAL_LANE, "key": "managed_delta", "name": "Delta newsroom",
                 "trial": {"day": 1, "of_days": 21, "shown": 0, "avg_grade": None, "grades_70_plus": 0, "grades_below_40": 0,
                           "unique_catches": None, "duplicates": None, "collected": 0, "last_article": None}}
        self.lanes = [{**LANES[0], "trial": None}, TRIAL_LANE, retired, fresh]
        app = self.start()
        table = app.dataframe[0].value
        self.assertEqual(list(table.columns), ["Source", "Covered company", "Kind", "Every (min)", "Status", "Last check", "Last article"])
        self.assertEqual(table.iloc[0].tolist(), ["Acme Robotics newsroom", "Ondas", "Acquired", 30, "Collecting", "Sep 30, 1:00 PM ET", "Sep 29, 11:00 AM ET"])
        self.assertEqual(table.iloc[1].tolist(), ["Beta Corp newsroom", "—", "Trial", 60, "Collecting", "Sep 30, 1:00 PM ET", "Sep 30, 11:00 AM ET"])
        self.assertEqual(table["Kind"].tolist(), ["Acquired", "Trial", "Trial", "Trial"])
        self.assertIn("Trial sources", [c.value for c in app.caption])
        trials = app.dataframe[1].value
        self.assertEqual(list(trials.columns), ["Source", "Day", "Shown", "Avg grade", "70+", "<40", "Unique", "Duplicates", "Collected"])
        self.assertEqual(trials.values.tolist(), [
            ["Beta Corp newsroom", "25/21 · due", "4", "62", "2", "1", "9", "3", "12"],
            ["Gamma newsroom", "30/21", "4", "33", "2", "1", "9", "3", "12"],
            ["Delta newsroom", "1/21", "0", "—", "0", "0", "—", "—", "0"]])
        self.assertEqual(trial_day({"trial": {"day": None, "of_days": 21}}), "—")
        self.assertEqual(trial_day({"trial": {"day": 21, "of_days": 21}, "configuration_status": "configured"}), "21/21",
                         "the last day; due from ends_at, which starts day 22")
        self.assertEqual(trial_day({"trial": {"day": 22, "of_days": 21}, "configuration_status": "configured"}), "22/21 · due")
        self.assertEqual([average_text(v) for v in (61.5, 62.5, 70, None, True, "70", float("nan"), float("inf"))],
                         ["62", "63", "70", "—", "—", "—", "—", "—"])

    def test_lane_health_shows_7_day_counts_when_the_worker_sends_them(self):
        # A managed source with counts, and a listed source outside the
        # managed manifest, which the Worker reports as null.
        self.lanes = [{**LANES[0], "kept_7d": 12, "excluded_7d": 5,
                       "excluded_reasons_7d": {"outside_relationship_scope": 4, "external_media": 1}},
                      {**LANES[0], "key": "beta_news", "name": "Beta Corp newsroom", "relationship_kind": "customer", "covered_entity_name": "Kratos",
                       "kept_7d": None, "excluded_7d": None, "excluded_reasons_7d": None}]
        app = self.start()
        table = app.dataframe[0].value
        self.assertEqual(list(table.columns), ["Source", "Covered company", "Kind", "Every (min)", "Status", "Last check", "Last article",
                                               "Kept (7d)", "Filtered (7d)"])
        self.assertEqual(table.iloc[0].tolist(), ["Acme Robotics newsroom", "Ondas", "Acquired", 30, "Collecting", "Sep 30, 1:00 PM ET",
                                                  "Sep 29, 11:00 AM ET", "12", "5"])
        self.assertEqual(table.iloc[1].tolist()[-2:], ["—", "—"])
        self.assertNotIn("outside_relationship_scope", table.to_string(), "reasons are not shown in phase 2")
        self.assertEqual([count_text(v) for v in (0, 7, None, True, "3", 2.5)], ["0", "7", "—", "—", "—", "—"])
        self.assertEqual(count_text({}.get("kept_7d")), "—", "a missing field")

    def test_malformed_evidence_lists_never_stop_the_tab(self):
        # Scout summaries the Worker stored before it checked these lists: a
        # number, a flag or a string where a list belongs.
        def bad(probe=None, backtest=None):
            proposal = copy.deepcopy(NEW_SOURCE["proposal"])
            proposal["probe"].update(probe or {})
            proposal["backtest"].update(backtest or {})
            return {**NEW_SOURCE, "proposal": proposal}
        variants = [bad(backtest={"results": 3}), bad(probe={"samples": 3}), bad(probe={"unfiltered": {"total_found": 2, "samples": True}}),
                    bad(backtest={"collisions": 5}), bad(probe={"samples": "abc"}), bad(backtest={"results": [{"term": "Acme", "hits": 1, "samples": "abc"}]})]
        for variant in variants:
            proposal = variant["proposal"]
            evidence_html(proposal)
            samples = samples_html(proposal)
            self.assertEqual(sample_count(proposal), samples.count('<div class="refine-note">'), "the count is what the list shows")
            self.drafts = [variant, REQUEST, SENT_BACK]
            self.calls.clear()
            app = self.start()
            buttons = {b.key for b in app.button}
            self.assertTrue({"radar_approve_12", "radar_sendback_12", "radar_discard_12", "radar_withdraw_20", "radar_withdraw_21"} <= buttons)
            self.assertIn("Lane health", [e.label for e in app.expander])
        self.assertEqual(sample_count(bad(probe={"samples": "abc"})["proposal"]), 1, "a string is no list of samples")

    def test_dates_without_a_time_keep_their_day(self):
        # The Worker stores a newsroom's date-only '2026-09-28' as midnight UTC.
        self.assertEqual(short_time("2026-09-28T00:00:00.000Z"), "Sep 28")
        self.assertEqual(short_time("2026-09-28"), "Sep 28")
        self.assertEqual(short_time("2026-09-28T14:00:00Z"), "Sep 28, 10:00 AM ET")
        self.assertEqual(short_time("2026-09-28T00:00:01Z"), "Sep 27, 8:00 PM ET")
        proposal = {"probe": {"total_found": 1, "samples": [{"title": "Acme ships Model X", "url": "https://acmerobotics.com/news/x", "published": "2026-09-28T00:00:00.000Z"}]}}
        self.assertIn(">Acme ships Model X</a> · Sep 28</div>", samples_html(proposal))

    def test_details_show_the_status_approve_saves(self):
        unset = {k: v for k, v in GAP_SOURCE["value"].items() if k != "configuration_status"}
        self.assertTrue(facts_html("source_upsert", unset).startswith('<div class="rule-meta">Status: draft, saved but not collected · '),
                        "Approve saves a source without a status as a draft")
        self.assertIn("Status: needs an adapter, not collected", facts_html("source_upsert", {**GAP_SOURCE["value"], "configuration_status": "needs_adapter"}))
        self.assertNotIn("Status", facts_html("source_upsert", {"key": "redcat", "entity_ids": ["redcat"], "tracking_notes": ""}),
                         "a protected source's routing-only value keeps its status")

    def test_an_approved_newsroom_gap_stays_a_company_newsroom(self):
        # Approval pins the new source's key and, outside the lane, radar_lane: null.
        pinned = {"kind": "source_upsert", "value": {**GAP_SOURCE["value"], "key": "managed_abc", "radar_lane": None}}
        approved = draft(15, status="approved", decided_at="2026-09-30T18:05:00Z", undo_available=True,
                         proposal={**GAP["proposal"], "operations": [pinned]})
        undone = {**approved, "status": "pending", "decided_at": None, "undo_available": False}
        for card in (approved, undone):
            self.assertIn('<span class="loop-kind loop-kind-newsroom">Company newsroom</span>', chips_html(card))
        covered = {**pinned["value"], "entity_ids": ["ondas"], "cadence_minutes": 8}
        self.assertEqual(cadence_ceiling(covered, {**undone, "proposal": {**undone["proposal"], "covered_entity_id": "ondas"}}), 8,
                         "a covered company's own newsroom, as the Worker checks it")
        self.recent = [approved]
        app = self.start()
        self.assertIn("Company newsroom", self.rendered(app))

    def test_effects_name_every_field_the_worker_reports(self):
        changed = draft(14, effects=[{"kind": "source_upsert", "target": "managed_amazon_news", "name": "Amazon — official news", "is_new": False,
                                      "changes": {"relationship": [None, {}], "industry_ids": [[], ["defense_tech"]], "config": [{}, {"include_categories": ["Investors"]}]}}])
        self.assertIn("Changes existing source: Amazon — official news · relationship, industries, collection settings", effects_html(changed))

    def test_empty_queue_still_shows_the_composer_and_lane_health(self):
        self.drafts, self.recent, self.lanes = [], [], []
        app = self.start()
        self.assertTrue(any(f.proto.form.form_id == "radar_composer" for f in app.get("form")))
        captions = "\n".join(c.value for c in app.caption)
        self.assertIn("0 for you · 0 with Claude", captions)
        self.assertIn("Nothing waiting.", captions)
        self.assertIn("No Radar sources yet.", captions)

    # ------------------------------------------------------------ trial lane

    def test_a_trial_result_card_shows_the_scorecard_and_three_verdicts(self):
        self.drafts = [TRIAL_RESULT]
        app = self.start()
        rendered = self.rendered(app)
        self.assertIn('<span class="loop-kind loop-kind-discovery">Discovery lane</span><span class="refine-chip">Trial result</span>', rendered)
        self.assertIn('<span class="refine-chip">Early: 3 grades of 70+</span>', rendered)
        self.assertIn('<div class="rule-meta">Day 9 of 21 · 4 shown in the panel · average grade 78 · 3 graded 70+ · 0 below 40</div>'
                      '<div class="rule-meta">12 collected · 9 unique · 3 duplicates · last article Sep 30, 1:00 PM ET</div>'
                      '<div class="rule-meta">Claude recommends Promote · Promote: becomes a regular source</div>', rendered)
        # The Worker's effects are those of the recommended verdict.
        self.assertIn("Changes existing source: Beta Corp newsroom · lane, trial dates", rendered)
        buttons = {b.key: b for b in app.button}
        self.assertEqual([buttons[k].label for k in ("radar_promote_50", "radar_extend_50", "radar_retire_50")], ["Promote", "Extend 21 days", "Retire"])
        self.assertEqual([buttons[k].proto.type for k in ("radar_promote_50", "radar_extend_50", "radar_retire_50")], ["primary", "secondary", "secondary"],
                         "Claude's pick is the primary button")
        self.assertIn("radar_sendback_50", buttons)
        self.assertNotIn("radar_approve_50", buttons, "no Approve: the owner picks a verdict")
        self.assertNotIn("radar_discard_50", buttons, "no Discard: the trial stays due until it is ended")
        self.assertEqual(self.posts(), [])

    def test_each_trial_verdict_posts_exactly_the_verdict(self):
        # One click per session (Streamlit 1.37 AppTest).
        self.drafts = [TRIAL_RESULT]
        for verdict, done in (("promote", "Promoted"), ("extend", "Extended"), ("retire", "Retired")):
            with self.subTest(verdict=verdict):
                self.approve_label = f"Radar #50: Beta Corp newsroom trial · {verdict}"
                app = self.start()
                app.button(f"radar_{verdict}_50").click().run()
                self.assertEqual(list(app.exception), [])
                url, body = self.posts()[-1][1:]
                self.assertTrue(url.endswith("/radar/drafts/50/approve"))
                self.assertEqual(body, {"verdict": verdict})
                self.assertEqual([s.value for s in app.success],
                                 [f"{done} · Radar \\#50\\:​ Beta Corp newsroom trial · {verdict} · undo within 24 h"])
        self.assertEqual(len(self.posts()), 3)

    def test_a_refused_verdict_stays_on_the_card(self):
        self.drafts = [TRIAL_RESULT]
        self.approve_error = "The relationship lane is full."
        app = self.start()
        app.button("radar_extend_50").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual([e.value for e in app.error], [md_escape("The relationship lane is full.")])
        self.assertTrue(any(b.key == "radar_extend_50" for b in app.button))

    def test_a_refusal_quoting_a_hostile_source_name_is_plain_text(self):
        # A verdict on a source that has left the trial lane: the Worker
        # answers 422 with the name the Scout wrote from web content. st.error
        # renders Markdown, so unescaped it would load the image and show the
        # link inside the error banner.
        self.drafts = [TRIAL_RESULT]
        self.approve_error = ("Acme ![x](https://attacker.example/p.png) [Re-enter PIN](https://attacker.example/login)"
                              " is no longer in the trial lane.")
        app = self.start()
        app.button("radar_promote_50").click().run()
        self.assertEqual(list(app.exception), [])
        shown = [e.value for e in app.error]
        self.assertEqual(shown, [(r"Acme \!\[x\]\(https\:|\/\/attacker|\.example\/p|\.png\) \[Re\-enter PIN\]\(https\:|\/\/attacker|\.example\/login\)"
                                  r" is no longer in the trial lane|\.").replace("|", "​")])
        self.assertNotIn("![", shown[0])
        self.assertNotIn("](", shown[0])
        self.assertEqual(list(app.success), [])
        self.assertTrue(any(b.key == "radar_promote_50" for b in app.button), "the card is still there")

    def test_list_and_lane_health_errors_are_plain_text(self):
        hostile = "Lanes unavailable: ![x](https://attacker.example/p.png)"
        self.lanes_error = hostile
        app = self.start()
        self.assertEqual([e.value for e in app.error], [md_escape(hostile)], "Lane health")
        self.assertNotIn("](", app.error[0].value)
        self.pending_error = hostile
        app = self.start()
        self.assertEqual([e.value for e in app.error], [md_escape(hostile)], "the draft list; Lane health is not reached")
        self.assertNotIn("](", app.error[0].value)

    def test_a_trial_result_is_sent_back_with_a_note_only(self):
        self.drafts = [TRIAL_RESULT]
        app = self.start()
        app.button("radar_sendback_50").click().run()
        self.assertEqual(self.posts(), [])
        self.assertTrue(any(i.value == "Add a note, so Claude knows what to change." for i in app.info))
        app = self.start()
        app.toggle("radar_details_50").set_value(True).run()
        app.text_input("radar_note_50").set_value("Promote it to a relationship source of Kratos")
        app.button("radar_sendback_50").click().run()
        self.assertEqual(list(app.exception), [])
        url, body = self.posts()[-1][1:]
        self.assertTrue(url.endswith("/radar/drafts/50/refine"))
        self.assertEqual(body, {"feedback": "Promote it to a relationship source of Kratos"})

    def test_an_undone_trial_result_offers_no_operation_to_edit(self):
        # finalizeApproval stores the built verdict operation in the proposal
        # and Undo reopens the card with it; the Worker refuses operations on
        # a trial result's send-back, and a verdict posts only {"verdict"}.
        built = {"kind": "source_upsert", "value": {
            "key": "managed_beta", "name": "Beta Corp newsroom", "endpoint": "https://beta.example/news", "adapter": "html", "entity_ids": ["beta"],
            "source_role": "company_newsroom", "companyStatus": "public", "cadence_minutes": 60, "configuration_status": "configured",
            "include_terms": [], "radar_lane": None}}
        self.drafts = [{**TRIAL_RESULT, "proposal": {**TRIAL_RESULT["proposal"], "operations": [built]}}]
        # One click per session (Streamlit 1.37 AppTest).
        for button, expected in (("radar_sendback_50", {"feedback": "Promote it to a relationship source of Kratos"}),
                                 ("radar_promote_50", {"verdict": "promote"})):
            with self.subTest(button=button):
                app = self.start()
                app.toggle("radar_details_50").set_value(True).run()
                self.assertEqual(list(app.exception), [])
                fields = [w.key for w in (*app.text_input, *app.text_area, *app.number_input)]
                self.assertEqual([k for k in fields if str(k).startswith("radar_50_op")], [], "no editable operation fields")
                self.assertNotIn("Newsroom URL", [w.label for w in app.text_input])
                app.text_input("radar_note_50").set_value("Promote it to a relationship source of Kratos")
                app.button(button).click().run()
                self.assertEqual(list(app.exception), [])
                self.assertEqual(self.posts()[-1][2], expected)

    def test_a_sent_back_trial_result_cannot_be_withdrawn(self):
        # Withdraw is a reject, and a trial result has no Discard: the
        # verdict stays due until the owner picks one.
        queued = draft(50, lane="discovery", action="trial_result", refine_status="queued", refine_round=1,
                       owner_feedback=[{"round": 0, "text": "Promote it to a relationship source of Kratos", "at": "2026-09-30T16:00:00Z"}],
                       previous_proposal=TRIAL_RESULT["proposal"])
        self.drafts = [queued, REQUEST]
        app = self.start()
        self.assertIn("You sent: Promote it to a relationship source of Kratos", self.rendered(app))
        keys = {b.key for b in app.button}
        self.assertNotIn("radar_withdraw_50", keys)
        self.assertIn("radar_withdraw_20", keys, "other send-backs and requests keep Withdraw")
        self.assertEqual(self.posts(), [])

    def test_trial_card_prefers_the_live_scorecard_and_names_the_promote_target(self):
        live = {**SCORECARD, "day": 22, "shown": 5, "avg_grade": 35.2, "grades_70_plus": 0, "grades_below_40": 3}
        card = {**TRIAL_RESULT, "trial_scorecard": live, "proposal": {
            **TRIAL_RESULT["proposal"], "verdict": "retire", "reason": "day_21",
            "promote_to": {"radar_lane": "relationship", "relationship": {"covered_entity_id": "kratos", "kind": "customer", "counterpart": "Beta Corp"}}}}
        body = trial_html(card)
        self.assertIn('<span class="refine-chip">Day 21 result</span>', body)
        self.assertIn("Day 22 of 21 · 5 shown in the panel · average grade 35 · 0 graded 70+ · 3 below 40", body)
        self.assertIn("Claude recommends Retire · Promote: becomes a relationship source of kratos", body)
        early_retire = {**TRIAL_RESULT, "proposal": {**TRIAL_RESULT["proposal"], "reason": "early_retire"}}
        self.assertIn('<span class="refine-chip">Early: 3 grades below 40</span>', trial_html(early_retire))
        # A malformed scorecard never stops the card: numbers read as 0, no
        # average as '—', and Claude's text stays escaped on one line.
        hostile = {**TRIAL_RESULT, "proposal": {**TRIAL_RESULT["proposal"], "scorecard": "lots", "verdict": "<b>keep</b>",
                                                "promote_to": {"radar_lane": "relationship", "relationship": {"covered_entity_id": "<i>x</i>\n\ny"}}}}
        body = trial_html(hostile)
        self.assertIn("0 shown in the panel · average grade — · 0 graded 70+ · 0 below 40", body)
        self.assertNotIn("Day ", body)
        self.assertIn("Promote: becomes a relationship source of &lt;i&gt;x&lt;/i&gt; y</div>", body)
        self.assertNotIn("recommends", body, "an unknown verdict is not offered as a pick")
        self.assertNotIn("\n", body)

    def test_just_decided_names_the_trial_verdict(self):
        decided = dict(status="approved", decided_at="2026-09-30T18:05:00Z", undo_available=True, lane="discovery", action="trial_result",
                       proposal=TRIAL_RESULT["proposal"])
        self.recent = [draft(61, result={"revision_id": "r1", "label": "Radar #61", "verdict": "promote"}, **decided),
                       draft(62, result={"revision_id": "r2", "label": "Radar #62", "verdict": "extend"}, **decided),
                       draft(63, result={"revision_id": "r3", "label": "Radar #63", "verdict": "retire"}, **decided), *RECENT]
        app = self.start()
        rendered = self.rendered(app)
        for label in ("Promoted #61", "Extended #62", "Retired #63", "Approved #9", "Discarded #8"):
            self.assertIn(f"{label} · ", rendered)
        self.assertTrue({"radar_undo_61", "radar_undo_62", "radar_undo_63"} <= {b.key for b in app.button}, "undo is unchanged")
        self.assertEqual(recent_label(draft(64, status="approved", result={"verdict": ["promote"]})), "Approved #64")
        self.assertEqual(recent_label(draft(65, status="approved", result="corrupt")), "Approved #65")

    def test_a_start_trial_card_offers_the_trial_cadence(self):
        value = START_TRIAL["proposal"]["operations"][0]["value"]
        self.assertEqual(cadence_ceiling(value, START_TRIAL), 60)
        self.assertEqual(cadence_ceiling({**value, "cadence_minutes": 20, "entity_ids": ["entity_ondas"]},
                                         draft(1, proposal={"covered_entity_id": "entity_ondas"})), 60,
                         "a trial source never gets the covered newsroom's 8 minutes")
        self.assertEqual(cadence_ceiling({**value, "companyStatus": "private"}, START_TRIAL), 60, "not the 120 of a private company")
        existing = {"key": "managed_beta", "cadence_minutes": 30}
        self.assertEqual(cadence_ceiling(existing, START_TRIAL), 60, "an existing source the card leaves the lane out of")
        self.assertEqual(cadence_ceiling(existing, TRIAL_RESULT), 60)
        self.assertEqual(cadence_ceiling(existing, draft(2, lane="discovery", action="fix_source", proposal={"action": "fix_source"})), 120)
        self.assertEqual(cadence_ceiling({**value, "cadence_minutes": 90}, START_TRIAL), 90, "Claude's own cadence always fits")
        self.assertIn("Lane: discovery trial (21 days; dates set on approval)", facts_html("source_upsert", value))
        self.assertIn("Lane: discovery trial (until Oct 21, 1:00 PM ET)",
                      facts_html("source_upsert", {**value, "trial": {"started_at": "2026-09-30T17:00:00Z", "ends_at": "2026-10-21T17:00:00Z"}}))
        self.assertEqual(include_terms_field(value, START_TRIAL), TOPIC_FILTER_FIELD, "a trial source has no relationship scope")
        self.assertIn("Changes existing source: Beta · trial dates",
                      effects_html(draft(3, effects=[{"kind": "source_upsert", "name": "Beta", "is_new": False,
                                                      "changes": {"trial": [{"ends_at": "a"}, {"ends_at": "b"}]}}])))
        self.drafts = [START_TRIAL]
        app = self.start()
        rendered = self.rendered(app)
        self.assertIn('<span class="loop-kind loop-kind-discovery">Discovery lane</span><span class="refine-chip">Start trial</span>', rendered)
        self.assertTrue({"radar_approve_51", "radar_sendback_51", "radar_discard_51"} <= {b.key for b in app.button})

    def test_start_trial_details_cap_the_cadence_at_60(self):
        self.drafts = [START_TRIAL]
        app = self.start()
        app.toggle("radar_details_51").set_value(True).run()
        self.assertEqual(list(app.exception), [])
        cadence = app.number_input("radar_51_op0_cadence")
        self.assertEqual((cadence.value, cadence.max), (60, 60))
        self.assertIn("Lane: discovery trial (21 days; dates set on approval)", self.rendered(app))
        self.assertEqual(app.text_area("radar_51_op0_include").label, TOPIC_FILTER_FIELD[0])

    # ------------------------------------------------------------ discovery lane

    def test_a_missed_story_diagnosis_reads_in_plain_words(self):
        def card(**fields):
            return draft(70, action="missed_story", proposal={**MISSED_STORY["proposal"], "diagnosis": {**DIAGNOSIS, **fields}})
        self.assertEqual(missed_story_html(MISSED_STORY), '<div class="rule-meta">Collected Sep 29, 10:05 AM ET as event 4512; '
                                                          'the Grader rejected it (score 35, below materiality)</div>')
        self.assertIn("as event 4512; the Grader marked it a duplicate of event 4400</div>",
                      missed_story_html(card(code="collected_rejected", decision="duplicate", score=None, reason_code=None, canonical_event_id=4400)))
        self.assertIn("as event 4512; the Grader selected it, but the edition did not publish it</div>",
                      missed_story_html(card(decision="selected", score=82, reason_code="material")))
        self.assertIn("as event 4512; no Grader run has reviewed it yet</div>",
                      missed_story_html(card(code="collected_unreviewed", decision=None, score=None, reason_code=None, run_id=None)))
        self.assertIn("the Grader rejected it (score 35)</div>", missed_story_html(card(reason_code=None)))
        self.assertIn("the Grader rejected it (not my focus)</div>", missed_story_html(card(score="35", reason_code="not_my_focus")))
        # A story matched by its title links the collected event, so the owner
        # can check it is the same story; Worker-stored text stays escaped and
        # on one line, an unreadable time included.
        titled = missed_story_html(card(matched_by="title", event_title="Navy <b>orders</b>" + IMAGE, event_url="https://news.example/navy-x10d",
                                        collected_at="not a time <i>"))
        self.assertIn('<div class="rule-meta">Collected not a time &lt;i&gt; as event 4512; ', titled)
        self.assertIn('<div class="rule-meta">Matched by title: <a href="https://news.example/navy-x10d" target="_blank" rel="noopener noreferrer">'
                      'Navy &lt;b&gt;orders&lt;/b&gt; ![x](https://attacker.example/p.png)</a></div>', titled)
        self.assertNotIn("\n", titled)
        self.assertNotIn("Matched by title", missed_story_html(MISSED_STORY))
        self.assertIn("Matched by title: javascript:alert(1)</div>", missed_story_html(card(matched_by="title", event_title=None, event_url="javascript:alert(1)")),
                      "anything but http(s) stays plain text")
        self.assertEqual(missed_story_html(card(event_id="x", collected_at=None, decision=None)), '<div class="rule-meta">Collected; no Grader run has reviewed it yet</div>')
        self.assertEqual(missed_story_html(draft(70, action="missed_story", proposal={"action": "missed_story", "diagnosis": "corrupt"})), "")

    def test_a_missed_story_card_offers_send_to_rules_and_discard_only(self):
        self.drafts = [MISSED_STORY]
        app = self.start()
        rendered = self.rendered(app)
        self.assertIn('<span class="loop-kind loop-kind-discovery">Discovery lane</span><span class="refine-chip">Missed story</span>', rendered)
        self.assertIn("Collected Sep 29, 10:05 AM ET as event 4512; the Grader rejected it (score 35, below materiality)", rendered)
        buttons = {b.key: b for b in app.button}
        self.assertEqual((buttons["radar_torules_70"].label, buttons["radar_torules_70"].proto.type), ("Send to Rules", "primary"))
        self.assertEqual(buttons["radar_discard_70"].label, "Discard")
        self.assertFalse([k for k in buttons if str(k).startswith(("radar_sendback_", "radar_approve_"))], "no Approve and no Send back")
        self.assertEqual(app.text_input("radar_note_70").label, "Your words for Rules (optional)")
        self.assertEqual(self.posts(), [])

    def test_a_missed_story_card_shows_no_operation_fields(self):
        self.drafts = [MISSED_STORY]
        app = self.start()
        app.toggle("radar_details_70").set_value(True).run()
        self.assertEqual(list(app.exception), [])
        fields = [w.key for w in (*app.text_input, *app.text_area, *app.number_input)]
        self.assertEqual([k for k in fields if str(k).startswith("radar_70_op")], [])
        self.assertIn('Your link: <a href="https://news.example/skydio-navy"', self.rendered(app))

    def test_send_to_rules_posts_the_note_only_when_given(self):
        self.drafts = [MISSED_STORY]
        # One click per session (Streamlit 1.37 AppTest).
        for note, body in (("", {}), ("   ", {}), ("  Navy orders are material  ", {"text": "Navy orders are material"})):
            with self.subTest(note=note):
                app = self.start()
                if note:
                    app.text_input("radar_note_70").set_value(note)
                app.button("radar_torules_70").click().run()
                self.assertEqual(list(app.exception), [])
                url, sent = self.posts()[-1][1:]
                self.assertTrue(url.endswith("/radar/drafts/70/to-rules"), url)
                self.assertEqual(sent, body)
                self.assertEqual([s.value for s in app.success], ["Sent to Rules as draft #88"])
        self.assertEqual(len(self.posts()), 3)

    def test_send_to_rules_says_when_the_rules_draft_already_exists(self):
        self.drafts = [MISSED_STORY]
        self.to_rules = {"rules_draft_id": 88, "duplicate": True}
        app = self.start()
        app.button("radar_torules_70").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual([s.value for s in app.success], ["Already in Rules as draft #88"])

    def test_a_refused_send_to_rules_stays_on_the_card(self):
        # An older aggregator answers 404; a second click while the first is
        # filing, 409.
        self.drafts = [MISSED_STORY]
        self.to_rules_error = (404, "Not found.")
        app = self.start()
        app.button("radar_torules_70").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual([e.value for e in app.error], [md_escape("Not found.")])
        self.assertEqual(list(app.success), [])
        self.assertTrue(any(b.key == "radar_torules_70" for b in app.button), "the card is still there")

    def test_a_missed_story_can_be_discarded(self):
        self.drafts = [MISSED_STORY]
        app = self.start()
        app.button("radar_discard_70").click().run()
        self.assertEqual(list(app.exception), [])
        url, body = self.posts()[-1][1:]
        self.assertTrue(url.endswith("/radar/drafts/70/reject"))
        self.assertEqual(body, {})
        self.assertEqual([s.value for s in app.success], ["#70 discarded · undo within 24 h"])

    def test_just_decided_names_a_missed_story_sent_to_rules(self):
        sent = draft(71, status="approved", decided_at="2026-09-30T18:05:00Z", undo_available=True, lane="discovery", action="missed_story",
                     result={"label": "Radar #71: Missed story", "rules_draft_id": 88}, proposal=MISSED_STORY["proposal"])
        self.assertEqual(recent_label(sent), "Sent to Rules #71")
        self.assertEqual(recent_label({**sent, "status": "rejected"}), "Discarded #71")
        self.assertEqual(recent_label({**sent, "result": {"label": "Radar #71"}}), "Approved #71")
        self.recent = [sent, *RECENT]
        app = self.start()
        rendered = self.rendered(app)
        self.assertIn("Sent to Rules #71 · Sep 30, 2:05 PM ET", rendered)
        self.assertIn("Approved #9 · ", rendered)
        self.assertIn("radar_undo_71", {b.key for b in app.button})

    def test_undo_withdraws_the_pending_rules_draft(self):
        sent = draft(71, status="approved", decided_at="2026-09-30T18:05:00Z", undo_available=True, lane="discovery", action="missed_story",
                     result={"label": "Radar #71: Missed story", "rules_draft_id": 88}, proposal=MISSED_STORY["proposal"])
        self.recent = [sent]
        # One click per session (Streamlit 1.37 AppTest).
        for status, response, message in (
                (200, {"ok": True, "draft_id": 71, "rules_draft_withdrawn": True}, ("success", "Undone · #71 is back in Radar · Rules draft #88 withdrawn")),
                (409, {"ok": False, "error": "Rules draft #88 was already decided; undo it on the Rules tab."},
                 ("error", md_escape("Rules draft #88 was already decided; undo it on the Rules tab.")))):
            with self.subTest(status=status):
                self.undo_result = (status, response)
                app = self.start()
                app.button("radar_undo_71").click().run()
                self.assertEqual(list(app.exception), [])
                self.assertTrue(self.posts()[-1][1].endswith("/radar/drafts/71/undo"))
                kind, text = message
                self.assertEqual([m.value for m in getattr(app, kind)], [text])

    def test_start_trial_evidence_shows_the_workers_values(self):
        body = start_trial_evidence_html({"evidence": EVIDENCE})
        link = '<a href="{0}" target="_blank" rel="noopener noreferrer">{0}</a>'.format
        self.assertEqual(body, (
            '<div class="rule-meta">2 misses in 30 days · 1 unique</div>'
            f'<div class="rule-meta">{link("https://beta.example/news/x9")} · first seen elsewhere Sep 28, 10:00 AM ET · not collected · you reported it (#44)</div>'
            f'<div class="rule-meta">{link("https://beta.example/news/y2")} · first seen elsewhere Sep 20, 8:00 AM ET · collected 7 h later · you graded it 78</div>'
            f'<div class="rule-meta">{link("https://beta.example/news/z1")} · first seen elsewhere Sep 18, 8:00 AM ET · collected first</div>'))
        def miss(**fields):
            return start_trial_evidence_html({"evidence": {**EVIDENCE, "counted": 1, "misses": [{**EVIDENCE["misses"][1], **fields}]}})
        self.assertIn("1 miss in 30 days · 1 unique", miss())
        self.assertIn("collected 6 h later", miss(lead_hours=6.49), "rounded, not truncated")
        self.assertIn("collected 13 h later", miss(lead_hours=12.5))
        self.assertIn("collected under 1 h later", miss(lead_hours=0.3))
        self.assertIn("collected first", miss(lead_hours=0))
        self.assertIn("collected Sep 20, 2:30 PM ET", miss(lead_hours=None), "a lead the Worker could not compute")
        self.assertIn("collected Sep 20, 2:30 PM ET", miss(lead_hours="6.5"))
        self.assertIn("· you reported it (#44)</div>", miss(owner_flagged=True, owner_request_id=44, owner_grade=78), "reported, never 'graded'")
        self.assertIn("· you reported it</div>", miss(owner_flagged=True, owner_request_id=None, owner_grade=None))
        self.assertNotIn("you graded", miss(owner_grade=None))
        self.assertNotIn("you graded", miss(owner_grade="78"))
        hostile = miss(url="https://beta.example/a" + IMAGE, first_seen_elsewhere="soon <b>")
        self.assertIn("first seen elsewhere soon &lt;b&gt;", hostile)
        self.assertNotIn("\n", hostile)
        self.assertIn("0 misses in 30 days · 0 unique</div>", start_trial_evidence_html({"evidence": {"misses": "lots"}}), "malformed lists show nothing")
        for absent in ({}, {"evidence": None}, {"evidence": "verified"}, {"evidence": []}):
            self.assertEqual(start_trial_evidence_html(absent), "", "a phase-3 card without evidence")

    def test_a_start_trial_card_shows_its_evidence_below_the_probe(self):
        probed = {**START_TRIAL["proposal"], "probe": {"total_found": 12, "excluded": {}, "checked_at": "2026-09-30T17:35:00Z"}}
        self.drafts = [{**START_TRIAL, "proposal": {**probed, "evidence": EVIDENCE}}, {**START_TRIAL, "id": 52, "proposal": probed}]
        app = self.start()
        cards = [m.value for m in app.markdown if "Probe: 12 posts" in m.value]
        self.assertEqual(len(cards), 2)
        self.assertLess(cards[0].index("Probe: 12 posts · 0 excluded · checked Sep 30, 1:35 PM ET"), cards[0].index("2 misses in 30 days · 1 unique"))
        self.assertIn("you reported it (#44)", cards[0])
        self.assertNotIn("misses in", cards[1], "a phase-3 card without evidence renders as before")
        self.assertTrue({"radar_approve_51", "radar_sendback_51", "radar_discard_51"} <= {b.key for b in app.button})

    def test_recall_rows_are_text_with_dashes_before_an_audit(self):
        self.assertEqual(recall_rows(RECALL), [
            {"Industry": "Autonomous vehicles", "Last audit": "Sep 30", "Found": "12", "Captured": "10", "Late": "2", "Recall": "83%"},
            {"Industry": "Drones & UAS", "Last audit": "—", "Found": "—", "Captured": "—", "Late": "—", "Recall": "—"}])
        self.assertEqual(recall_rows([RECALL[1]]), [], "no audit yet")
        self.assertEqual(recall_rows("corrupt"), [])
        self.assertEqual([percent_text(v) for v in (83, 82.5, 0, None, True, "83")], ["83%", "83%", "0%", "—", "—", "—"])
        self.assertEqual(recall_rows([{**RECALL[0], "name": None, "found_30d": 0, "captured_30d": 0, "late_30d": 0, "recall_pct": None}])[0],
                         {"Industry": "autonomous_vehicles", "Last audit": "Sep 30", "Found": "0", "Captured": "0", "Late": "0", "Recall": "—"})

    def test_lane_health_shows_recall_without_any_radar_source(self):
        self.lanes, self.recall = [], RECALL
        app = self.start()
        captions = [c.value for c in app.caption]
        self.assertIn("No Radar sources yet. Sources you approve here are listed with their collection status.", captions)
        self.assertLess(captions.index("No Radar sources yet. Sources you approve here are listed with their collection status."),
                        captions.index("Recall by industry (30 days)"))
        self.assertEqual(len(app.dataframe), 1)
        table = app.dataframe[0].value
        self.assertEqual(list(table.columns), RECALL_COLUMNS)
        self.assertEqual(table.values.tolist(), [["Autonomous vehicles", "Sep 30", "12", "10", "2", "83%"], ["Drones & UAS", "—", "—", "—", "—", "—"]])

    def test_lane_health_shows_recall_after_the_trial_table(self):
        self.lanes, self.recall = [{**LANES[0], "trial": None}, TRIAL_LANE], RECALL
        app = self.start()
        self.assertEqual(len(app.dataframe), 3)
        self.assertEqual(app.dataframe[0].value.iloc[0].tolist()[0], "Acme Robotics newsroom", "the main table stays first")
        self.assertEqual(list(app.dataframe[1].value.columns)[:2], ["Source", "Day"], "then the trial table")
        self.assertEqual(list(app.dataframe[2].value.columns), RECALL_COLUMNS)
        captions = [c.value for c in app.caption]
        self.assertLess(captions.index("Trial sources"), captions.index("Recall by industry (30 days)"))

    def test_lane_health_says_when_no_industry_was_audited(self):
        self.recall = [RECALL[1], {**RECALL[1], "industry_id": "humanoids", "name": "Humanoids"}]
        app = self.start()
        captions = [c.value for c in app.caption]
        self.assertIn("No recall audit yet; the 8:30 PM run audits a third of the industries each night.", captions)
        self.assertNotIn("Recall by industry (30 days)", captions)
        self.assertEqual(len(app.dataframe), 1, "only the sources table")
        self.recall = []
        app = self.start()
        self.assertFalse([c.value for c in app.caption if "ecall" in c.value], "an empty recall shows nothing")

    def test_composer_explains_the_missed_story_link(self):
        app = self.start()
        self.assertIn(MISSED_CAPTION, [c.value for c in app.caption])
        self.assertEqual(MISSED_CAPTION, "For a missed story, paste its link: at its next run Claude checks whether we collected it and why it was missed "
                                         "(no source, a filter, a broken source or a low ranking), and answers with a card.")
        self.assertEqual(app.text_input("radar_url").label, "Link (required for a missed story)")

    def test_composer_shows_a_worker_refusal_inline(self):
        self.request_error = "The link must be an http(s) URL."
        app = self.start()
        app.radio("radar_kind").set_value("We missed this story")
        app.text_area("radar_text").set_value("The Navy's Skydio order never reached the digest")
        app.text_input("radar_url").set_value("https://news example/skydio")
        self.composer_submit(app)
        self.assertEqual(self.posts()[-1][2], {"text": "The Navy's Skydio order never reached the digest", "kind": "missed", "url": "https://news example/skydio"})
        self.assertEqual([e.value for e in app.error], [md_escape("The link must be an http(s) URL.")])
        self.assertEqual(list(app.success), [])


if __name__ == "__main__":
    unittest.main()
