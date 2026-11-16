"""Extending a declaration must extend loading, links, redaction and grants."""

import io
import json
import unittest
from contextlib import redirect_stderr
from dataclasses import replace
from datetime import date
from unittest.mock import patch

from development_mcp.grants import grant_sql
from development_mcp.schema import CaseFilter, Load, PROGRAMS, TABLES, Table, registry_version, validate_registry
from development_mcp.service import Service
from .helpers import MemoryDatabase, MemoryReader, NoNER, fixture


class RegistryTests(unittest.TestCase):
    def test_one_declaration_connects_loading_cleaning_links_and_grants(self):
        review = Table(output=('comment',), identities=(('reviewer_name', 'person'),), age_field='birth_date',
                       filters=(CaseFilter('demo_comment_present', 'text', 'comment'),),
                       loads=(Load('core_motivationletter', 'letter_id', programs=('main',)),
                              Load('demo_followup', 'id', source_column='review_id', programs=('main',))))
        followup = Table(output=('comment',), loads=(Load('demo_casereview', 'review_id', programs=('main',)),))
        # Deliberately put descendants before parents; include a cycle back to review.
        registry = {'demo_followup': followup, 'demo_casereview': review, **TABLES}
        data = fixture()
        data['demo_casereview'] = [
            {'id': 901, 'letter_id': 401, 'comment': 'Мария Петрова: ivan@example.org, родился 2010-01-02',
             'reviewer_name': 'Мария Петрова', 'birth_date': date(2010, 1, 2), 'future_secret': 'HIDDEN_EXTRA_FIELD'},
            {'id': 902, 'letter_id': 999, 'comment': 'UNRELATED_PARTICIPANT'},
        ]
        data['demo_followup'] = [{'id': 903, 'review_id': 901, 'comment': 'Проверено'}]
        original_version = registry_version()
        with patch.dict(TABLES, registry, clear=True):
            validate_registry()
            self.assertNotEqual(registry_version(), original_version)
            reader = MemoryReader(data)
            records = reader.load_case('main', 201)
            keys = [(table, row['id']) for table, row in records]
            self.assertEqual(keys.count(('demo_casereview', 901)), 1)
            self.assertEqual(keys.count(('demo_followup', 903)), 1)
            self.assertNotIn(('demo_casereview', 902), keys)
            other = MemoryReader(data).load_case('nto', 601)
            self.assertFalse(any(table.startswith('demo_') for table, _ in other))
            service = Service(MemoryDatabase(data), NoNER(), 'registry-test-secret-123456789012345')
            with redirect_stderr(io.StringIO()):
                described = service.call('describe_dataset')
                result = service.call('get_case', case_id=service.opaque_id('main', 201))
                items = list(result['items'])
                while result['next_cursor']:
                    result = service.call('get_case', case_id=result['case_id'], cursor=result['next_cursor'])
                    items += result['items']
            self.assertIn('demo_casereview', described['sections'])
            self.assertIn('demo_comment_present', described['programs']['main']['filters'])
            with redirect_stderr(io.StringIO()):
                filtered = service.call('list_cases', program='main', filters={'demo_comment_present': True})
            self.assertEqual(len(filtered['cases']), 1)
            self.assertEqual(described['registry_version'], registry_version())
            review_item = next(i for i in items if i['section'] == 'demo_casereview' and i['field'] == 'comment')
            self.assertEqual(review_item['links']['letter'], service.opaque_id('core_motivationletter', 401))
            self.assertIn('[Человек 1]', review_item['value'])
            self.assertNotIn('2010', review_item['value'])
            values = json.dumps([i['value'] for i in items], ensure_ascii=False)
            for secret in ('Мария', 'Петрова', 'ivan@example.org', 'HIDDEN_EXTRA_FIELD', 'UNRELATED_PARTICIPANT'):
                self.assertNotIn(secret, values)
            grants = grant_sql(update=True)
            self.assertIn('ON TABLE public."demo_casereview"', grants)
            self.assertIn('"letter_id"', grants)
            self.assertNotIn('HIDDEN_EXTRA_FIELD', grants)

    def test_incomplete_and_unsafe_declarations_are_rejected(self):
        cases = [
            Table(output=('comment',), loads=(Load('missing_table', 'user_id'),)),
            Table(output=('password',), loads=(Load('auth_user', 'user_id'),)),
            Table(output=('user_id',), loads=(Load('auth_user', 'user_id'),)),
            Table(output=('comment',), loads=(Load('auth_user', 'user_id', source_column='missing_column'),)),
            Table(output=('comment',), loads=(Load('auth_user', 'user_id', programs=('missing_direction',)),)),
            Table(output=('comment',)),  # unreachable
            Table(output=('comment',), identities=(('comment', 'person'),), loads=(Load('auth_user', 'user_id'),)),
            Table(output=('comment',), internal=('private_text',), loads=(Load('auth_user', 'user_id'),),
                  filters=(CaseFilter('private_filter', 'text', 'private_text'),)),
            Table(output=('comment',), loads=(Load('auth_user', 'user_id'),),
                  filters=(CaseFilter('staff_note_count', 'count'),)),
            Table(output=('comment',), loads=(Load('auth_user', 'user_id', programs=('main',)),),
                  filters=(CaseFilter('not_reachable', 'text', 'comment', programs=('nto',)),)),
        ]
        for declaration in cases:
            with self.subTest(declaration=declaration), self.assertRaises(ValueError):
                validate_registry({**TABLES, 'demo_invalid': declaration}, PROGRAMS)

    def test_existing_field_extension_requires_no_loader_change(self):
        extended = replace(TABLES['core_motivationletter'], output=TABLES['core_motivationletter'].output + ('new_comment',))
        data = fixture()
        data['core_motivationletter'][0]['new_comment'] = 'Новый комментарий'
        with patch.dict(TABLES, {'core_motivationletter': extended}):
            validate_registry()
            self.assertIn('"new_comment"', grant_sql(update=True))
            loaded = MemoryReader(data).load_case('main', 201)
            letter = next(row for table, row in loaded if table == 'core_motivationletter')
            self.assertEqual(letter['new_comment'], 'Новый комментарий')
