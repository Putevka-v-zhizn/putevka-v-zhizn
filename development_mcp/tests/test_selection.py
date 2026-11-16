import io
import json
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from development_mcp.schema import case_filters
from development_mcp.service import Service, safe_features
from development_mcp.redaction import RedactionError
from .helpers import MemoryDatabase, NoNER, fixture


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture()
        self.data['scholar_form_userinfo'][0]['selection_step'] = 'ml'
        self.data['core_motivationletter'][0]['status'] = 'revision'
        for user, root in [(102, 202), (103, 203)]:
            self.data['auth_user'].append({'id': user})
            self.data['scholar_form_userinfo'].append({'id': root, 'user_id': user, 'form_status': 'submitted'})
        self.data['core_motivationletter'].append({'id': 411, 'user_id': 102, 'status': 'revision', 'letter_text': ' \n\t', 'admin_score': None})
        self.data['review_by_tutor_interview'].append({'id': 511, 'user_id': 102, 'transcript': ' \n\t'})
        self.data['review_by_tutor_testassignment'] = [{'id': 801, 'user_id': 101}, {'id': 802, 'user_id': 101}, {'id': 803, 'user_id': 102}, {'id': 804, 'user_id': 999}]
        self.service = Service(MemoryDatabase(self.data), NoNER(), 'selection-test-secret-123456789012345')

    def call(self, **kwargs):
        with redirect_stderr(io.StringIO()):
            return self.service.call('list_cases', **kwargs)

    def test_combines_filters_and_returns_only_safe_features(self):
        filters = {'has_interview_transcript': True, 'letter_status': 'revision', 'motivation_score': {'min': 3, 'max': 5},
                   'test_count': {'min': 2}, 'selection_step': 'ml'}
        result = self.call(program='main', status='submitted', filters=filters)
        self.assertEqual([c['case_id'] for c in result['cases']], [self.service.opaque_id('main', 201)])
        features = result['cases'][0]['features']
        self.assertTrue(features['has_interview_transcript'])
        self.assertEqual(features['letter_status'], ['revision'])
        self.assertEqual(features['test_count'], 2)
        for value in ('Иван', 'ivan@example.org', 'Здравствуйте', 'Томск'):
            self.assertNotIn(value, json.dumps(result, ensure_ascii=False))
        self.assertEqual(result['applied_filters'], filters)

    def test_missing_relations_and_whitespace_are_absent(self):
        for name in ('has_interview_transcript', 'has_motivation_letter'):
            result = self.call(program='main', filters={name: False})
            self.assertEqual({c['case_id'] for c in result['cases']}, {self.service.opaque_id('main', pk) for pk in (202, 203)})
        result = self.call(program='main', filters={'test_count': {'min': 0, 'max': 0}})
        self.assertEqual([c['case_id'] for c in result['cases']], [self.service.opaque_id('main', 203)])
        self.assertEqual(self.call(program='main', filters={'motivation_score': {'max': 5}})['cases'][0]['features']['motivation_score'], 4)

    def test_filters_are_direction_specific_and_discoverable(self):
        with redirect_stderr(io.StringIO()):
            described = self.service.call('describe_dataset')
        self.assertIn('has_interview_transcript', described['programs']['main']['filters'])
        self.assertNotIn('letter_status', described['programs']['nto']['filters'])
        self.assertIn('income_source_count', described['programs']['family_income']['filters'])
        result = self.call(program='family_income', filters={'income_source_count': {'min': 1}, 'family_size': {'min': 3, 'max': 3}})
        self.assertEqual(len(result['cases']), 1)
        result = self.call(program='nto', filters={'has_situation_details': True, 'criticality': {'min': 4}})
        self.assertEqual(len(result['cases']), 1)

    def test_cursor_is_bound_to_filters_and_registry(self):
        filters = {'has_motivation_letter': False, 'test_count': {'max': 1, 'min': 0}}
        first = self.call(program='main', filters=filters, limit=1)
        self.assertIsNotNone(first['next_cursor'])
        reordered = {'test_count': {'min': 0, 'max': 1}, 'has_motivation_letter': False}
        second = self.call(program='main', filters=reordered, limit=1, cursor=first['next_cursor'])
        self.assertIsNone(second['next_cursor'])
        self.assertNotEqual(first['cases'][0]['case_id'], second['cases'][0]['case_id'])
        changed = self.call(program='main', filters={'has_motivation_letter': True}, cursor=first['next_cursor'])
        self.assertEqual(changed['error']['code'], 'invalid_request')
        with patch('development_mcp.service.registry_version', return_value='new-version'):
            stale = self.call(program='main', filters=filters, cursor=first['next_cursor'])
        self.assertEqual(stale['error']['code'], 'invalid_request')

    def test_rejects_unknown_filters_bad_types_ranges_and_sql(self):
        invalid = [
            {'phone': '123'}, {'has_motivation_letter': 'true'}, {'letter_status': "revision' OR TRUE--"},
            {'motivation_score': {}}, {'motivation_score': {'min': 5, 'max': 2}},
            {'motivation_score': {'min': True}}, {'motivation_score': {'min': float('nan')}},
            {'motivation_score': {'min': float('inf')}}, {'motivation_score': {'min': 10**1000}},
            {'test_count': {'min': -1}}, {'test_count': {'min': 1.5}},
            {'test_count': {'sql': 'SELECT * FROM auth_user'}}, [],
        ]
        for filters in invalid:
            with self.subTest(filters=str(filters)[:120]):
                result = self.call(program='main', filters=filters)
                self.assertEqual(result['error']['code'], 'invalid_request')
        self.assertEqual(self.call(program='nto', filters={'letter_status': 'revision'})['error']['code'], 'invalid_request')

    def test_summary_types_fail_closed_on_database_drift(self):
        with self.service.database.read() as reader:
            row = reader.list_roots('main', None, 0, 1)[0]
        row['feature_motivation_score'] = 'PRIVATE_SOURCE_TEXT'
        with self.assertRaises(RedactionError):
            safe_features('main', row)
        row['feature_motivation_score'] = 4
        row['feature_letter_status'] = ['PRIVATE_SOURCE_TEXT']
        with self.assertRaises(RedactionError):
            safe_features('main', row)
