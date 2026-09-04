import unittest
from datetime import datetime, timezone

from dashboard_utils import MIN_TIME, parse_time, pipeline_status, rejected_time, sort_rejected


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


class ParseTimeTests(unittest.TestCase):
    def test_parses_rss_and_iso_timestamps(self):
        self.assertEqual(
            parse_time("Thu, 03 Sep 2026 19:42:48 +0000"),
            datetime(2026, 9, 3, 19, 42, 48, tzinfo=timezone.utc),
        )
        self.assertEqual(
            parse_time("Thu, 03 Sep 26 15:31:37 EDT"),
            datetime(2026, 9, 3, 19, 31, 37, tzinfo=timezone.utc),
        )
        self.assertEqual(
            parse_time("2026-09-03T20:30:26.388Z"),
            datetime(2026, 9, 3, 20, 30, 26, 388000, tzinfo=timezone.utc),
        )

    def test_rejected_time_falls_back_when_source_time_is_invalid(self):
        item = {"ts": "not-a-time", "created_at": "2026-09-03T20:30:26Z"}
        self.assertEqual(rejected_time(item), parse_time(item["created_at"]))

    def test_rejected_sort_uses_parsed_source_time(self):
        items = [
            {"id": 1, "ts": "Thu, 03 Sep 2026 19:42:48 +0000"},
            {"id": 2, "ts": "2026-09-03T20:30:00Z"},
            {"id": 3, "ts": "bad", "created_at": "2026-09-03T21:00:00Z"},
        ]
        self.assertEqual([item["id"] for item in sort_rejected(items)], [3, 2, 1])

    def test_invalid_time_is_explicit_sentinel(self):
        self.assertEqual(parse_time(None), MIN_TIME)


class PipelineStatusTests(unittest.TestCase):
    def test_quiet_review_is_green(self):
        health = {
            "ok": True,
            "status": "healthy",
            "unread": 4,
            "staleness": {
                "lastReview": "2026-09-04T10:00:00Z",
                "lastOutcome": "reviewed_no_publish",
                "lastItemCount": 0,
            },
        }
        status = pipeline_status(health, now=NOW)
        self.assertEqual(status.level, "green")
        self.assertIn("nothing new to publish", status.text)

    def test_backend_degraded_status_cannot_appear_green(self):
        health = {
            "ok": True,
            "status": "degraded",
            "unread": 4,
            "staleness": {
                "lastReview": "2026-09-04T10:00:00Z",
                "lastOutcome": "published",
                "lastItemCount": 3,
            },
        }
        status = pipeline_status(health, now=NOW)
        self.assertEqual(status.level, "amber")
        self.assertIn("degraded", status.text)

    def test_backend_degraded_status_does_not_hide_stale_review(self):
        health = {
            "ok": True,
            "status": "degraded",
            "staleness": {
                "lastReview": "2026-09-02T00:00:00Z",
                "lastOutcome": "published",
                "lastItemCount": 3,
            },
        }
        self.assertEqual(pipeline_status(health, now=NOW).level, "red")

    def test_delayed_and_stale_reviews_are_not_green(self):
        delayed = {"ok": True, "staleness": {"lastReview": "2026-09-03T16:00:00Z"}}
        stale = {"ok": True, "staleness": {"lastReview": "2026-09-02T00:00:00Z"}}
        self.assertEqual(pipeline_status(delayed, now=NOW).level, "amber")
        self.assertEqual(pipeline_status(stale, now=NOW).level, "red")

    def test_health_endpoint_fallback_never_claims_green(self):
        latest = {"posted_at": "2026-09-04T10:00:00Z"}
        status = pipeline_status(None, latest, now=NOW)
        self.assertEqual(status.level, "amber")
        self.assertIn("Health check unavailable", status.text)

    def test_reachable_legacy_health_uses_amber_fallback(self):
        health = {
            "ok": True,
            "staleness": {"lastPost": "2026-09-04T10:00:00Z"},
        }
        self.assertEqual(pipeline_status(health, now=NOW).level, "amber")


if __name__ == "__main__":
    unittest.main()
