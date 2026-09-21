import unittest
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from calibration_view import delta_text, pct
from rules_view import parse_signature, sort_rules


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


class RulesTabTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        self.calls = []
        self.guides = GUIDES
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
        if "/rules/drafts" in url:
            return StubResponse({"ok": True, "drafts": DRAFTS})
        if "/rules" in url:
            return StubResponse({"ok": True, "rules": RULES, "pending_drafts": 1})
        if "/calibration/summary" in url:
            return StubResponse(SUMMARY)
        if "/calibration/month" in url:
            return StubResponse(MONTH)
        if "/calibration/drilldown" in url:
            return StubResponse(DRILL)
        raise AssertionError(f"unexpected request: {url}")

    def fake_post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs.get("json")))
        if url.endswith("/approve"):
            return StubResponse({"ok": True, "rule_id": "R-0003", "distilled": 1, "precedent_id": 9})
        if url.endswith("/supersede"):
            return StubResponse({"ok": True, "superseded": "R-0001", "rule_id": "R-0004"})
        if url.endswith("/fold"):
            return StubResponse({"ok": True, "rule_id": "R-0001", "brief_version": "2026.10.1"})
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

    def test_helpers(self):
        self.assertEqual(parse_signature("workers: a, b; tickers: X; bogus: y"), {"workers": ["a", "b"], "tickers": ["X"]})
        self.assertEqual([r["rule_id"] for r in sort_rules(RULES)], ["R-0002", "R-0001", "R-scale-v1"])
        self.assertEqual(pct(0.667), "67%"); self.assertEqual(delta_text(0.167), "+17 pts vs prior month")

    def test_navigation_has_no_separate_calibration_view(self):
        app = self.start()
        view = next(radio for radio in app.radio if radio.label == "Dashboard view")
        self.assertEqual(list(view.options), ["Feed", "Rejected", "Rules", "Universe"])

    def test_pin_gate_makes_no_owner_calls(self):
        app = self.start(pin="")
        self.assertIn("enter the grader PIN", self.rendered(app))
        self.assertFalse(any("/rules" in c[1] or "/calibration" in c[1] for c in self.calls))

    def test_four_sections_render_with_the_pin_header(self):
        app = self.start()
        self.assertEqual([t.label for t in app.tabs], ["Drafts and rules", "Calibration", "Monthly audit", "How to grade"])
        rendered = self.rendered(app)
        # Drafts and rules
        self.assertIn("Pending drafts · 1", rendered); self.assertIn("Active rules · 3", rendered)
        self.assertIn(">ignored<", rendered); self.assertIn(">working<", rendered); self.assertIn(">no data yet<", rendered)
        self.assertLess(rendered.index("R-0002"), rendered.index("R-0001"))
        # Calibration
        metric = next(m for m in app.metric if m.label == "Action agreement")
        self.assertEqual(metric.value, "67%"); self.assertEqual(metric.delta, "+17 pts vs prior month")
        self.assertEqual(len(app.get("plotly_chart")), 2)
        self.assertTrue(any("Waymo now testing" in t.value.to_string() for t in app.get("table")))
        # Guides from the aggregator, audit form under the checklist
        self.assertIn("Monthly audit — 20 minutes", rendered); self.assertIn("Read the headline", rendered)
        self.assertIn("Grade disagreements, not agreements", rendered)
        self.assertIn("Prior month audit · 2026-08", rendered)
        self.assertTrue(any(f.proto.form.form_id == "audit_form" for f in app.get("form")))
        owner_calls = [c for c in self.calls if c[0] == "GET" and ("/rules" in c[1] or "/calibration" in c[1])]
        self.assertTrue(owner_calls and all(c[2] == {"X-Owner-Pin": "test-pin"} for c in owner_calls))
        guide_calls = [c for c in self.calls if c[1].endswith("/grades/guide")]
        self.assertEqual(len(guide_calls), 1, "guides fetched once and cached")

    def test_guides_unavailable_shows_fallback_not_an_error(self):
        self.guides = {}
        app = self.start()
        rendered = "\n".join(c.value for c in app.caption)
        self.assertIn("Guide unavailable", rendered)
        self.assertEqual(list(app.error), [])

    def test_draft_approval_posts_the_edited_text(self):
        app = self.start()
        app.text_area("draft_text_7").set_value("Robotaxi new-market launches by Waymo, Tesla or Zoox are digest items; score 70 or more.")
        form = next(f for f in app.get("form") if f.proto.form.form_id == "draft_7")
        next(b for b in form.button if b.label == "Approve").click().run()
        self.assertEqual(list(app.exception), [])
        post = next(c for c in self.calls if c[0] == "POST")
        self.assertTrue(post[1].endswith("/rules/drafts/7/approve"))
        self.assertEqual(post[2]["signature"], {"workers": ["robotaxi-monitor"], "keywords": ["waymo"]})
        self.assertIn("Zoox", post[2]["text"])
        self.assertTrue(any("Approved as R-0003" in s.value for s in app.success))

    def test_supersede_and_fold(self):
        app = self.start()
        form = next(f for f in app.get("form") if f.proto.form.form_id == "rule_action")
        next(b for b in form.button if b.label == "Supersede").click().run()
        self.assertFalse(any(c[0] == "POST" for c in self.calls))
        app.text_area("rule_action_text").set_value("Freshness is judged by the underlying event date; 3+ week old events are excluded.")
        form = next(f for f in app.get("form") if f.proto.form.form_id == "rule_action")
        next(b for b in form.button if b.label == "Supersede").click().run()
        self.assertTrue(next(c for c in self.calls if c[0] == "POST")[1].endswith("/rules/R-0001/supersede"))
        app.text_input("rule_action_fold").set_value("2026.10.1")
        form = next(f for f in app.get("form") if f.proto.form.form_id == "rule_action")
        next(b for b in form.button if b.label == "Fold into brief").click().run()
        fold = [c for c in self.calls if c[0] == "POST" and c[1].endswith("/fold")]
        self.assertEqual(fold[0][2], {"brief_version": "2026.10.1"})
        self.assertTrue(any("folded into 2026.10.1" in s.value for s in app.success))

    def test_audit_form_posts_summary_and_focus(self):
        app = self.start()
        app.text_area("audit_summary").set_value("Robotaxi rejections drove the disagreements.")
        app.text_area("audit_focus").set_value("Grade every robotaxi rejection.")
        form = next(f for f in app.get("form") if f.proto.form.form_id == "audit_form")
        next(b for b in form.button if b.label == "Save audit").click().run()
        post = next(c for c in self.calls if c[0] == "POST")
        self.assertTrue(post[1].endswith("/calibration/audit"))
        self.assertEqual(post[2], {"month": "2026-09", "summary": "Robotaxi rejections drove the disagreements.", "focus": "Grade every robotaxi rejection."})
        self.assertTrue(any("standing instruction #23" in s.value for s in app.success))


if __name__ == "__main__":
    unittest.main()
