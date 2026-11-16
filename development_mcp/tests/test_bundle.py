import copy
import io
import json
from contextlib import redirect_stderr
from pathlib import Path
import tempfile
import unittest

from development_mcp.bundle import BundleError, Collector, loads, validate_bundle
from development_mcp.export import write_bundle
from development_mcp.service import Service
from .helpers import MemoryDatabase, NoNER, fixture


def exported_case(program='main', data=None):
    data = fixture() if data is None else data
    data['core_motivationletter'][0]['letter_text'] = 'Хочу стать врачом. ' * 1400 + 'ivan@example.org'
    service = Service(MemoryDatabase(data), NoNER(), 'export-test-secret-12345678901234567')
    pk = {'main': 201, 'nto': 601, 'family_income': 701}[program]
    pages, collector, cursor = [], Collector(), None
    with redirect_stderr(io.StringIO()):
        while True:
            page = service.call('export_case', case_id=service.opaque_id(program, pk), cursor=cursor)
            pages.append(page)
            collector.add(page)
            cursor = page.get('next_cursor')
            if not cursor:
                break
    return collector.finish(), pages


class BundleTests(unittest.TestCase):
    def test_json_preserves_empty_containers_and_rejects_masked_key_collisions(self):
        data = fixture()
        data['nto_travel_ntoapplication'][0]['achievements'] = [{}, [], {'nested': {}, 'items': [[]]}]
        bundle, _ = exported_case('nto', data)
        app = next(r for r in bundle['records'] if r['table'] == 'nto_travel_ntoapplication')
        self.assertEqual(app['fields']['achievements'], [{}, [], {'nested': {}, 'items': [[]]}])
        data['nto_travel_ntoapplication'][0]['achievements'] = [{'ivan@example.org': 'a', 'other@example.org': 'b'}]
        with self.assertRaises(BundleError):
            exported_case('nto', data)

    def test_exports_all_directions_and_restores_json_and_long_text(self):
        for program in ('main', 'nto', 'family_income'):
            bundle, _ = exported_case(program)
            validate_bundle(bundle)
            text = json.dumps(bundle, ensure_ascii=False)
            for secret in ('ivan@example.org', 'Иван', 'PRIVATE_FILE', 'RAW_EXCEPTION_SECRET'):
                self.assertNotIn(secret, text)
            if program == 'main':
                letter = next(r for r in bundle['records'] if r['table'] == 'core_motivationletter')
                self.assertEqual(letter['fields']['letter_text'], 'Хочу стать врачом. ' * 1400 + '[Контакт]')
            app = next((r for r in bundle['records'] if r['table'] == 'nto_travel_ntoapplication'), None)
            if app:
                self.assertIsInstance(app['fields']['achievements'][0], dict)

    def test_rejects_broken_pages_and_snapshot_changes(self):
        _, pages = exported_case()
        collector = Collector()
        collector.add(pages[0])
        changed = copy.deepcopy(pages[1])
        changed['data_as_of'] = '2000-01-01T00:00:00+00:00'
        with self.assertRaises(BundleError):
            collector.add(changed)
        with self.assertRaises(BundleError):
            collector.finish()
        broken = copy.deepcopy(pages)
        item = next(item for p in broken for item in p['items'] if item['field'] == 'letter_text')
        item['offset'] = 1
        with self.assertRaises(BundleError):
            collector = Collector()
            for page in broken:
                collector.add(page)
            collector.finish()

    def test_rejects_private_fields_wrong_links_and_versions(self):
        bundle, _ = exported_case()
        for mutation in ('private', 'link', 'version', 'redaction'):
            changed = copy.deepcopy(bundle)
            if mutation == 'private':
                changed['records'][0]['fields']['password'] = 'DO_NOT_IMPORT'
            elif mutation == 'link':
                record = next(r for r in changed['records'] if r['table'] == 'review_by_tutor_interviewresult')
                record['links']['interview'] = changed['root_record_id']
            elif mutation == 'version':
                changed['version'] = 999
            else:
                changed['automatically_redacted'] = False
            with self.subTest(mutation=mutation), self.assertRaises(BundleError):
                validate_bundle(changed)
        with self.assertRaises(BundleError):
            loads('{"version":1,"version":2}')

    def test_local_file_is_never_overwritten(self):
        bundle, _ = exported_case()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'case.json'
            write_bundle(path, bundle)
            self.assertEqual(loads(path.read_text(encoding='utf-8')), bundle)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_bundle(path, bundle)
            self.assertEqual(path.read_bytes(), original)
