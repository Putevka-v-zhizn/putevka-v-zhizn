"""Opt-in integration tests. ONLY use a new disposable database named mcp_test.

Creates a cluster role and tables; intentionally refuses other database names.
Never point this at the application database.
"""
import ast
from dataclasses import replace
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from development_mcp.database import AccessDenied, Database, ROLE, audit_privileges
from development_mcp.grants import grant_sql
from development_mcp.schema import TABLES
from .helpers import fixture, NoNER
from development_mcp.service import Service


ADMIN_URL = os.environ.get('MCP_TEST_ADMIN_URL')


def apply_grants(connection, update=False):
    # psql meta commands are exercised through the documented SQL generator;
    # adapt only those client-side commands for the psycopg test connection.
    script = []
    for line in grant_sql(update=update).splitlines():
        if line.startswith(('--', '\\')):
            continue
        if '\\gexec' in line:
            line = f'GRANT CONNECT ON DATABASE mcp_test TO {ROLE};'
        script.append(line)
    connection.execute('\n'.join(script))


def model_types():
    root = Path(__file__).resolve().parents[2]
    types = {}
    for model_path in sorted(root.glob('*/models.py')):
        app = model_path.parent.name
        for cls in ast.parse(model_path.read_text(encoding='utf-8-sig')).body:
            if not isinstance(cls, ast.ClassDef):
                continue
            fields = {'id': 'bigint'}
            for node in cls.body:
                if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                    continue
                fn = node.value.func
                if not isinstance(fn, ast.Attribute) or not isinstance(fn.value, ast.Name) or fn.value.id != 'models':
                    continue
                name = node.targets[0].id
                kind = fn.attr
                if kind in ('ForeignKey', 'OneToOneField'):
                    name += '_id'
                    pgtype = 'bigint'
                elif kind in ('IntegerField', 'PositiveIntegerField', 'PositiveSmallIntegerField', 'PositiveBigIntegerField'):
                    pgtype = 'bigint'
                else:
                    pgtype = {'BooleanField': 'boolean', 'DateField': 'date', 'DecimalField': 'numeric', 'JSONField': 'jsonb'}.get(kind, 'text')
                fields[name] = pgtype
            types[app + '_' + cls.name.lower()] = fields
    types['auth_user'] = dict(id='bigint', first_name='text', last_name='text', email='text', username='text')
    # Optional NTO can be absent from this checkout. Its server protocol is still
    # exercised with synthetic tables; live Django columns are checked separately.
    for table, spec in TABLES.items():
        if table in types:
            continue
        if not table.startswith('nto_travel_'):
            raise RuntimeError('Unknown application table in test registry')
        fields = {column: ('bigint' if column == 'id' or column.endswith('_id') else 'text') for column in spec.columns}
        for row in fixture().get(table, []):
            for column, value in row.items():
                if column in fields and value is not None:
                    if type(value) is bool: fields[column] = 'boolean'
                    elif isinstance(value, (list, dict)): fields[column] = 'jsonb'
                    elif type(value) in (int, float): fields[column] = 'numeric'
        for definition in spec.filters:
            if definition.kind == 'number': fields[definition.field] = 'numeric'
        types[table] = fields
    return types


@unittest.skipUnless(ADMIN_URL, 'MCP_TEST_ADMIN_URL not set; requires disposable PostgreSQL')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = conninfo_to_dict(ADMIN_URL)
        if config.get('dbname') != 'mcp_test':
            raise RuntimeError('Refusing to modify a database other than mcp_test')
        cls.admin = psycopg.connect(ADMIN_URL, autocommit=True, row_factory=dict_row)
        # Requiring an empty database prevents accidental changes to an existing fixture.
        if cls.admin.execute("SELECT 1 FROM pg_tables WHERE schemaname='public'").fetchone():
            raise RuntimeError('Disposable test database must be empty')
        types = model_types()
        for table, spec in TABLES.items():
            columns = [sql.SQL('{} {}').format(sql.Identifier(column), sql.SQL(types[table][column])) for column in spec.columns]
            columns.append(sql.SQL('future_secret text'))
            cls.admin.execute(sql.SQL('CREATE TABLE public.{} ({})').format(sql.Identifier(table), sql.SQL(', ').join(columns)))
        for table, rows in fixture().items():
            for row in rows:
                columns = [c for c in row if c in TABLES[table].columns]
                values = [Jsonb(row[c]) if types[table][c] == 'jsonb' else row[c] for c in columns]
                cls.admin.execute(sql.SQL('INSERT INTO public.{} ({}) VALUES ({})').format(
                    sql.Identifier(table), sql.SQL(', ').join(map(sql.Identifier, columns)),
                    sql.SQL(', ').join(sql.Placeholder() for _ in columns)), values)
        apply_grants(cls.admin)
        cls.admin.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(ROLE), sql.Literal('mcp-reader-test-only')))
        cls.reader_url = make_conninfo(ADMIN_URL, user=ROLE, password='mcp-reader-test-only')

    @classmethod
    def tearDownClass(cls):
        cls.admin.close()

    def test_reader_queries_all_directions(self):
        for program in ('main', 'nto', 'family_income'):
            with Database(self.reader_url).read() as reader:
                roots = reader.list_roots(program, None, 0, 20)
                self.assertEqual(len(roots), 1)
                records = reader.load_case(program, roots[0]['id'])
                self.assertGreater(len(records), 3)
                self.assertTrue(all('future_secret' not in row for _, row in records))

    def test_database_denies_write_ddl_and_unlisted_columns(self):
        # Disable default read-only to prove ACLs, independently of transaction mode.
        statements = [
            "INSERT INTO scholar_form_userinfo (id) VALUES (999)",
            "UPDATE scholar_form_userinfo SET form_status='approved'",
            "DELETE FROM scholar_form_userinfo", "TRUNCATE scholar_form_userinfo",
            "ALTER TABLE scholar_form_userinfo ADD COLUMN injected text",
            "CREATE TABLE public.injected (id bigint)",
            "SELECT future_secret FROM scholar_form_userinfo", "SELECT * FROM auth_user",
        ]
        for statement in statements:
            with self.subTest(statement=statement), psycopg.connect(self.reader_url, autocommit=True) as connection:
                connection.execute('SET default_transaction_read_only=off')
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(statement)

    def test_runtime_transaction_is_read_only(self):
        with Database(self.reader_url).read() as reader:
            mode = reader.connection.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']
            self.assertEqual(mode, 'on')

    def test_admin_and_extra_privileges_are_rejected(self):
        with self.assertRaises(AccessDenied), psycopg.connect(ADMIN_URL, row_factory=dict_row) as connection:
            audit_privileges(connection)
        self.admin.execute(sql.SQL('GRANT SELECT (future_secret) ON auth_user TO {}').format(sql.Identifier(ROLE)))
        try:
            with self.assertRaises(AccessDenied), Database(self.reader_url).read():
                pass
        finally:
            self.admin.execute(sql.SQL('REVOKE SELECT (future_secret) ON auth_user FROM {}').format(sql.Identifier(ROLE)))

    def test_update_grants_is_idempotent_and_follows_field_changes(self):
        password_before = self.admin.execute('SELECT rolpassword FROM pg_authid WHERE rolname=%s', (ROLE,)).fetchone()['rolpassword']
        table = 'core_motivationletter'
        spec = replace(TABLES[table], output=TABLES[table].output + ('future_secret',))
        self.admin.execute("UPDATE core_motivationletter SET future_secret='Новый комментарий'")
        self.admin.execute(sql.SQL('GRANT SELECT, UPDATE ON auth_user TO {}').format(sql.Identifier(ROLE)))
        self.admin.execute('CREATE TABLE mcp_removed_fixture (id bigint, old_text text)')
        self.admin.execute(sql.SQL('GRANT SELECT (id, old_text) ON mcp_removed_fixture TO {}').format(sql.Identifier(ROLE)))
        try:
            with patch.dict(TABLES, {table: spec}):
                apply_grants(self.admin, update=True)
                apply_grants(self.admin, update=True)
                with Database(self.reader_url).read() as reader:
                    row = reader.select(table, 'id', [401])[0]
                    self.assertEqual(row['future_secret'], 'Новый комментарий')
            apply_grants(self.admin, update=True)
            with Database(self.reader_url).read():
                pass
            with psycopg.connect(self.reader_url, autocommit=True) as connection:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    connection.execute('SELECT future_secret FROM core_motivationletter')
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    connection.execute('SELECT old_text FROM mcp_removed_fixture')
            password_after = self.admin.execute('SELECT rolpassword FROM pg_authid WHERE rolname=%s', (ROLE,)).fetchone()['rolpassword']
            self.assertEqual(password_before, password_after)
        finally:
            apply_grants(self.admin, update=True)
            self.admin.execute('DROP TABLE mcp_removed_fixture')

    def test_selection_filters_and_summaries_execute_in_postgres(self):
        original_letter = self.admin.execute('SELECT status, admin_score FROM core_motivationletter WHERE id=401').fetchone()
        original_stage = self.admin.execute('SELECT selection_step FROM scholar_form_userinfo WHERE id=201').fetchone()['selection_step']
        try:
            self.admin.execute("UPDATE core_motivationletter SET status='revision', admin_score=4 WHERE id=401")
            self.admin.execute("UPDATE scholar_form_userinfo SET selection_step='ml' WHERE id=201")
            self.admin.execute('INSERT INTO auth_user (id) VALUES (102),(103)')
            self.admin.execute("INSERT INTO scholar_form_userinfo (id,user_id,form_status) VALUES (202,102,'submitted'),(203,103,'submitted')")
            self.admin.execute("INSERT INTO core_motivationletter (id,user_id,status,letter_text) VALUES (411,102,'revision',%s)", (' \n\t',))
            self.admin.execute('INSERT INTO review_by_tutor_interview (id,user_id,transcript) VALUES (511,102,%s)', (' \n\t',))
            self.admin.execute('INSERT INTO review_by_tutor_testassignment (id,user_id) VALUES (801,101),(802,101),(803,102),(804,999)')
            with Database(self.reader_url).read() as reader:
                found = reader.list_roots('main', 'submitted', 0, 20, filters={
                    'has_interview_transcript': True, 'letter_status': 'revision',
                    'motivation_score': {'min': 4, 'max': 4}, 'test_count': {'min': 2}, 'selection_step': 'ml'})
                self.assertEqual([row['id'] for row in found], [201])
                self.assertEqual(found[0]['feature_test_count'], 2)
                self.assertEqual(found[0]['feature_letter_status'], ['revision'])
                self.assertTrue(all(key in {'id', 'form_status'} or key.startswith('feature_') for key in found[0]))
                self.assertNotIn('Здравствуйте', str(found))
                for name in ('has_interview_transcript', 'has_motivation_letter'):
                    absent = reader.list_roots('main', None, 0, 20, filters={name: False})
                    self.assertEqual([row['id'] for row in absent], [202, 203])
                zeros = reader.list_roots('main', None, 0, 20, filters={'test_count': {'max': 0}})
                self.assertEqual([row['id'] for row in zeros], [203])
                family = reader.list_roots('family_income', None, 0, 20, filters={'income_source_count': {'min': 1}, 'family_size': {'min': 3}})
                self.assertEqual([row['id'] for row in family], [701])
                nto = reader.list_roots('nto', None, 0, 20, filters={'criticality': {'min': 4}, 'has_situation_details': True})
                self.assertEqual([row['id'] for row in nto], [601])
                first = reader.list_roots('main', None, 0, 1, filters={'has_interview_transcript': False})
                second = reader.list_roots('main', None, 1, 1, filters={'has_interview_transcript': False})
                self.assertEqual([first[0]['id'], second[0]['id']], [202, 203])
            class NoTextAllowed(NoNER):
                def entities(self, text):
                    raise AssertionError('list_cases must not load or redact case texts')
            service = Service(Database(self.reader_url), NoTextAllowed(), 'selection-postgres-test-secret-12345')
            result = service.call('list_cases', program='main', filters={'letter_status': 'revision'})
            self.assertEqual(len(result['cases']), 2)
        finally:
            self.admin.execute('DELETE FROM review_by_tutor_testassignment WHERE id IN (801,802,803,804)')
            self.admin.execute('DELETE FROM review_by_tutor_interview WHERE id=511')
            self.admin.execute('DELETE FROM core_motivationletter WHERE id=411')
            self.admin.execute('DELETE FROM scholar_form_userinfo WHERE id IN (202,203)')
            self.admin.execute('DELETE FROM auth_user WHERE id IN (102,103)')
            self.admin.execute('UPDATE core_motivationletter SET status=%s,admin_score=%s WHERE id=401',
                               (original_letter['status'], original_letter['admin_score']))
            self.admin.execute('UPDATE scholar_form_userinfo SET selection_step=%s WHERE id=201', (original_stage,))
