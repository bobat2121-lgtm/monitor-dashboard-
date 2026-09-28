import unittest
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from calibration_view import delta_text, pct
from datetime import datetime, timezone

from rules_view import classify, draft_origin, effect_payload, effect_text, next_pickup_label, parse_signature, signature_value, sort_rules


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"


class StubResponse:
    text = ""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


RULES = [
    {"id": 1, "rule_id": "R-0001", "kind": "rule", "active": 1, "text": "Freshness is judged by the event date.", "source": "chat", "created_at": "2026-08-11T12:56:41Z", "signature": {}, "state": "working"},
    {"id": 2, "rule_id": "R-0002", "kind": "rule", "active": 1, "text": "Ceremonial items are out.", "source": "dashboard", "created_at": "2026-08-22T20:56:12Z", "signature": {"keywords": ["award", "bell"]}, "state": "ignored"},
    {"id": 3, "rule_id": "R-scale-v1", "kind": "rule", "active": 1, "text": "Grade scale.", "source": "owner", "created_at": "2026-09-18T02:00:00Z", "signature": {}, "state": None},
]
DRAFTS = [
    {"id": 7, "created_at": "2026-09-21T12:00:00Z", "run_id": "distill-2026-09-21", "text": "Robotaxi launches by major operators are digest items; score 70 or more.", "signature": {"workers": ["robotaxi-monitor"], "keywords": ["waymo"]}, "source_feedback_ids": [73], "status": "pending"},
]
JUMBLE = "the navy usv marketplace thing should have been lead, opening a program to new vendors is huge"
REWRITE = "A government program that opens production qualification to new vendors of an autonomous system is a digest item (70+), and leads when it names a program of record."
REFINE_DRAFTS = [
    {"id": 8, "created_at": "2026-09-24T20:00:00Z", "run_id": "owner", "text": JUMBLE, "raw_text": JUMBLE, "event_id": 900, "status": "pending",
     "refine_status": "proposed", "refine_round": 1, "signature": {}, "source_feedback_ids": [], "owner_feedback": [],
     "proposal": {"text": REWRITE, "signature": {"workers": [], "tickers": [], "categories": [], "keywords": ["marketplace", "qualification"]},
                  "effect": {"min_score": 70}, "rationale": "Generalized from the Navy USV marketplace to any autonomy program opening to new vendors.",
                  "overlaps": ["R-0002"], "conflicts": [], "supersedes": "R-0001"}},
    {"id": 9, "created_at": "2026-09-24T21:00:00Z", "run_id": None, "text": "drone unveilings are noise unless someone buys them", "raw_text": "drone unveilings are noise unless someone buys them",
     "status": "pending", "refine_status": "queued", "refine_round": 0, "signature": {}, "source_feedback_ids": [80],
     "owner_feedback": [], "proposal": None},
]


def overall(month, agreement, gap, n=10, dis=3):
    return {"month": month, "dimension": "overall", "dimension_value": "all", "n_graded": n, "n_late": 1, "n_comparable": n - 1, "n_disagreements": dis,
            "action_agreement": agreement, "mean_score_gap": gap, "false_negative_rate": 0.2, "false_positive_rate": 0.0, "median_lag_hours": 3.5}


SUMMARY = {
    "ok": True, "months": ["2026-08", "2026-09"], "latest_month": "2026-09", "prior_month": "2026-08", "provisional": True,
    "headline": {**overall("2026-09", 0.667, -18.3), "prior_action_agreement": 0.5, "delta": 0.167},
    "trend": [{"month": "2026-08", "action_agreement": 0.5, "mean_score_gap": -30, "n_graded": 8, "n_disagreements": 4},
              {"month": "2026-09", "action_agreement": 0.667, "mean_score_gap": -18.3, "n_graded": 10, "n_disagreements": 3}],
    "worst": [{"dimension": "worker", "dimension_value": "robotaxi-monitor", "n_graded": 4, "n_comparable": 4, "n_disagreements": 2, "action_agreement": 0.5, "mean_score_gap": -20}],
    "most_improved": [],
    "rules": [{"rule_id": "R-0002", "cited": 0, "applicable": 5, "agreement_when_cited": None, "agreement_when_applicable_not_cited": 0.4, "state": "ignored"},
              {"rule_id": "R-0009", "cited": 4, "applicable": 5, "agreement_when_cited": 0.9, "agreement_when_applicable_not_cited": None, "state": "working"}],
    "rules_added_last_month": ["R-0009"],
    "context": {"month": "2026-09", "active_rules": 38}, "prior_audit": {"summary": "August: mostly late reposts.", "focus": "Grade every rejection."}, "latest_audit": None,
}
MONTH = {"ok": True, "month": "2026-09", "dimensions": [overall("2026-09", 0.667, -18.3), {"month": "2026-09", "dimension": "worker", "dimension_value": "robotaxi-monitor", "n_graded": 4, "n_comparable": 4, "n_disagreements": 2, "action_agreement": 0.5, "mean_score_gap": -20}], "rules": [], "context": {}, "audit": []}
DRILL = {"ok": True, "grades": [{"id": 73, "event_id": 14683, "title": "Waymo now testing in Pittsburgh", "target_score": 75, "owner_action": "digest", "reason_code": "wrong_action", "grader_score": 40, "grader_action": "reject", "grader_reason_code": "below_materiality", "agree": False, "late": False, "note": "Robotaxi expansions are key"}]}
GUIDES = {"ok": True, "guides": {"monthly_audit": {"path": "docs/monthly-audit.md", "text": "# Monthly audit — 20 minutes\n\n1. Read the headline."}, "how_to_grade": {"path": "docs/how-to-grade.md", "text": "# How to grade\n\nGrade disagreements, not agreements."}}}


ITEMS = [
    {"id": 40, "rule_id": "I-0001", "kind": "case", "type": "item", "active": 1, "event_id": 900,
     "text": "Newport Beach expanded its Skydio and Axon police-drone program; the owner graded it borderline. Routine municipal renewals stay borderline.",
     "signature": {"workers": ["axon-signal-watcher"], "tickers": ["AXON"], "keywords": ["police", "renew"]}, "created_at": "2026-09-27T18:00:00Z", "state": None},
]
TRENDS = {"ok": True, "config": {"min_grades": 5, "min_share": 0.75, "window_days": 30}, "trends": [
    {"key": "worker:axon-signal-watcher", "status": "ready", "n": 6, "needed": 5, "comparable": 7, "share": 0.857,
     "summary": "You graded 6 of 7 axon signal watcher items lower than the grader in the last 30 days"},
    {"key": "reason:not_my_focus", "status": "watching", "n": 3, "needed": 5, "comparable": 4, "share": 0.75,
     "summary": "You graded 3 of 4 not my focus items lower than the grader in the last 30 days"},
    {"key": "ticker:AXON", "status": "covered", "n": 6, "needed": 5, "comparable": 7, "share": 0.857, "covered_by": "R-0009",
     "summary": "You graded 6 of 7 AXON items lower than the grader in the last 30 days"},
]}


def proposed(draft_id, text, proposal_text, feedback=(), status="proposed", target=None, run_id="owner", kind="rule", effect=None):
    return {"id": draft_id, "created_at": "2026-09-27T12:00:00Z", "run_id": run_id, "text": text, "raw_text": text, "status": "pending",
            "refine_status": status, "refine_round": 1 if status == "proposed" or feedback else 0, "signature": {}, "source_feedback_ids": [],
            "owner_feedback": list(feedback), "owner_edit": next((f.get("edit") for f in reversed(list(feedback)) if f.get("edit")), None),
            "target_rule_id": target, "kind": kind,
            "proposal": None if proposal_text is None else {"text": proposal_text, "signature": {"keywords": ["counter-uas"]}, "effect": effect,
                                                              "rationale": "Kept the $1M threshold.", "overlaps": [], "conflicts": [], "supersedes": target}}


class RulesTabTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        self.calls = []
        self.guides = GUIDES
        self.drafts = DRAFTS
        self.recent = []
        self.items = ITEMS
        self.trends = TRENDS
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
        if url.endswith("/grades/guide"):
            return StubResponse(self.guides, 200 if self.guides else 503)
        if "/rules/drafts" in url and "status=recent" in url:
            return StubResponse({"ok": True, "drafts": self.recent})
        if "/rules/drafts" in url:
            return StubResponse({"ok": True, "drafts": self.drafts})
        if "/rules/items" in url:
            items = self.items if "include=inactive" in url else [i for i in self.items if i.get("active")]
            return StubResponse({"ok": True, "items": items})
        if "/rules" in url:
            return StubResponse({"ok": True, "rules": RULES + ([{**RULES[0], "id": 9, "rule_id": "R-0009", "active": 0, "superseded_by": None, "text": "Old retired rule."}] if "include=inactive" in url else []), "pending_drafts": 1})
        if "/calibration/trends" in url:
            return StubResponse(self.trends)
        if "/calibration/summary" in url:
            return StubResponse(SUMMARY)
        if "/calibration/month" in url:
            return StubResponse(MONTH)
        if "/calibration/drilldown" in url:
            return StubResponse(DRILL)
        raise AssertionError(f"unexpected request: {url}")

    def fake_post(self, url, **kwargs):
        body = kwargs.get("json") or {}
        self.calls.append(("POST", url, body))
        if url.endswith("/approve"):
            kind = body.get("kind", "rule")
            return StubResponse({"ok": True, "kind": kind, "rule_id": "I-0002" if kind == "item" else "R-0003", "distilled": 1, "precedent_id": 9, "superseded": body.get("supersedes")})
        if url.endswith("/rules/drafts"):
            return StubResponse({"ok": True, "draft_id": 12, "kind": body.get("kind"), "duplicate": False, "refine_status": "queued"})
        if url.endswith("/rules/refine-missing"):
            return StubResponse({"ok": True, "queued": 1, "remaining": 0})
        if url.endswith("/refine") and "/rules/drafts/" in url:
            return StubResponse({"ok": True, "draft_id": int(url.split("/")[-2]), "refine_status": "queued", "edit": "text" in body})
        if url.endswith("/refine"):
            return StubResponse({"ok": True, "rule_id": url.split("/")[-2], "draft_id": 13, "refine_status": "queued"})
        if url.endswith("/undo"):
            return StubResponse({"ok": True, "draft_id": int(url.split("/")[-2]), "restored": "superseded", "status": "pending"})
        if url.endswith("/drop"):
            return StubResponse({"ok": True, "draft_id": int(url.split("/")[-2]), "dropped": "R-0034", "status": "approved"})
        if url.endswith("/deactivate") or url.endswith("/reactivate"):
            return StubResponse({"ok": True, "rule_id": url.split("/")[-2], "active": 1 if url.endswith("/reactivate") else 0})
        if url.endswith("/calibration/trends/draft"):
            return StubResponse({"ok": True, "key": body.get("key"), "draft_id": 55, "created": True})
        if url.endswith("/calibration/audit"):
            return StubResponse({"ok": True, "id": 1, "month": "2026-09", "standing_instruction_id": 23})
        return StubResponse({"ok": True})

    def start(self, pin="test-pin"):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["grader_pin"] = pin
        app.session_state["dashboard_view"] = "Rules"
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def rendered(self, app):
        return "\n".join(m.value for m in app.markdown)

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]

    def test_helpers(self):
        self.assertEqual(parse_signature("workers: a, b; tickers: X; bogus: y"), {"workers": ["a", "b"], "tickers": ["X"]})
        self.assertEqual([r["rule_id"] for r in sort_rules(RULES)], ["R-0002", "R-0001", "R-scale-v1"])
        self.assertEqual(pct(0.667), "67%"); self.assertEqual(delta_text(0.167), "+17 pts vs prior month")
        self.assertEqual(signature_value({"workers": ["a", "b"], "tickers": [], "keywords": ["k"]}), "workers: a, b; keywords: k")
        self.assertEqual(effect_payload(70, None), {"min_score": 70})
        self.assertEqual(effect_text({"min_score": 70, "max_score": 95}), "score floor 70 · score ceiling 95")
        self.assertEqual(draft_origin({"run_id": "owner"}), "written here")
        self.assertEqual(draft_origin({"run_id": None}), "from a grade")
        self.assertEqual(draft_origin({"run_id": "calibration-trend", "source_feedback_ids": [1, 2, 3]}), "from calibration · 3 grades")
        self.assertEqual(draft_origin({"run_id": "owner-revision", "target_rule_id": "R-0001"}), "revision of R-0001")
        # 6:45 PM ET -> the 6:50 PM edition pickup; 10 PM ET -> tomorrow's first one.
        self.assertEqual(next_pickup_label(datetime(2026, 9, 27, 22, 45, tzinfo=timezone.utc)), "~6:50 PM ET")
        self.assertEqual(next_pickup_label(datetime(2026, 9, 28, 2, 0, tzinfo=timezone.utc)), "tomorrow ~6:50 AM ET")
        groups = classify([
            proposed(1, "a" * 30, "b" * 30),
            proposed(2, "a" * 30, "b" * 30, feedback=[{"round": 1, "edit": "c" * 30}]),
            proposed(3, "a" * 30, "b" * 30, feedback=[{"round": 1, "text": "tighter"}], status="queued"),
            proposed(4, "a" * 30, None, status="queued"),
            proposed(5, "x" * 30, "x" * 30, target="R-0001"),
        ])
        self.assertEqual({k: [d["id"] for d in v] for k, v in groups.items()},
                         {"back": [2], "with_chatgpt": [3], "your_turn": [1], "signature_only": [5], "waiting": [4]})

    def test_navigation_has_no_separate_calibration_view(self):
        app = self.start()
        view = next(radio for radio in app.radio if radio.label == "Dashboard view")
        self.assertEqual(list(view.options), ["Feed", "Rejected", "Rules", "Universe"])

    def test_pin_gate_makes_no_owner_calls(self):
        app = self.start(pin="")
        self.assertIn("enter the grader PIN", self.rendered(app))
        self.assertFalse(any("/rules" in c[1] or "/calibration" in c[1] for c in self.calls))

    def test_three_tabs_render_with_the_pin_header(self):
        app = self.start()
        self.assertEqual([t.label for t in app.tabs], ["Drafts", "Rules & Items", "Calibration"])
        rendered = self.rendered(app)
        # Drafts: composer and the distilled draft as a card.
        self.assertTrue(any(f.proto.form.form_id == "rule_composer" for f in app.get("form")))
        self.assertEqual(app.text_area("card_text_7").value, DRAFTS[0]["text"])
        # Rules & Items: one expander per rule and item.
        labels = "\n".join(e.label for e in app.expander)
        for rule_id in ("R-0002 · Rule · ignored", "R-0001 · Rule · working", "R-scale-v1 · Rule · no data yet", "I-0001 · Item · guides"):
            self.assertIn(rule_id, labels)
        self.assertLess(labels.index("R-0002"), labels.index("R-0001"))
        # Calibration: trends first, then the scoreboard, audit and guide.
        self.assertIn("You graded 6 of 7 axon signal watcher items lower", rendered)
        self.assertNotIn("AXON items lower", rendered, "a covered trend is not shown")
        metric = next(m for m in app.metric if m.label == "Action agreement")
        self.assertEqual(metric.value, "67%"); self.assertEqual(metric.delta, "+17 pts vs prior month")
        self.assertEqual(len(app.get("plotly_chart")), 2)
        self.assertIn("Monthly audit", labels); self.assertIn("How to grade", labels)
        self.assertIn("Read the headline", rendered)
        self.assertTrue(any(f.proto.form.form_id == "audit_form" for f in app.get("form")))
        owner_calls = [c for c in self.calls if c[0] == "GET" and ("/rules" in c[1] or "/calibration" in c[1])]
        self.assertTrue(owner_calls and all(c[2] == {"X-Owner-Pin": "test-pin"} for c in owner_calls))
        self.assertEqual(len([c for c in self.calls if c[1].endswith("/grades/guide")]), 1, "guides fetched once and cached")

    def test_guides_unavailable_shows_fallback_not_an_error(self):
        self.guides = {}
        app = self.start()
        self.assertIn("Guide unavailable", "\n".join(c.value for c in app.caption))
        self.assertEqual(list(app.error), [])

    def test_composer_sends_the_words_as_a_rule_or_an_item(self):
        app = self.start()
        form = next(f for f in app.get("form") if f.proto.form.form_id == "rule_composer")
        next(b for b in form.button if b.label == "Send to ChatGPT").click().run()
        self.assertEqual(self.posts(), [], "empty words are not sent")
        app.radio("composer_kind").set_value("Item")
        app.text_area("composer_text").set_value(JUMBLE)
        form = next(f for f in app.get("form") if f.proto.form.form_id == "rule_composer")
        next(b for b in form.button if b.label == "Send to ChatGPT").click().run()
        post = self.posts()[-1]
        self.assertTrue(post[1].endswith("/rules/drafts"))
        self.assertEqual(post[2], {"text": JUMBLE, "kind": "item"})
        self.assertTrue(any("Item draft #12 sent to ChatGPT" in s.value for s in app.success))

    def test_card_publishes_chatgpts_version_or_the_owners_edit(self):
        self.drafts = [proposed(8, JUMBLE, REWRITE, target=None, effect={"min_score": 70})]
        self.drafts[0]["proposal"]["supersedes"] = "R-0001"
        app = self.start()
        self.assertEqual(app.text_area("card_text_8").value, REWRITE)
        self.assertIn("score floor 70", self.rendered(app))
        self.assertIn("would replace R-0001", self.rendered(app))
        app.button("publish_8").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual(self.posts()[-1][2], {"text": REWRITE}, "without details, the rewrite's signature and bounds stand")
        self.assertTrue(any("Published rule R-0003" in s.value for s in app.success))
        # Details: signature, bounds and the explicit choice to replace a rule.
        app.toggle("card_details_8").set_value(True).run()
        self.assertIn(JUMBLE, self.rendered(app))
        self.assertEqual(app.number_input("card_8_floor").value, 70)
        app.checkbox("card_replace_8").check()
        app.text_area("card_text_8").set_value(REWRITE + " Not for loitering munitions.")
        app.button("publish_8").click().run()
        payload = self.posts()[-1][2]
        self.assertEqual(payload["text"], REWRITE + " Not for loitering munitions.")
        self.assertEqual(payload["signature"], {"keywords": ["counter-uas"]})
        self.assertEqual(payload["effect"], {"min_score": 70})
        self.assertEqual(payload["supersedes"], "R-0001")

    def test_publish_as_relabels_a_draft_rule_or_item(self):
        self.drafts = [proposed(8, JUMBLE, REWRITE, effect={"min_score": 70}), proposed(5, "x" * 30, "y" * 30, target="R-0001")]
        app = self.start()
        self.assertEqual(app.radio("card_kind_8").value, "Rule", "starts on the draft's own label")
        self.assertEqual(app.radio("card_kind_5").value, "Rule", "revisions can be relabeled too")
        app.radio("card_kind_5").set_value("Item").run()
        self.assertTrue(any("retires R-0001 and creates a new item" in c.value for c in app.caption))
        app.radio("card_kind_5").set_value("Rule").run()
        app.radio("card_kind_8").set_value("Item").run()
        rendered = self.rendered(app)
        self.assertIn('loop-kind loop-kind-item', rendered)
        self.assertNotIn("score floor 70", rendered, "an item carries no floor or ceiling")
        app.button("publish_8").click().run()
        self.assertEqual(self.posts()[-1][2], {"text": REWRITE, "kind": "item"})
        self.assertTrue(any("Published item I-0002" in s.value for s in app.success))

    def test_send_back_as_the_other_kind(self):
        self.drafts = [proposed(8, JUMBLE, REWRITE, kind="item")]
        app = self.start()
        self.assertEqual(app.radio("card_kind_8").value, "Item")
        app.radio("card_kind_8").set_value("Rule").run()
        app.button("sendback_8").click().run()
        self.assertEqual(self.posts()[-1][2], {"kind": "rule"}, "a relabel alone is reason enough to send it back")
        self.assertTrue(any("Draft #8 sent back as a rule" in s.value for s in app.success))

    def test_send_back_carries_the_edit_and_the_card_stays_pinned(self):
        self.drafts = [proposed(8, JUMBLE, REWRITE)]
        app = self.start()
        app.button("sendback_8").click().run()
        self.assertEqual(self.posts(), [], "nothing changed, nothing sent")
        self.assertTrue(any("Edit the text, add a note or change Publish as" in i.value for i in app.info))
        edited = REWRITE + " Only uncrewed maritime and air programs."
        app.text_area("card_text_8").set_value(edited)
        app.text_input("card_note_8").set_value("Keep my maritime/air boundary.")
        app.button("sendback_8").click().run()
        post = self.posts()[-1]
        self.assertTrue(post[1].endswith("/rules/drafts/8/refine"))
        self.assertEqual(post[2], {"text": edited, "feedback": "Keep my maritime/air boundary."})
        self.assertTrue(any("sent back with your edit" in s.value for s in app.success))

        # Now with ChatGPT: pinned above everything, showing what was sent.
        sent = [{"round": 1, "text": "Keep my maritime/air boundary.", "edit": edited}]
        self.drafts = [proposed(9, "other words for another rule here", "Another rewrite for the owner to sign off."),
                       proposed(8, JUMBLE, REWRITE, feedback=sent, status="queued")]
        app = self.start()
        rendered = self.rendered(app)
        self.assertLess(rendered.index("With ChatGPT · 1"), rendered.index("Your turn · 1"))
        self.assertIn("You sent: " + edited, rendered)
        app.button("withdraw_8").click().run()
        self.assertTrue(self.posts()[-1][1].endswith("/rules/drafts/8/reject"))

        # Back from ChatGPT: first on the page, marked, and editable again.
        self.drafts = [proposed(9, "other words for another rule here", "Another rewrite for the owner to sign off."),
                       proposed(8, JUMBLE, REWRITE + " Only uncrewed maritime and air programs.", feedback=sent)]
        app = self.start()
        rendered = self.rendered(app)
        self.assertLess(rendered.index("Back from ChatGPT · 1"), rendered.index("Your turn · 1"))
        self.assertIn("your edit applied", rendered)

    def test_signature_only_updates_publish_in_bulk_and_first_versions_wait(self):
        revision = lambda i, rule: proposed(i, f"Rule text number {i} stays exactly the same.", f"Rule text number {i} stays exactly the same.", target=rule, run_id="owner-revision")
        waiting = [proposed(30 + i, f"a waiting rule in the owner's words, number {i}", None, status="queued") for i in range(4)]
        self.drafts = [revision(21, "R-0034"), revision(22, "R-0012"), proposed(23, "Loitering munitions are tier 2.", "Loitering munitions are tier 2 (70+).", target="R-0028", effect={"min_score": 70}), *waiting]
        app = self.start()
        labels = "\n".join(e.label for e in app.expander)
        self.assertIn("Signature-only updates · 2", labels)
        self.assertIn("Waiting for ChatGPT's first version · 4", labels)
        self.assertTrue(any(t.key == "card_text_23" for t in app.text_area), "a rewrite with score bounds gets its own card")
        self.assertFalse(any(t.key == "card_text_21" for t in app.text_area), "signature-only drafts are listed compactly")
        app.multiselect("signature_only_flip").set_value([22]).run()
        app.button("approve_signature_only").click().run()
        approvals = [c for c in self.posts() if c[1].endswith("/approve")]
        self.assertEqual([c[1].split("/")[-2] for c in approvals], ["21", "22"])
        self.assertEqual(approvals[0][2], {}, "an empty body publishes the proposal as written")
        self.assertEqual(approvals[1][2], {"kind": "item"}, "a picked one publishes as the other kind")

    def test_a_proposed_drop_is_signed_off_as_a_drop_never_as_an_approval(self):
        drop = proposed(41, "A new drone unveiling is not a digest item.", None, target="R-0034", run_id="owner-revision")
        drop["proposal"] = {"action": "drop", "rationale": "Fully covered by R-0001; it never changes a decision.", "duplicate_of": "R-0001", "overlaps": [], "conflicts": [], "supersedes": "R-0034"}
        retire = {**drop, "id": 42, "run_id": "reviewer-drop", "target_rule_id": "R-0012", "proposal": {**drop["proposal"], "duplicate_of": None, "supersedes": "R-0012"}}
        self.drafts = [drop, retire]
        app = self.start()
        rendered = self.rendered(app)
        self.assertIn("ChatGPT proposes dropping R-0034", rendered)
        self.assertIn("covered by R-0001", rendered)
        self.assertIn("ChatGPT proposes retiring R-0012", rendered)
        self.assertFalse(any(b.key == "publish_41" for b in app.button))
        app.button("drop_41").click().run()
        self.assertTrue(self.posts()[-1][1].endswith("/rules/drafts/41/drop"))
        self.assertTrue(any("Dropped R-0034" in s.value for s in app.success))
        app.button("keep_42").click().run()
        self.assertTrue(self.posts()[-1][1].endswith("/rules/drafts/42/reject"))

    def test_anything_decided_in_the_last_day_can_be_undone(self):
        self.recent = [{"id": 37, "status": "approved", "precedent_rule_id": "R-0038", "decided_at": "2026-09-27T22:31:14.844Z", "undo": {"type": "superseded"}, "undo_available": True,
                        "kind": "item", "raw_text": "police drone <renewals> are borderline for me", "text": "Routine municipal police-drone renewals stay borderline."},
                       {"id": 12, "status": "rejected", "decided_at": "2026-09-27T20:00:00.000Z", "undo": {"type": "rejected"}, "undo_available": True,
                        "kind": "rule", "raw_text": "my rough words " + "x" * 300, "text": "The rewrite", "proposal": {"text": "The discarded rewrite"}}]
        app = self.start()
        rendered = self.rendered(app)
        # Each row shows its label and the words the owner sent to ChatGPT.
        self.assertIn('loop-kind loop-kind-item', rendered)
        self.assertIn('<div class="recent-text">You sent: police drone &lt;renewals&gt; are borderline for me</div>', rendered)
        self.assertIn("You sent: my rough words", rendered)
        self.assertNotIn("x" * 260, rendered, "long texts are shortened")
        self.assertIn("Just decided · 2 · undo within 24 h", "\n".join(e.label for e in app.expander))
        rendered = self.rendered(app)
        self.assertIn("Published R-0038", rendered); self.assertIn("Discarded draft #12", rendered)
        app.button("undo_37").click().run()
        self.assertTrue(self.posts()[-1][1].endswith("/rules/drafts/37/undo"))
        self.assertTrue(any("Undone" in s.value for s in app.success))

    def test_rules_and_items_filter_search_revise_retire_and_restore(self):
        app = self.start()
        app.radio("ri_filter").set_value("Items").run()
        labels = [e.label for e in app.expander if e.label.startswith(("R-", "I-"))]
        self.assertEqual(len(labels), 1); self.assertTrue(labels[0].startswith("I-0001 · Item"))
        app.radio("ri_filter").set_value("All").run()
        app.text_input("ri_search").set_value("ceremonial").run()
        labels = [e.label for e in app.expander if e.label.startswith(("R-", "I-"))]
        self.assertEqual(len(labels), 1); self.assertTrue(labels[0].startswith("R-0002"))
        app.text_input("ri_note_R-0002").set_value("Only ribbon cuttings and bell ringings.")
        app.button("ri_revise_R-0002").click().run()
        post = self.posts()[-1]
        self.assertTrue(post[1].endswith("/rules/R-0002/refine")); self.assertEqual(post[2], {"feedback": "Only ribbon cuttings and bell ringings."})
        self.assertTrue(any("sent to ChatGPT as draft #13" in s.value for s in app.success))
        app.text_input("ri_search").set_value("").run()
        app.button("ri_retire_I-0001").click().run()
        self.assertTrue(self.posts()[-1][1].endswith("/rules/I-0001/deactivate"))
        app.radio("ri_filter").set_value("Inactive").run()
        app.button("ri_restore_R-0009").click().run()
        self.assertTrue(self.posts()[-1][1].endswith("/rules/R-0009/reactivate"))
        app.radio("ri_filter").set_value("Rules").run()
        app.button("rules_signature_pass").click().run()
        self.assertTrue(self.posts()[-1][1].endswith("/rules/refine-missing"))

    def test_a_trend_can_be_drafted_now(self):
        app = self.start()
        app.button("trend_draft_reason:not_my_focus").click().run()
        post = self.posts()[-1]
        self.assertTrue(post[1].endswith("/calibration/trends/draft")); self.assertEqual(post[2], {"key": "reason:not_my_focus"})
        self.assertTrue(any("draft #55" in s.value for s in app.success))

    def test_audit_form_posts_summary_and_focus(self):
        app = self.start()
        app.text_area("audit_summary").set_value("Robotaxi rejections drove the disagreements.")
        app.text_area("audit_focus").set_value("Grade every robotaxi rejection.")
        form = next(f for f in app.get("form") if f.proto.form.form_id == "audit_form")
        next(b for b in form.button if b.label == "Save audit").click().run()
        post = self.posts()[-1]
        self.assertTrue(post[1].endswith("/calibration/audit"))
        self.assertEqual(post[2], {"month": "2026-09", "summary": "Robotaxi rejections drove the disagreements.", "focus": "Grade every robotaxi rejection."})
        self.assertTrue(any("standing instruction #23" in s.value for s in app.success))


if __name__ == "__main__":
    unittest.main()
