import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"

VOCABULARY = {
    "ok": True,
    "reason_codes": ["material", "below_materiality", "stale", "wrong_tier", "wrong_action"],
    "actions": ["lead", "digest", "borderline", "reject", "urgent"],
    "scale": [
        {"action": "lead", "min": 90, "max": 100, "label": "Lead item"},
        {"action": "digest", "min": 70, "max": 89, "label": "In the digest"},
        {"action": "borderline", "min": 40, "max": 69, "label": "Borderline"},
        {"action": "reject", "min": 0, "max": 39, "label": "Correct rejection"},
    ],
}


class StubResponse:
    text = ""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def digest(post_id, offset=0):
    posted_at = datetime(2026, 9, 7, 16, tzinfo=timezone.utc) - timedelta(hours=offset)
    return {
        "id": post_id,
        "posted_at": posted_at.isoformat(),
        "trigger_label": "12pm ET",
        "headline": f"Digest edition {post_id}",
        "items": [
            {
                "rank": 1,
                "event_id": post_id * 10 + 1,
                "event_ids": [post_id * 10 + 1],
                "headline": "Shared autonomy procurement story",
                "text": f"First article in digest {post_id}.",
                "url": f"https://example.com/{post_id}/1",
                "worker": "aviation-tracker",
            },
            {
                # A nonconsecutive rank catches accidental reindexing in search.
                "rank": 4,
                "event_id": post_id * 10 + 4,
                "event_ids": [post_id * 10 + 4],
                "headline": f"Robotics deployment {post_id}",
                "text": f"Second article in digest {post_id}.",
                "url": f"https://example.com/{post_id}/4",
                "worker": "news-monitor",
            },
            {
                # Legacy item without an event id: shown, but not gradable.
                "rank": 6,
                "text": "Old-style item",
                "url": f"https://example.com/{post_id}/6",
                "worker": "news-monitor",
            },
        ],
    }


def rejected_item(event_id):
    return {
        "id": event_id,
        "title": f"Rejected candidate {event_id}",
        "url": f"https://example.com/rejected/{event_id}",
        "worker": "robotaxi-monitor",
        "ts": "2026-09-17T18:00:00Z",
    }


class DigestGradingTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        self.daily = [digest(101), digest(102, offset=1)]
        self.rejected = [rejected_item(14683), rejected_item(14667)]
        self.context_requests = []
        get_patch = patch("requests.get", side_effect=self.fake_get)
        get_patch.start()
        self.addCleanup(get_patch.stop)
        post_patch = patch(
            "requests.post",
            return_value=StubResponse({"ok": True, "id": 74, "stored": 1, "rule_draft_id": None,
                                       "grade": {"target_score": 75, "target_action": "digest"}}),
        )
        self.post = post_patch.start()
        self.addCleanup(post_patch.stop)

    def fake_get(self, url, **kwargs):
        if url.endswith("/digests"):
            return StubResponse({"daily": self.daily, "weekly": []})
        if url.endswith("/health"):
            return StubResponse({"ok": True})
        if url.endswith("/rejected"):
            return StubResponse({"items": self.rejected, "prefilter_kills": []})
        if url.endswith("/grades/vocabulary"):
            return StubResponse(VOCABULARY)
        if url.endswith("/grades/context"):
            ids = [int(i) for i in kwargs["params"]["event_ids"].split(",")]
            self.context_requests.append(ids)
            events = {
                str(i): {"grader": {"run_id": "r2", "decision": "rejected", "score": 40, "action": "reject", "reason_code": "below_materiality"},
                         "grade_count": 0, "latest_grade": None}
                for i in ids
            }
            return StubResponse({"ok": True, "events": events})
        raise AssertionError(f"unexpected dashboard request: {url}")

    def start_app(self, owner=False, pin="", view="Feed"):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["grading_enabled"] = owner
        app.session_state["grader_pin"] = pin
        app.session_state["dashboard_view"] = view
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def forms(self, app, prefix="grade_daily_"):
        # Inspect native form containment, rather than just checking that the
        # right number of widgets exists somewhere at the bottom of the feed.
        return {
            form.proto.form.form_id: form
            for form in app.get("form")
            if form.proto.form.form_id.startswith(prefix)
        }

    def submit(self, app, form_id, prefix="grade_daily_"):
        form = self.forms(app, prefix)[form_id]
        next(button for button in form.button if button.label == "Submit grade").click().run()
        self.assertEqual(list(app.exception), [])

    def test_owner_toggle_places_the_grade_form_inside_each_digest_panel(self):
        app = self.start_app()
        self.assertEqual(self.forms(app), {})
        self.assertFalse(any(slider.key.startswith("gscore_daily_") for slider in app.slider))

        app.checkbox("grading_enabled").check().run()
        self.assertEqual(list(app.exception), [])
        forms = self.forms(app)
        self.assertEqual(list(forms), ["grade_daily_101", "grade_daily_102"])

        for post_id, other_id in [(101, 102), (102, 101)]:
            form = forms[f"grade_daily_{post_id}"]
            rendered = "\n".join(markdown.value for markdown in form.markdown)
            self.assertIn(f"Digest edition {post_id}", rendered)
            self.assertNotIn(f"Digest edition {other_id}", rendered)
            # Grader context is shown for the gradable items, and the legacy rank is called out.
            self.assertIn("Grader: reject · score 40 · below_materiality", rendered)
            self.assertIn("Not gradable with the new form", "\n".join(c.value for c in form.caption))
            self.assertEqual([s.key for s in form.selectbox], [f"gitem_daily_{post_id}", f"gaction_daily_{post_id}", f"greason_daily_{post_id}"])
            self.assertEqual([s.key for s in form.slider], [f"gscore_daily_{post_id}"])
            self.assertEqual([r.key for r in form.radio], [f"gscope_daily_{post_id}"])
            self.assertEqual([note.key for note in form.text_area], [f"note_daily_{post_id}"])
            self.assertEqual([button.label for button in form.button], ["Submit grade"])
            # Only the two items with event ids are offered.
            self.assertEqual(len(form.selectbox[0].options), 2)
            nodes = list(form)
            digest_index = next(i for i, node in enumerate(nodes) if node.type == "markdown" and f"Digest edition {post_id}" in node.value)
            first_widget = next(i for i, node in enumerate(nodes) if node.type == "selectbox")
            self.assertLess(digest_index, first_widget)

        # One context request per edition, for exactly its gradable events.
        self.assertIn([1011, 1014], self.context_requests)
        self.assertIn([1021, 1024], self.context_requests)

        app.checkbox("grading_enabled").uncheck().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual(self.forms(app), {})
        self.post.assert_not_called()

    def test_loaded_older_digests_each_receive_grade_forms(self):
        self.daily = [digest(101 + index, offset=index) for index in range(15)]
        app = self.start_app(owner=True)
        self.assertEqual(len(self.forms(app)), 10)
        app.button("button_daily_limit").click().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual(set(self.forms(app)), {f"grade_daily_{post_id}" for post_id in range(101, 116)})

    def test_feed_grade_posts_one_self_contained_row_with_client_resolved_event_id(self):
        app = self.start_app(owner=True, pin="test-pin")
        app.selectbox("gitem_daily_102").select_index(1)
        app.slider("gscore_daily_102").set_value(92)
        app.selectbox("greason_daily_102").select("wrong_tier")
        app.text_area("note_daily_102").set_value("  Should have led  ")
        app.slider("gscore_daily_101").set_value(12)
        self.submit(app, "grade_daily_102")

        self.post.assert_called_once()
        self.assertTrue(self.post.call_args.args[0].endswith("/grades"))
        self.assertEqual(self.post.call_args.kwargs["headers"], {"X-Owner-Pin": "test-pin"})
        self.assertEqual(
            self.post.call_args.kwargs["json"],
            {
                "post_type": "daily", "post_id": 102, "item_rank": 4, "event_id": 1024,
                "target_score": 92, "target_action": None, "reason_code": "wrong_tier",
                "scope": "item", "note": "Should have led",
            },
        )
        self.assertEqual(len(self.forms(app)["grade_daily_102"].success), 1)
        # The other edition's draft is untouched.
        self.assertEqual(app.slider("gscore_daily_101").value, 12)

    def test_action_override_and_rule_scope(self):
        app = self.start_app(owner=True, pin="test-pin")
        app.selectbox("gaction_daily_101").select("urgent")
        app.radio("gscope_daily_101").set_value("rule")
        self.submit(app, "grade_daily_101")
        self.post.assert_not_called()
        self.assertEqual(len(self.forms(app)["grade_daily_101"].info), 1)

        app.text_area("note_daily_101").set_value("Every covered-company procurement award is a digest item at any size.")
        self.submit(app, "grade_daily_101")
        self.post.assert_called_once()
        payload = self.post.call_args.kwargs["json"]
        self.assertEqual(payload["target_action"], "urgent")
        self.assertEqual(payload["scope"], "rule")
        self.assertEqual(payload["event_id"], 1011)

    def test_missing_pin_keeps_submission_local_to_digest(self):
        app = self.start_app(owner=True)
        self.submit(app, "grade_daily_101")
        self.post.assert_not_called()
        warnings = self.forms(app)["grade_daily_101"].warning
        self.assertEqual(len(warnings), 1)
        self.assertIn("PIN", warnings[0].value)
        self.assertEqual(len(self.forms(app)["grade_daily_102"].warning), 0)

    def test_worker_errors_are_shown_verbatim(self):
        self.post.return_value = StubResponse({"ok": False, "error": "invalid grade", "errors": ["reason_code must be one of ..."]}, 400)
        app = self.start_app(owner=True, pin="test-pin")
        self.submit(app, "grade_daily_101")
        errors = self.forms(app)["grade_daily_101"].error
        self.assertEqual(len(errors), 1)
        self.assertIn("reason_code", errors[0].value)

    def test_rejected_grade_posts_the_same_row_shape(self):
        app = self.start_app(owner=True, pin="test-pin", view="Rejected")
        forms = self.forms(app, "rejected_grading_")
        self.assertEqual(len(forms), 1)
        (form_id, form), = forms.items()
        key = form.selectbox[0].key
        self.assertTrue(key.startswith("gitem_rejected_"))
        suffix = key[len("gitem_"):]
        self.assertIn([14683, 14667], self.context_requests)

        app.selectbox(key).select_index(1)
        app.slider(f"gscore_{suffix}").set_value(35)
        app.selectbox(f"greason_{suffix}").select("stale")
        self.submit(app, form_id, "rejected_grading_")
        self.post.assert_called_once()
        self.assertTrue(self.post.call_args.args[0].endswith("/grades"))
        self.assertEqual(
            self.post.call_args.kwargs["json"],
            {
                "post_type": "rejected", "post_id": 14667, "item_rank": None, "event_id": 14667,
                "target_score": 35, "target_action": None, "reason_code": "stale",
                "scope": "item", "note": "",
            },
        )


if __name__ == "__main__":
    unittest.main()
