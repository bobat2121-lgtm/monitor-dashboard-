import unittest
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

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


class RulesViewTests(unittest.TestCase):
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
        if "/rules/drafts" in url:
            return StubResponse({"ok": True, "drafts": DRAFTS})
        if "/rules" in url:
            return StubResponse({"ok": True, "rules": RULES, "pending_drafts": 1})
        raise AssertionError(f"unexpected request: {url}")

    def fake_post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs.get("json")))
        if url.endswith("/approve"):
            return StubResponse({"ok": True, "rule_id": "R-0003", "distilled": 1, "precedent_id": 9})
        if url.endswith("/supersede"):
            return StubResponse({"ok": True, "superseded": "R-0001", "rule_id": "R-0004"})
        return StubResponse({"ok": True})

    def start(self, pin="test-pin"):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["grader_pin"] = pin
        app.session_state["dashboard_view"] = "Rules"
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def test_helpers(self):
        self.assertEqual(parse_signature("workers: a, b; tickers: X; bogus: y"), {"workers": ["a", "b"], "tickers": ["X"]})
        self.assertEqual([r["rule_id"] for r in sort_rules(RULES)], ["R-0002", "R-0001", "R-scale-v1"])

    def test_pin_gate(self):
        app = self.start(pin="")
        rendered = "\n".join(m.value for m in app.markdown)
        self.assertIn("enter the grader PIN", rendered)
        self.assertFalse(any("/rules" in c[1] for c in self.calls))

    def test_tab_renders_drafts_and_rules_with_badges_and_posts_approval(self):
        app = self.start()
        rendered = "\n".join(m.value for m in app.markdown)
        self.assertIn("Pending drafts · 1", rendered)
        self.assertIn("Active rules · 3", rendered)
        self.assertIn(">ignored<", rendered)
        self.assertIn(">working<", rendered)
        self.assertIn(">no data yet<", rendered)
        # ignored sorts before working before no data
        self.assertLess(rendered.index("R-0002"), rendered.index("R-0001"))
        headers = [c[2] for c in self.calls if c[0] == "GET" and "/rules" in c[1]]
        self.assertTrue(all(h == {"X-Owner-Pin": "test-pin"} for h in headers))

        app.text_area("draft_text_7").set_value("Robotaxi new-market launches by Waymo, Tesla or Zoox are digest items; score 70 or more.")
        form = next(f for f in app.get("form") if f.proto.form.form_id == "draft_7")
        next(b for b in form.button if b.label == "Approve").click().run()
        self.assertEqual(list(app.exception), [])
        post = next(c for c in self.calls if c[0] == "POST")
        self.assertTrue(post[1].endswith("/rules/drafts/7/approve"))
        self.assertEqual(post[2]["signature"], {"workers": ["robotaxi-monitor"], "keywords": ["waymo"]})
        self.assertIn("Zoox", post[2]["text"])
        self.assertTrue(any("Approved as R-0003" in s.value for s in app.success))

    def test_supersede_requires_text_then_posts(self):
        app = self.start()
        form = next(f for f in app.get("form") if f.proto.form.form_id == "rule_action")
        next(b for b in form.button if b.label == "Supersede").click().run()
        self.assertFalse(any(c[0] == "POST" for c in self.calls))
        app.text_area("rule_action_text").set_value("Freshness is judged by the underlying event date; 3+ week old events are excluded.")
        form = next(f for f in app.get("form") if f.proto.form.form_id == "rule_action")
        next(b for b in form.button if b.label == "Supersede").click().run()
        post = next(c for c in self.calls if c[0] == "POST")
        self.assertTrue(post[1].endswith("/rules/R-0001/supersede"))
        self.assertTrue(any("superseded by R-0004" in s.value for s in app.success))


if __name__ == "__main__":
    unittest.main()
