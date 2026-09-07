import copy
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from test_streamlit_smoke import APP_PATH, StubResponse
from test_universe import DATA, get, by_label
from universe_view import source_evidence_rows


class CollectionEvidenceTests(unittest.TestCase):
    def test_rows_keep_unknown_counts_and_bound_samples(self):
        report = {"checks": [{"checked_at": "2026-09-07T10:00:00Z", "status": "success", "completeness": {"response_complete": False}}] * 15,
                  "observations": [{"decision": "excluded", "reason": "outside_source_scope", "evidence": {"excerpt": "Body-only material context"}}] * 25,
                  "pending": [{"attempts": 2}] * 25}
        checks, observations, pending = source_evidence_rows(report)
        self.assertEqual((len(checks), len(observations), len(pending)), (10, 20, 20))
        self.assertIsNone(checks[0]["Accepted"])
        self.assertEqual(observations[0]["Captured evidence"], "Body-only material context")

    def test_owner_inspection_is_read_only_and_shows_incomplete_evidence(self):
        data = copy.deepcopy(DATA)
        source = data["registry"]["sources"][0]
        source.update(key="managed_test", managed_by="universe", protected_roster_entry=False, companyStatus="private", cadence_minutes=120)
        report = {"ok": True, "available": True, "history_complete": False, "counts": {"observations": 25, "excluded": 20, "same_url_revisions": 1},
                  "retained_since": "2026-09-07T10:00:00Z", "checks": [{"checked_at": "2026-09-07T10:00:00Z", "status": "success",
                      "counts": {"accepted": 3, "excluded": 20, "body_pending": 2}, "completeness": {"response_complete": False, "cap_reasons": ["item_limit"]}}],
                  "observations": [{"observed_at": "2026-09-07T10:00:00Z", "decision": "excluded", "reason": "outside_source_scope", "url": "https://issuer.example/release",
                      "evidence": {"title": "Issuer operating update", "excerpt": "Captured evidence from the official release"}}],
                  "pending": [], "truncated": {"observations": True}}
        reads = []
        def fetch(url, **kwargs):
            reads.append(url)
            if '/source-evidence?' in url:
                self.assertEqual(kwargs['headers']['X-Owner-Pin'], 'test-pin')
                return StubResponse(report)
            return StubResponse(data) if url.endswith('/universe') else get(url, **kwargs)
        with patch('requests.get', side_effect=fetch), patch('requests.post', side_effect=AssertionError('inspection must not write')):
            app = AppTest.from_file(str(APP_PATH), default_timeout=30)
            app.session_state['grader_pin'] = 'test-pin'
            app.run()
            by_label(app.radio, 'Dashboard view').set_value('Universe'); app.run()
            by_label(app.radio, 'Universe view').set_value('Sources'); app.run()
            by_label(app.selectbox, 'Edit or add a source').set_value('managed_test'); app.run()
            self.assertFalse(any('/source-evidence?' in url for url in reads))
            by_label(app.button, 'Load collection evidence').click(); app.run()
            self.assertEqual(list(app.exception), [])
            self.assertTrue(any('/source-evidence?key=managed_test' in url for url in reads))
            self.assertTrue(any('entire historical archive' in item.value for item in app.caption))
            self.assertTrue(any('additional evidence is retained' in item.value for item in app.caption))


if __name__ == '__main__':
    unittest.main()
