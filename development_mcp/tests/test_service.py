import ast
import io
import json
from contextlib import redirect_stderr
from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch

from development_mcp import RULES_VERSION
from development_mcp.schema import TABLES
from development_mcp.service import MAX_TEXT, Service
from .helpers import MemoryDatabase, NoNER, fixture


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture()
        self.db = MemoryDatabase(self.data)
        self.service = Service(self.db, NoNER(), 'test-secret-' * 4)

    def call(self, tool, **kwargs):
        with redirect_stderr(io.StringIO()):
            return self.service.call(tool, **kwargs)

    def pages(self, case_id):
        result = self.call('get_case', case_id=case_id)
        pages = [result]
        while result.get('next_cursor'):
            result = self.call('get_case', case_id=case_id, cursor=result['next_cursor'])
            pages.append(result)
            self.assertLess(len(pages), 100)
        self.assertNotIn('error', result)
        return pages

    def test_all_directions_and_nested_json(self):
        for program in ('main', 'nto', 'family_income'):
            with self.subTest(program=program):
                result = self.call('list_cases', program=program)
                self.assertEqual(len(result['cases']), 1)
                case_id = result['cases'][0]['case_id']
                self.assertRegex(case_id, r'^[0-9a-f]{64}$')
                pages = self.pages(case_id)
                serialized = json.dumps(pages, ensure_ascii=False)
                for value in ('Иван', 'ivan@example.org', 'ivan_login', '+79991234567', '40817810099910004312',
                              'NEVER_OUTPUT_PASSWORD', 'NEVER_OUTPUT_UNKNOWN', 'RAW_EXCEPTION_SECRET', 'PRIVATE_FILE', 'Мария', 'Петрова'):
                    self.assertNotIn(value, serialized)
                self.assertIn('[Участник]', serialized)
                self.assertEqual(pages[0]['program'], program)
                for page in pages:
                    self.assertEqual(page['data_as_of'], pages[0]['data_as_of'])
                    self.assertEqual(page['redaction_rules_version'], RULES_VERSION)
                    self.assertTrue(page['automatically_redacted'])

    def test_relations_scores_and_amounts(self):
        for program, pk in [('main', 201), ('family_income', 701), ('nto', 601)]:
            items = [item for page in self.pages(self.service.opaque_id(program, pk)) for item in page['items']]
            by_section = {item['section']: item['record_id'] for item in items}
            if program == 'main':
                result = next(i for i in items if i['field'] == 'interviewer_score')
                self.assertEqual(result['value'], 4)
                self.assertEqual(result['links']['interview'], by_section['review_by_tutor_interview'])
            if program == 'family_income':
                result = next(i for i in items if i['field'] == 'gross_amount')
                self.assertEqual(result['value'], 123456)
                self.assertEqual(result['links']['family_income_document'], by_section['family_income_familyincomedocument'])
            if program == 'nto':
                result = next(i for i in items if i['field'] == 'ticket_cost')
                self.assertEqual(result['value'], 15000)

    def test_continuations_are_cleaned_complete_and_stable(self):
        text = ('Хочу изучать медицину. ' * 900) + 'ivan@example.org' + (' Готов учиться.' * 900)
        self.data['core_motivationletter'][0]['letter_text'] = text
        case_id = self.service.opaque_id('main', 201)
        first = self.call('get_case', case_id=case_id)
        self.data['core_motivationletter'][0]['letter_text'] = 'CHANGED_AFTER_FIRST_PAGE'
        pages, current = [first], first
        while current['next_cursor']:
            current = self.call('get_case', case_id=case_id, cursor=current['next_cursor'])
            pages.append(current)
        chunks = [i for p in pages for i in p['items'] if i['field'] == 'letter_text']
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(i['value']) <= MAX_TEXT for i in chunks))
        combined = ''.join(i['value'] for i in chunks)
        self.assertEqual(combined, text.replace('ivan@example.org', '[Контакт]'))
        self.assertEqual([i['offset'] for i in chunks], list(range(0, len(combined), MAX_TEXT)))
        self.assertEqual(self.db.reads, 1)
        self.assertNotIn('ivan@example.org', repr(self.service.snapshots))

    def test_list_pagination_filters_and_cursor_binding(self):
        self.data['scholar_form_userinfo'] += [dict(self.data['scholar_form_userinfo'][0], id=pk) for pk in range(202, 224)]
        first = self.call('list_cases', program='main', status='submitted')
        second = self.call('list_cases', program='main', status='submitted', cursor=first['next_cursor'])
        self.assertEqual(len(first['cases']), 20)
        self.assertEqual(len(second['cases']), 3)
        self.assertIsNone(second['next_cursor'])
        self.assertFalse({i['case_id'] for i in first['cases']} & {i['case_id'] for i in second['cases']})
        bad = self.call('list_cases', program='nto', cursor=first['next_cursor'])
        self.assertEqual(bad['error']['code'], 'invalid_request')
        tampered = self.call('list_cases', program='main', cursor=first['next_cursor'] + 'x')
        self.assertEqual(tampered['error']['code'], 'invalid_request')
        for kwargs in ({'limit': 21}, {'limit': 0}, {'status': 'ivan@example.org'}, {'limit': True}):
            self.assertEqual(self.call('list_cases', program='main', **kwargs)['error']['code'], 'invalid_request')

    def test_error_and_audit_never_include_source(self):
        class Broken(NoNER):
            def entities(self, text):
                raise RuntimeError('SOURCE ivan@example.org')
        self.service.ner = Broken()
        log = io.StringIO()
        with redirect_stderr(log):
            result = self.service.call('get_case', case_id=self.service.opaque_id('main', 201))
        self.assertEqual(result['error']['code'], 'redaction_failed')
        self.assertNotIn('ivan', json.dumps(result) + log.getvalue())
        self.assertEqual(set(json.loads(log.getvalue())), {'tool', 'elapsed_ms', 'code'})
        self.assertFalse(self.service.snapshots)

    def test_cursor_expiry_and_case_binding(self):
        first = self.call('get_case', case_id=self.service.opaque_id('main', 201))
        wrong = self.call('get_case', case_id=self.service.opaque_id('nto', 601), cursor=first['next_cursor'])
        self.assertEqual(wrong['error']['code'], 'invalid_request')
        with patch('development_mcp.service.time.monotonic', return_value=10**15):
            expired = self.call('get_case', case_id=first['case_id'], cursor=first['next_cursor'])
        self.assertEqual(expired['error']['code'], 'cursor_expired_restart_case')

    def test_birth_date_only_returns_age_group(self):
        self.data['scholar_form_userinfo'][0]['birth_date'] = date(2009, 3, 12)
        self.data['core_motivationletter'][0]['letter_text'] = 'Родился 2009-03-12 и хочу учиться.'
        pages = self.pages(self.service.opaque_id('main', 201))
        self.assertNotIn('2009', json.dumps([i['value'] for p in pages for i in p['items']]))
        self.assertTrue(any(i['field'] == 'age_group' and i['value'] == '14_17' for p in pages for i in p['items']))

    def test_overlarge_case_is_rejected_without_partial_output(self):
        self.data['core_motivationletter'][0]['letter_text'] = 'PRIVATE_SOURCE_' * 160000
        result = self.call('get_case', case_id=self.service.opaque_id('main', 201))
        self.assertEqual(result['error']['code'], 'case_too_large')
        self.assertNotIn('PRIVATE_SOURCE', json.dumps(result))
        self.assertFalse(self.service.snapshots)

    def test_database_failure_is_safe_and_placeholder_secret_is_rejected(self):
        with patch.object(self.db, 'read', side_effect=RuntimeError('postgres://SECRET_PASSWORD/PRIVATE_TEXT')):
            log = io.StringIO()
            with redirect_stderr(log):
                result = self.service.call('list_cases', program='main')
        self.assertEqual(result['error']['code'], 'unavailable')
        self.assertNotIn('SECRET_PASSWORD', json.dumps(result) + log.getvalue())
        with self.assertRaises(ValueError):
            Service(self.db, NoNER(), 'REPLACE_WITH_AN_INDEPENDENT_RANDOM_SECRET')


class SchemaTests(unittest.TestCase):
    def test_allowlist_matches_models_and_never_exposes_file_fields(self):
        root = Path(__file__).resolve().parents[2]
        models = {'auth_user': {'id': 'AutoField', 'first_name': 'CharField', 'last_name': 'CharField', 'email': 'EmailField', 'username': 'CharField'}}
        for model_path in sorted(root.glob('*/models.py')):
            app = model_path.parent.name
            tree = ast.parse(model_path.read_text(encoding='utf-8-sig'))
            for cls in tree.body:
                if not isinstance(cls, ast.ClassDef):
                    continue
                fields = {'id': 'AutoField'}
                for node in cls.body:
                    if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                        continue
                    func = node.value.func
                    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == 'models':
                        field = node.targets[0].id
                        if func.attr in ('ForeignKey', 'OneToOneField'):
                            field += '_id'
                        fields[field] = func.attr
                models[app + '_' + cls.name.lower()] = fields
        for table, spec in TABLES.items():
            if table.startswith('nto_travel_') and not (root / 'nto_travel' / 'models.py').exists():
                continue
            with self.subTest(table=table):
                self.assertTrue(set(spec.columns) <= set(models[table]), set(spec.columns) - set(models[table]))
                for column in spec.output:
                    self.assertNotIn(models[table][column], {'FileField', 'ImageField', 'URLField', 'ForeignKey', 'OneToOneField', 'DateField', 'DateTimeField'})
                    self.assertNotRegex(column, r'password|token|error|yandex|passport|snils|bank_account')
                for definition in spec.filters:
                    if definition.kind == 'number':
                        self.assertIn(models[table][definition.field], {'IntegerField', 'PositiveIntegerField', 'PositiveSmallIntegerField', 'PositiveBigIntegerField', 'SmallIntegerField', 'BigIntegerField', 'DecimalField', 'FloatField'})
                    elif definition.kind in {'text', 'choice'}:
                        self.assertIn(models[table][definition.field], {'CharField', 'TextField'})
