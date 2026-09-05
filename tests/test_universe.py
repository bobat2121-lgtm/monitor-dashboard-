import unittest
import copy
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from streamlit.testing.v1 import AppTest
from test_streamlit_smoke import APP_PATH, StubResponse, fake_get
from universe_view import source_status, config_hash

ENTITY = {'id': 'example', 'name': 'Example', 'aliases': [], 'coverage_role': 'adjacent_comparable', 'memberships': [{'industry_id': 'defense', 'subindustry_ids': ['uas']}], 'source_ids': []}
SOURCE = {'key': 'original', 'name': 'Original newsroom', 'endpoint': 'https://example.com/feed', 'adapter': 'rss', 'config': {}, 'entity_ids': ['example'], 'configuration_status': 'configured', 'source_role': 'company_newsroom', 'cadence_minutes': 60, 'protected_roster_entry': True}
DATA = {'ok': True, 'revision_id': 'r1', 'collection_state': 'applied', 'ranking_published': True, 'collector': None, 'source_health': {}, 'registry': {'industries': [{'id': 'defense', 'name': 'Defense tech', 'subindustries': [{'id': 'uas', 'name': 'UAS'}]}], 'entities': [ENTITY], 'sources': [SOURCE], 'relationships': []}}
def get(url, **kwargs):
    if url.endswith('/universe/history'):
        return StubResponse({'ok': True, 'revisions': [{'id':'r1','label':'Initial','created_at':'2026-09-05T00:00:00Z','collection_state':'applied'}]})
    if url.endswith('/universe'):
        assert kwargs['headers']['X-Owner-Pin'] == 'test-pin'
        return StubResponse(DATA)
    return fake_get(url, **kwargs)

def by_label(elements, label):
    return next(e for e in elements if e.label == label)

class UniverseTests(unittest.TestCase):
    def test_relationship_and_government_edits_use_versioned_owner_operations(self):
        data=copy.deepcopy(DATA)
        data['matching_revision']='r1'
        data['registry']['knowledge_nodes']=[{'id':'payload','kind':'product','name':'Example Payload','aliases':['Payload One'],'entity_ids':['example'],'industry_ids':['defense'],'match_mode':'direct','evidence_note':'Company release'}]
        data['registry']['external_sources']=[{'id':'oira','name':'OIRA','worker':'reg-watcher','endpoint':'https://www.reginfo.gov/','configuration_status':'configured','industry_ids':['defense'],'knowledge_ids':[],'include_terms':[],'exclude_terms':[],'matching_enabled':True}]
        posted=[]
        def fetch(url, **kwargs):
            return StubResponse(data) if url.endswith('/universe') else get(url, **kwargs)
        def post(url, **kwargs):
            posted.append(kwargs['json'])
            return StubResponse({'ok':True,'revision_id':'r2'})
        with patch('requests.get', side_effect=fetch), patch('requests.post', side_effect=post):
            app=AppTest.from_file(str(APP_PATH), default_timeout=30)
            app.session_state['grader_pin']='test-pin'
            app.run()
            by_label(app.radio,'Dashboard view').set_value('Universe');app.run()
            by_label(app.radio,'Universe view').set_value('Relationships');app.run()
            by_label(app.selectbox,'Edit or add a relationship').set_value('payload');app.run()
            by_label(app.text_area,'Matchable names (one per line)').set_value('Payload One\nPayload Two')
            by_label(app.button,'Save relationship').click();app.run()
            self.assertEqual(list(app.exception),[])
            self.assertEqual(posted[-1]['operation']['kind'],'knowledge_upsert')
            self.assertEqual(posted[-1]['operation']['value']['aliases'],['Payload One','Payload Two'])
            by_label(app.radio,'Universe view').set_value('Government');app.run()
            by_label(app.text_area,'Additional relevance phrases (one per line)').set_value('Novel program')
            by_label(app.button,'Save government routing').click();app.run()
            self.assertEqual(list(app.exception),[])
            self.assertEqual(posted[-1]['operation']['kind'],'government_source_update')
            self.assertEqual(posted[-1]['operation']['value']['include_terms'],['Novel program'])

    def test_owner_map_source_preview_save_and_history(self):
        posted=[]
        def post(url, **kwargs):
            posted.append((url, kwargs['json']))
            if url.endswith('/preview'):
                return StubResponse({'ok': True, 'preview_id':'proof', 'total_found':1, 'items':[{'title':'New deployment','url':'https://example.com/news/new'}], 'source':{'endpoint':'https://example.com/feed','adapter':'rss','config':{}}})
            return StubResponse({'ok':True,'revision_id':'r2'})
        with patch('requests.get', side_effect=get), patch('requests.post', side_effect=post):
            app=AppTest.from_file(str(APP_PATH), default_timeout=30)
            app.session_state['grader_pin']='test-pin'
            app.run()
            by_label(app.radio,'Dashboard view').set_value('Universe');app.run()
            self.assertEqual(list(app.exception),[])
            by_label(app.radio,'Universe view').set_value('Sources');app.run()
            self.assertEqual(list(app.exception),[])
            by_label(app.multiselect,'Linked companies').set_value(['example'])
            by_label(app.text_input,'Source name').set_value('New newsroom')
            by_label(app.text_input,'Newsroom or feed URL').set_value('https://example.com/feed')
            by_label(app.text_input,'Article card selector').set_value('.press-item')
            by_label(app.text_input,'Headline selector').set_value('h3')
            by_label(app.text_input,'Category selector').set_value('.type')
            by_label(app.text_area,'Allowed release categories (optional, one per line)').set_value('Press Release')
            by_label(app.selectbox,'Collection').set_value('configured')
            by_label(app.button,'Preview releases').click();app.run()
            self.assertEqual(list(app.exception),[])
            by_label(app.button,'Save source').click();app.run()
            self.assertEqual(list(app.exception),[])
            self.assertEqual(posted[-1][1]['preview_id'],'proof')
            self.assertEqual(posted[-1][1]['operation']['value']['configuration_status'],'configured')
            self.assertEqual(posted[-1][1]['operation']['value']['item_selector'],'.press-item')
            self.assertEqual(posted[-1][1]['operation']['value']['include_categories'],['Press Release'])
            by_label(app.selectbox,'Edit or add a source').set_value('original');app.run()
            self.assertTrue(by_label(app.text_input,'Newsroom or feed URL').disabled)
            by_label(app.radio,'Universe view').set_value('History');app.run()
            self.assertEqual(list(app.exception),[])
    def test_stale_source_is_not_green(self):
        source={**SOURCE,'managed_by':'universe'}
        health={'config_hash':config_hash(source),'last_ok':(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()}
        self.assertEqual(source_status(source,{**DATA,'source_health':{'original':health}}),'Overdue')
    def test_no_pin_does_not_request_registry(self):
        with patch('requests.get',side_effect=fake_get):
            app=AppTest.from_file(str(APP_PATH),default_timeout=30).run()
            by_label(app.radio,'Dashboard view').set_value('Universe');app.run()
            self.assertEqual(list(app.exception),[])
            self.assertTrue(any('Grader PIN' in e.value for e in app.info))
