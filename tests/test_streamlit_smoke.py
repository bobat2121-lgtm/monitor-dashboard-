import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"


class StubResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def fake_get(url, **_kwargs):
    if url.endswith("/health"):
        return StubResponse(
            {
                "ok": True,
                "status": "healthy",
                "schema_version": 6,
                "unread": 0,
                "staleness": {
                    "lastReview": "2026-09-04T10:00:00Z",
                    "lastOutcome": "reviewed_no_publish",
                    "lastTriggerLabel": "7am ET",
                    "lastItemCount": 0,
                    "reviewBoundary": 8108,
                },
            }
        )
    if url.endswith("/digests"):
        return StubResponse({"daily": [], "weekly": []})
    if url.endswith("/rejected"):
        return StubResponse({"items": [], "prefilter_kills": []})
    raise AssertionError(f"unexpected dashboard request: {url}")


class StreamlitStartupTests(unittest.TestCase):
    def test_feed_and_rejected_views_start_without_exceptions(self):
        # This catches Streamlit lifecycle errors such as reading st.secrets
        # before set_page_config, while keeping CI independent of production.
        with patch("requests.get", side_effect=fake_get):
            app = AppTest.from_file(str(APP_PATH), default_timeout=30).run(timeout=30)
            self.assertEqual(list(app.exception), [])

            view = next(radio for radio in app.radio if radio.label == "Dashboard view")
            view.set_value("Rejected")
            app.run(timeout=30)
            self.assertEqual(list(app.exception), [])


if __name__ == "__main__":
    unittest.main()
