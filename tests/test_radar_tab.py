import copy
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from radar_view import (cadence_ceiling, chips_html, classify, effects_html, evidence_html, facts_html, history_html, md_escape, next_pickup_label,
                        sample_count, samples_html, sent_words, short_time, split_aliases)


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


class RadarTabTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        self.calls = []
        self.drafts = [NEW_SOURCE, NO_CHANGE, REQUEST, SENT_BACK]
        self.recent = RECENT
        self.lanes = LANES
        self.approve_error = None
        self.approve_label = None
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
            return StubResponse({"ok": True, "drafts": self.drafts, "counts": {
                "your_turn": len([d for d in self.drafts if d["refine_status"] == "proposed"]),
                "with_claude": len([d for d in self.drafts if d["refine_status"] == "queued"])}})
        if url.endswith("/radar/lanes"):
            return StubResponse({"ok": True, "revision_id": "rev-7", "sources": self.lanes})
        raise AssertionError(f"unexpected request: {url}")

    def fake_post(self, url, **kwargs):
        body = kwargs.get("json") or {}
        self.calls.append(("POST", url, body))
        self.assertEqual(kwargs.get("headers"), {"X-Owner-Pin": "test-pin"})
        if url.endswith("/radar/drafts"):
            return StubResponse({"ok": True, "draft_id": 31, "duplicate": False})
        draft_id = int(url.split("/")[-2])
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

    def test_a_failed_reprobe_stays_on_the_card(self):
        self.approve_error = PROBE_FAILED
        app = self.start()
        app.button("radar_approve_12").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual([e.value for e in app.error], [PROBE_FAILED])
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


if __name__ == "__main__":
    unittest.main()
