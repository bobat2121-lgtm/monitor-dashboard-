import copy
import json
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from test_universe import DATA, SOURCE, by_label


class SourceEditorConfigTests(unittest.TestCase):
    def test_json_url_directory_survives_preview_save_and_pause(self):
        for prefix in ['/media-center/announcements/', '/en-US/newsroom/', '']:
            data = copy.deepcopy(DATA)
            data['registry']['sources'] = [{**SOURCE, 'key': 'managed_json', 'protected_roster_entry': False,
                'companyStatus': 'private', 'adapter': 'json', 'source_role': 'issuer_release_distribution',
                'config': {'json_url_field': 'slug', 'json_url_prefix': prefix}}]
            code = '''
import json
import streamlit as st
import universe_view as uv
from unittest.mock import patch
data = json.loads(DATA_LITERAL)
def capture_api(base, pin, path='', payload=None):
    st.session_state['payload'] = payload
    raise ValueError('Captured locally')
def capture_save(base, pin, data, operation, preview_id=None):
    st.session_state['payload'] = operation['value']
with patch.object(uv, 'api', capture_api), patch.object(uv, 'save_change', capture_save):
    uv.source_editor('https://example.com', 'test-pin', data, data['registry']['sources'][0])
'''.replace('DATA_LITERAL', repr(json.dumps(data)))
            with patch('requests.get', side_effect=AssertionError('No network')), patch('requests.post', side_effect=AssertionError('No network')):
                for action in ['Preview releases', 'Save source', 'Pause']:
                    app = AppTest.from_string(code).run()
                    self.assertEqual(list(app.exception), [])
                    if action == 'Pause':
                        by_label(app.selectbox, 'Collection').set_value('paused')
                    by_label(app.button, 'Save source' if action == 'Pause' else action).click().run()
                    self.assertEqual(list(app.exception), [])
                    self.assertEqual(app.session_state['payload']['json_url_prefix'], prefix)
                    if action != 'Preview releases':
                        self.assertEqual(app.session_state['payload']['source_role'], 'issuer_release_distribution')


if __name__ == '__main__':
    unittest.main()
