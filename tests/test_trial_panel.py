import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"


class StubResponse:
    text = ""
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


MAIN_ITEM = {"rank": 1, "event_id": 11, "headline": "Main story of the edition", "text": "The main item.",
             "url": "https://example.com/main", "worker": "news-monitor", "value": "medium"}
# The /digests shape (contract P3.4): sorted by rank, no score or research
# fields, and the Worker-stamped trial_origin.
TRIAL_ITEMS = [
    {"rank": 2, "event_id": 9002, "headline": "Missed drone order", "text": "A story the collection missed.",
     "url": "https://wire.example/two", "worker": "scout", "value": "low",
     "trial_origin": {"kind": "scout_missed", "first_published_by": "reuters.com", "found_at": "2026-09-30T12:00:00Z"}},
    {"rank": 1, "event_id": 9001, "headline": "Beta ships the X9", "text": "Beta Corp shipped its X9 to a second customer.",
     "url": "https://beta.example/news/x9", "worker": "news-monitor", "value": "high",
     "trial_origin": {"kind": "trial_source", "source_key": "managed_beta", "source_name": "Beta Corp newsroom", "day": 4, "of_days": 21}},
]
# Strings a hostile page could steer: a blank line would end the raw HTML
# block and let Markdown render a remote image.
IMAGE = "\n\n![x](https://attacker.example/p.png)"


def post(**fields):
    return {"id": 1, "posted_at": "2026-09-30T16:00:00Z", "trigger_label": "12pm ET", "headline": "Edition headline",
            "reviewed": 20, "items": [MAIN_ITEM], **fields}


class TrialPanelTests(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        self.daily = [post(trial_items=copy.deepcopy(TRIAL_ITEMS))]
        get_patch = patch("requests.get", side_effect=self.fake_get)
        get_patch.start()
        self.addCleanup(get_patch.stop)

    def fake_get(self, url, **_kwargs):
        if url.endswith("/digests"):
            return StubResponse({"daily": self.daily, "weekly": []})
        raise AssertionError(f"unexpected dashboard request: {url}")

    def render(self, search=""):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30)
        app.session_state["feed_search"] = search
        app.run(timeout=30)
        self.assertEqual(list(app.exception), [])
        # The stylesheet is Markdown too; only the feed's own blocks count.
        self.blocks = [m.value for m in app.markdown if not m.value.startswith("<style>")]
        return "\n".join(self.blocks)

    def test_trial_items_render_collapsed_after_the_main_items(self):
        rendered = self.render()
        self.assertIn('<details class="trial-panel"><summary class="trial-panel-toggle">Trial · 2</summary>', rendered)
        panel = rendered.index('<details class="trial-panel">')
        self.assertLess(rendered.index("Main story of the edition"), panel, "after the main items")
        self.assertLess(panel, rendered.index("</section>"), "inside the edition's own section")
        self.assertEqual(rendered.count('<details class="trial-panel">'), 1)
        # T{rank} markers in rank order, each with its origin chip, value badge and link.
        self.assertLess(rendered.index('<div class="rank-marker">T1</div>'), rendered.index('<div class="rank-marker">T2</div>'))
        self.assertIn('<span class="feed-worker">beta.example</span>'
                      '<span class="trial-origin">Trial source · Beta Corp newsroom · day 4/21</span>', rendered)
        self.assertIn('<span class="trial-origin">Missed by collection · first seen at reuters.com</span>', rendered)
        self.assertIn('<span class="value-badge level-high">High</span><a class="source-link" href="https://beta.example/news/x9" '
                      'target="_blank" rel="noopener noreferrer">Open source ↗</a>', rendered)
        self.assertIn('<span class="value-badge level-low">Low</span>', rendered)
        self.assertIn('<div class="feed-item-headline">Beta ships the X9</div>', rendered)
        # The main item keeps its two-digit marker; trial items count nowhere else.
        self.assertIn('<div class="rank-marker">01</div>', rendered)
        self.assertIn("<span>1 item</span>", rendered)
        self.assertIn('<div class="stat"><div class="stat-n">1</div><div class="stat-l">ITEMS</div></div>', rendered)

    def test_no_panel_when_trial_items_are_absent_empty_or_not_a_list(self):
        for trial_items in ("absent", [], None, {"rank": 1, "headline": "x"}, "T1", [1, "x", None]):
            with self.subTest(trial_items=trial_items):
                self.daily = [post() if trial_items == "absent" else post(trial_items=trial_items)]
                rendered = self.render()
                self.assertIn("Main story of the edition", rendered)
                self.assertNotIn('class="trial-panel"', rendered)
                self.assertNotIn("rank-marker\">T", rendered)

    def test_every_string_is_escaped_and_kept_on_one_line(self):
        self.daily = [post(trial_items=[
            "not an item",
            {"rank": "1", "event_id": 9001, "headline": "<script>alert(1)</script>" + IMAGE, "text": "Line one" + IMAGE,
             "url": 'https://beta.example/x"onmouseover="alert(1)', "worker": "news-monitor", "value": "medium",
             "trial_origin": {"kind": "trial_source", "source_name": "<b>Beta</b>" + IMAGE, "day": "5", "of_days": 21.0}},
            {"rank": 2, "event_id": 9002, "headline": "No day yet", "url": "javascript:alert(1)", "worker": "news-monitor",
             "trial_origin": {"kind": "trial_source", "source_key": "managed_gamma", "day": None, "of_days": None}},
            {"rank": 3, "event_id": 9003, "headline": "Scout story", "url": "https://www.wire.example/story", "worker": "scout",
             "trial_origin": {"kind": "scout_missed", "first_published_by": "<i>host</i>" + IMAGE}},
            {"rank": 4, "event_id": 9004, "headline": "Scout story without a host", "url": "https://www.wire.example/other", "worker": "scout",
             "trial_origin": {"kind": "scout_missed", "first_published_by": None}},
            {"rank": 5, "event_id": 9005, "headline": "Unknown origin", "url": "https://example.com/5", "trial_origin": "trial"},
        ])]
        rendered = self.render()
        self.assertIn('<summary class="trial-panel-toggle">Trial · 5</summary>', rendered, "the string entry is skipped")
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<b>Beta", rendered)
        self.assertNotIn("<i>host", rendered)
        self.assertIn('<div class="feed-item-headline">&lt;script&gt;alert(1)&lt;/script&gt; ![x](https://attacker.example/p.png)</div>', rendered)
        self.assertIn('<div class="feed-text">Line one ![x](https://attacker.example/p.png)</div>', rendered)
        self.assertIn('href="https://beta.example/x&quot;onmouseover=&quot;alert(1)"', rendered)
        # Numbers are coerced to ints; a null day leaves the day part out.
        self.assertIn('<span class="trial-origin">Trial source · &lt;b&gt;Beta&lt;/b&gt; ![x](https://attacker.example/p.png) · day 5/21</span>', rendered)
        self.assertIn('<span class="trial-origin">Trial source · managed_gamma</span>', rendered)
        self.assertIn('<span class="trial-origin">Missed by collection · first seen at &lt;i&gt;host&lt;/i&gt; ![x](https://attacker.example/p.png)</span>', rendered)
        self.assertIn('<span class="trial-origin">Missed by collection · first seen at wire.example</span>', rendered, "falls back to the link's domain")
        self.assertEqual(rendered.count('class="trial-origin"'), 4, "no chip for an unknown origin")
        # A link that is not http(s) is never an href.
        self.assertNotIn("javascript:", rendered)
        self.assertIn('<div class="rank-marker">T2</div>', rendered)
        hostile = [block for block in self.blocks if "attacker.example" in block]
        self.assertEqual(len(hostile), 1, "the feed is one HTML block")
        self.assertNotIn("\n", hostile[0], "nothing in the block spans lines")

    def test_search_leaves_out_the_trial_panel(self):
        rendered = self.render(search="main story")
        self.assertIn("1 search result", rendered)
        self.assertIn("Main story of the edition", rendered)
        self.assertNotIn('class="trial-panel"', rendered)
        self.assertNotIn("Beta ships the X9", rendered)


if __name__ == "__main__":
    unittest.main()
