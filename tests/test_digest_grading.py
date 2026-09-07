import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"


class StubResponse:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self.payload = payload

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
                "headline": "Shared autonomy procurement story",
                "text": f"First article in digest {post_id}.",
                "url": f"https://example.com/{post_id}/1",
                "worker": "aviation-tracker",
            },
            {
                # A nonconsecutive rank catches accidental reindexing in search.
                "rank": 4,
                "headline": f"Robotics deployment {post_id}",
                "text": f"Second article in digest {post_id}.",
                "url": f"https://example.com/{post_id}/4",
                "worker": "news-monitor",
            },
        ],
    }


class DigestGradingTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        self.daily = [digest(101), digest(102, offset=1)]
        get_patch = patch("requests.get", side_effect=self.fake_get)
        get_patch.start()
        self.addCleanup(get_patch.stop)
        post_patch = patch("requests.post", return_value=StubResponse({"stored": 1}))
        self.post = post_patch.start()
        self.addCleanup(post_patch.stop)

    def fake_get(self, url, **_kwargs):
        if url.endswith("/digests"):
            return StubResponse({"daily": self.daily, "weekly": []})
        if url.endswith("/health"):
            return StubResponse({"ok": True})
        if url.endswith("/rejected"):
            return StubResponse({"items": [], "prefilter_kills": []})
        raise AssertionError(f"unexpected dashboard request: {url}")

    def start_app(self, owner=False, pin=""):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["grading_enabled"] = owner
        app.session_state["grader_pin"] = pin
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        return app

    def forms(self, app):
        # Inspect native form containment, rather than just checking that the
        # right number of widgets exists somewhere at the bottom of the feed.
        return {
            form.proto.form.form_id: form
            for form in app.get("form")
            if form.proto.form.form_id.startswith("grade_daily_")
        }

    def submit(self, app, post_id):
        form = self.forms(app)[f"grade_daily_{post_id}"]
        next(button for button in form.button if button.label == "Submit grades").click().run()
        self.assertEqual(list(app.exception), [])

    def test_owner_toggle_places_controls_inside_each_digest_panel(self):
        app = self.start_app()
        self.assertEqual(self.forms(app), {})
        self.assertFalse(any(radio.key.startswith("g_daily_") for radio in app.radio))

        app.checkbox("grading_enabled").check().run()
        self.assertEqual(list(app.exception), [])
        forms = self.forms(app)
        self.assertEqual(list(forms), ["grade_daily_101", "grade_daily_102"])
        self.assertFalse(any(expander.label == "Rate published editions" for expander in app.expander))

        for post_id, other_id in [(101, 102), (102, 101)]:
            form = forms[f"grade_daily_{post_id}"]
            rendered = "\n".join(markdown.value for markdown in form.markdown)
            self.assertIn(f"Digest edition {post_id}", rendered)
            self.assertNotIn(f"Digest edition {other_id}", rendered)
            self.assertEqual(
                [radio.key for radio in form.radio],
                [f"g_daily_{post_id}_1", f"g_daily_{post_id}_4"],
            )
            self.assertEqual([note.key for note in form.text_area], [f"note_daily_{post_id}"])
            self.assertEqual([button.label for button in form.button], ["Submit grades"])
            nodes = list(form)
            digest_index = next(
                index for index, node in enumerate(nodes)
                if node.type == "markdown" and f"Digest edition {post_id}" in node.value
            )
            first_grade_index = next(index for index, node in enumerate(nodes) if node.type == "radio")
            self.assertLess(digest_index, first_grade_index)

        app.checkbox("grading_enabled").uncheck().run()
        self.assertEqual(list(app.exception), [])
        self.assertEqual(self.forms(app), {})
        self.post.assert_not_called()

    def test_loaded_older_digests_each_receive_grading_controls(self):
        self.daily = [digest(101 + index, offset=index) for index in range(15)]
        app = self.start_app(owner=True)
        self.assertEqual(len(self.forms(app)), 10)

        app.button("button_daily_limit").click().run()
        self.assertEqual(list(app.exception), [])
        forms = self.forms(app)
        self.assertEqual(len(forms), 15)
        self.assertEqual(
            set(forms), {f"grade_daily_{post_id}" for post_id in range(101, 116)}
        )
        self.assertEqual(
            [radio.key for radio in forms["grade_daily_115"].radio],
            ["g_daily_115_1", "g_daily_115_4"],
        )

    def test_submitting_one_digest_keeps_feedback_isolated(self):
        app = self.start_app(owner=True, pin="test-pin")
        app.radio("g_daily_101_1").set_value("👍")
        app.text_area("note_daily_101").set_value("First digest draft")
        app.radio("g_daily_102_4").set_value("👎")
        app.text_area("note_daily_102").set_value("  Second digest feedback  ")
        self.submit(app, 102)

        self.post.assert_called_once()
        self.assertTrue(self.post.call_args.args[0].endswith("/grade"))
        self.assertEqual(
            self.post.call_args.kwargs["json"],
            {
                "pin": "test-pin",
                "post_type": "daily",
                "post_id": 102,
                "grades": [{"rank": 4, "verdict": "down"}],
                "note": "Second digest feedback",
            },
        )
        self.assertEqual(app.radio("g_daily_101_1").value, "👍")
        self.assertEqual(app.text_area("note_daily_101").value, "First digest draft")
        self.assertEqual(len(self.forms(app)["grade_daily_102"].success), 1)

        app.run()
        self.assertEqual(list(app.exception), [])
        self.post.assert_called_once()
        self.assertEqual(app.radio("g_daily_101_1").value, "👍")

    def test_search_grades_only_matching_articles_using_original_rank(self):
        self.daily[1]["items"][1]["headline"] = "Unique needle-search robotics story"
        app = self.start_app(owner=True, pin="test-pin")
        app.radio("g_daily_102_1").set_value("👍")
        app.text_input("feed_search").set_value("needle-search").run()
        self.assertEqual(list(app.exception), [])
        forms = self.forms(app)
        self.assertEqual(list(forms), ["grade_daily_102"])
        self.assertEqual([radio.key for radio in forms["grade_daily_102"].radio], ["g_daily_102_4"])
        self.assertTrue(forms["grade_daily_102"].radio[0].label.startswith("4."))

        app.radio("g_daily_102_4").set_value("👍")
        self.submit(app, 102)
        self.post.assert_called_once()
        payload = self.post.call_args.kwargs["json"]
        self.assertEqual(payload["post_id"], 102)
        self.assertEqual(payload["grades"], [{"rank": 4, "verdict": "up"}])

    def test_missing_pin_keeps_submission_local_to_digest(self):
        app = self.start_app(owner=True)
        app.radio("g_daily_101_1").set_value("👍")
        self.submit(app, 101)
        self.post.assert_not_called()
        warnings = self.forms(app)["grade_daily_101"].warning
        self.assertEqual(len(warnings), 1)
        self.assertIn("PIN", warnings[0].value)
        self.assertEqual(len(self.forms(app)["grade_daily_102"].warning), 0)

    def test_empty_feedback_does_not_post_but_note_only_feedback_does(self):
        app = self.start_app(owner=True, pin="test-pin")
        self.submit(app, 101)
        self.post.assert_not_called()
        self.assertEqual(len(self.forms(app)["grade_daily_101"].info), 1)

        app.text_area("note_daily_101").set_value("Move procurement stories higher")
        self.submit(app, 101)
        self.post.assert_called_once()
        payload = self.post.call_args.kwargs["json"]
        self.assertEqual(payload["grades"], [])
        self.assertEqual(payload["note"], "Move procurement stories higher")


if __name__ == "__main__":
    unittest.main()
