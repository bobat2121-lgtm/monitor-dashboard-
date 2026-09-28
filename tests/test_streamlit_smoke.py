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
        return StubResponse(
            {
                "daily": [
                    {
                        "id": 1,
                        "posted_at": "2026-09-04T16:13:31Z",
                        "trigger_label": "12pm ET",
                        "headline": "Physical AI deployments advance",
                        "reviewed": 19,
                        "themes": [{"label": "Defense", "count": 1}, {"label": "Space", "count": 1}],
                        "brief": {
                            "threads": [
                                {"label": "Drone <buying>", "ranks": [1, 2], "theme": "Defense"},
                                {"label": "Legacy", "ranks": [2], "theme": "Defense"},
                            ],
                            "source": "reviewer",
                        },
                        "items": [
                            {
                                "rank": 1,
                                "headline": "Air Force <accelerates> its lower-cost MQ-9 successor",
                                "text": "The service plans at least 180 unmanned aircraft.",
                                "url": "https://example.com/source",
                                "worker": "aviation-tracker",
                                "theme": "Defense",
                                "value": "Defense autonomy procurement",
                            },
                            {
                                "rank": 2,
                                "text": "A legacy digest item still renders without a headline.",
                                "url": "https://example.com/legacy",
                                "worker": "news-monitor",
                                "value": "medium",
                            },
                        ],
                    }
                ],
                "weekly": [],
            }
        )
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
            rendered = "\n".join(markdown.value for markdown in app.markdown)
            self.assertEqual(rendered.count('<div class="feed-item-headline">'), 1)
            self.assertIn("Air Force &lt;accelerates&gt; its lower-cost MQ-9 successor", rendered)
            self.assertIn("The service plans at least 180 unmanned aircraft.", rendered)
            self.assertIn("A legacy digest item still renders without a headline.", rendered)
            # The edition's topic tags render under the headline, escaped, without
            # item numbers, each in its own colour (a repeated theme moves on).
            self.assertIn('<span class="edition-thread" style="color:#b692f6;background:rgba(182,146,246,0.1);border-color:rgba(182,146,246,0.38)">Drone &lt;buying&gt;</span>', rendered)
            self.assertIn('<span class="edition-thread" style="color:#4fd1c5;background:rgba(79,209,197,0.1);border-color:rgba(79,209,197,0.38)">Legacy</span>', rendered)
            # The latest edition's stats panel: counts, the theme bar and its legend.
            self.assertIn('<div class="stat"><div class="stat-n">2</div><div class="stat-l">ITEMS</div></div>', rendered)
            self.assertIn('<div class="stat"><div class="stat-n">19</div><div class="stat-l">REVIEWED</div></div>', rendered)
            self.assertIn('<div class="stat stat-medium"><div class="stat-n">1</div><div class="stat-l">MEDIUM</div></div>', rendered)
            self.assertIn('<span style="flex-grow:1;background:#4fd1c5"></span>', rendered)
            self.assertIn('<span><i style="background:#b692f6"></i>DEFENSE 1</span>', rendered)
            # Each item carries its theme label.
            self.assertIn('<span class="feed-theme"><i style="background:#b692f6"></i>Defense</span>', rendered)
            self.assertIn('<span class="value-badge level-medium">Medium</span>', rendered)

            search = next(field for field in app.text_input if field.label == "Search published stories")
            search.set_value("legacy").run()
            self.assertEqual(list(app.exception), [])
            filtered = "\n".join(markdown.value for markdown in app.markdown)
            self.assertIn("1 search result", filtered)
            self.assertIn("A legacy digest item still renders without a headline.", filtered)
            self.assertNotIn('class="edition-thread"', filtered, "search results leave out the edition brief")
            self.assertNotIn("Air Force &lt;accelerates&gt;", filtered)
            search.set_value("no-such-story-xxxxx").run()
            self.assertIn("No matching stories.", "\n".join(m.value for m in app.markdown))
            search.set_value("").run()
            self.assertIn("Air Force &lt;accelerates&gt;", "\n".join(m.value for m in app.markdown))

            view = next(radio for radio in app.radio if radio.label == "Dashboard view")
            view.set_value("Rejected")
            app.run(timeout=30)
            self.assertEqual(list(app.exception), [])


if __name__ == "__main__":
    unittest.main()
