import unittest
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from calibration_view import pct, delta_text


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"


class StubResponse:
    text = ""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def overall(month, agreement, gap, n=10, dis=3):
    return {"month": month, "dimension": "overall", "dimension_value": "all", "n_graded": n, "n_late": 1, "n_comparable": n - 1, "n_disagreements": dis,
            "action_agreement": agreement, "mean_score_gap": gap, "false_negative_rate": 0.2, "false_positive_rate": 0.0, "median_lag_hours": 3.5}


SUMMARY = {
    "ok": True, "months": ["2026-08", "2026-09"], "latest_month": "2026-09", "prior_month": "2026-08", "provisional": True,
    "headline": {**overall("2026-09", 0.667, -18.3), "prior_action_agreement": 0.5, "delta": 0.167},
    "trend": [{"month": "2026-08", "action_agreement": 0.5, "mean_score_gap": -30, "n_graded": 8, "n_disagreements": 4},
              {"month": "2026-09", "action_agreement": 0.667, "mean_score_gap": -18.3, "n_graded": 10, "n_disagreements": 3}],
    "worst": [{"dimension": "worker", "dimension_value": "robotaxi-monitor", "n_graded": 4, "n_comparable": 4, "n_disagreements": 2, "action_agreement": 0.5, "mean_score_gap": -20}],
    "most_improved": [{"dimension": "tab", "dimension_value": "rejected", "n_graded": 6, "n_comparable": 5, "n_disagreements": 1, "action_agreement": 0.8, "mean_score_gap": -10, "prior_action_agreement": 0.4, "delta": 0.4}],
    "rules": [{"rule_id": "R-0002", "cited": 0, "applicable": 5, "agreement_when_cited": None, "agreement_when_applicable_not_cited": 0.4, "state": "ignored"},
              {"rule_id": "R-0009", "cited": 4, "applicable": 5, "agreement_when_cited": 0.9, "agreement_when_applicable_not_cited": None, "state": "working"}],
    "rules_added_last_month": ["R-0009"],
    "context": {"month": "2026-09", "active_rules": 38}, "prior_audit": {"summary": "August: mostly late reposts.", "focus": "Grade every rejection."}, "latest_audit": None,
}
MONTH = {"ok": True, "month": "2026-09", "dimensions": [overall("2026-09", 0.667, -18.3), {"month": "2026-09", "dimension": "worker", "dimension_value": "robotaxi-monitor", "n_graded": 4, "n_comparable": 4, "n_disagreements": 2, "action_agreement": 0.5, "mean_score_gap": -20}], "rules": [], "context": {}, "audit": []}
DRILL = {"ok": True, "grades": [{"id": 73, "event_id": 14683, "title": "Waymo now testing in Pittsburgh", "target_score": 75, "owner_action": "digest", "reason_code": "wrong_action", "grader_score": 40, "grader_action": "reject", "grader_reason_code": "below_materiality", "agree": False, "late": False, "note": "Robotaxi expansions are key"}]}


class CalibrationViewTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        self.calls = []
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
        if "/calibration/summary" in url:
            return StubResponse(SUMMARY)
        if "/calibration/month" in url:
            return StubResponse(MONTH)
        if "/calibration/drilldown" in url:
            return StubResponse(DRILL)
        raise AssertionError(f"unexpected request: {url}")

    def fake_post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs.get("json")))
        return StubResponse({"ok": True, "id": 1, "month": "2026-09", "standing_instruction_id": 23})

    def start(self, pin="test-pin"):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["grader_pin"] = pin
        app.session_state["dashboard_view"] = "Calibration"
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def test_helpers(self):
        self.assertEqual(pct(0.667), "67%"); self.assertEqual(pct(None), "n/a")
        self.assertEqual(delta_text(0.167), "+17 pts vs prior month"); self.assertEqual(delta_text(None), "no prior month to compare")

    def test_pin_gate(self):
        app = self.start(pin="")
        self.assertIn("enter the grader PIN", "\n".join(m.value for m in app.markdown))
        self.assertFalse(any("/calibration" in c[1] for c in self.calls))

    def test_tab_reads_only_calibration_tables_and_renders_every_section(self):
        app = self.start()
        urls = [c[1] for c in self.calls if c[0] == "GET" and "/calibration" in c[1]]
        self.assertTrue(all("/calibration/" in u for u in urls))
        self.assertTrue(all(c[2] == {"X-Owner-Pin": "test-pin"} for c in self.calls if c[0] == "GET" and "/calibration" in c[1]))
        labels = [m.label for m in app.metric]
        self.assertIn("Action agreement", labels)
        metric = next(m for m in app.metric if m.label == "Action agreement")
        self.assertEqual(metric.value, "67%"); self.assertEqual(metric.delta, "+17 pts vs prior month")
        rendered = "\n".join(m.value for m in app.markdown)
        self.assertIn("provisional", rendered)
        self.assertIn("Prior month audit · 2026-08", rendered); self.assertIn("August: mostly late reposts.", rendered)
        self.assertIn("R-0002", rendered); self.assertIn(">ignored<", rendered); self.assertIn(">working<", rendered)
        self.assertLess(rendered.index("R-0002"), rendered.index("R-0009"))
        self.assertIn("added last month", rendered)
        self.assertEqual(len(app.get("plotly_chart")), 2)
        # Drill-down table shows the grade against the grader.
        tables = app.get("table")
        self.assertTrue(any("Waymo now testing" in t.value.to_string() for t in tables))
        # "Only rules added last month" hides R-0002.
        app.checkbox("cal_only_added").check().run()
        rendered = "\n".join(m.value for m in app.markdown)
        self.assertNotIn("R-0002", rendered); self.assertIn("R-0009", rendered)

    def test_audit_form_posts_summary_and_focus(self):
        app = self.start()
        form = next(f for f in app.get("form") if f.proto.form.form_id == "audit_form")
        next(b for b in form.button if b.label == "Save audit").click().run()
        self.assertFalse(any(c[0] == "POST" for c in self.calls))
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
