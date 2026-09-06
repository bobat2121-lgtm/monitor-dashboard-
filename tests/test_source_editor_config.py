import copy
import json
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from test_universe import DATA, SOURCE, by_label


class SourceEditorConfigTests(unittest.TestCase):
    def test_all_supported_fields_survive_rss_html_and_json_preview_save_and_pause(self):
        config = {
            'path_prefix': '/releases/', 'item_selector': '.release', 'title_selector': 'h2',
            'link_selector': 'a', 'category_selector': '.category', 'date_selector': 'time', 'allow_pdf': True,
            'json_script_id': 'news_data', 'json_items_path': 'data.items', 'json_title_field': 'headline',
            'json_url_field': 'slug', 'json_url_prefix': '/releases/', 'json_date_field': 'published',
            'json_category_field': 'category', 'json_external_field': 'external', 'json_excerpt_field': 'summary',
            'include_terms': ['robotics', 'autonomy'], 'exclude_paths': ['/media/'], 'include_categories': ['Press Release'],
        }
        for adapter in ['rss', 'html', 'json']:
            data = copy.deepcopy(DATA)
            data['registry']['sources'] = [{**SOURCE, 'key': 'managed_fixture', 'protected_roster_entry': False,
                'companyStatus': 'private', 'adapter': adapter, 'config': config}]
            code = '''
import json
import streamlit as st
import universe_view as uv
from unittest.mock import patch
data = json.loads(DATA_LITERAL)
def capture_api(base, pin, path='', payload=None):
    st.session_state['payload'] = payload
    config = {key: value for key, value in payload.items() if key not in ['endpoint', 'adapter']}
    return {'ok': True, 'preview_id': 'exact-proof', 'total_found': 1,
            'items': [{'title': 'Company release', 'url': 'https://example.com/releases/one'}],
            'source': {'endpoint': payload['endpoint'], 'adapter': payload['adapter'], 'config': config}}
def capture_save(base, pin, data, operation, preview_id=None):
    st.session_state['payload'] = operation['value']
    st.session_state['saved_proof'] = preview_id
with patch.object(uv, 'api', capture_api), patch.object(uv, 'save_change', capture_save):
    uv.source_editor('https://example.com', 'test-pin', data, data['registry']['sources'][0])
'''.replace('DATA_LITERAL', repr(json.dumps(data)))
            with patch('requests.get', side_effect=AssertionError('No network')), patch('requests.post', side_effect=AssertionError('No network')):
                app = AppTest.from_string(code).run()
                by_label(app.button, 'Preview releases').click().run()
                self.assertEqual(list(app.exception), [])
                for field, expected in config.items():
                    self.assertEqual(app.session_state['payload'][field], expected, f'{adapter} preview {field}')
                by_label(app.button, 'Save source').click().run()
                self.assertEqual(app.session_state['saved_proof'], 'exact-proof')
                for field, expected in config.items():
                    self.assertEqual(app.session_state['payload'][field], expected, f'{adapter} save {field}')
                by_label(app.selectbox, 'Collection').set_value('paused')
                by_label(app.button, 'Save source').click().run()
                self.assertEqual(list(app.exception), [])
                self.assertEqual(app.session_state['payload']['configuration_status'], 'paused')
                for field, expected in config.items():
                    self.assertEqual(app.session_state['payload'][field], expected, f'{adapter} pause {field}')
                # Changing extraction after preview must drop the proof handed
                # to the backend; it will require a fresh matching preview.
                by_label(app.text_input, 'Article URL directory (optional)').set_value('/updates/')
                by_label(app.selectbox, 'Collection').set_value('configured')
                by_label(app.button, 'Save source').click().run()
                self.assertEqual(list(app.exception), [])
                self.assertIsNone(app.session_state['saved_proof'])
                self.assertEqual(app.session_state['payload']['json_url_prefix'], '/updates/')
                self.assertEqual(app.session_state['payload']['include_terms'], config['include_terms'])

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
