"""Portable cleaned case format. No Django, SDK or database dependency."""

import json
import math
import re
from datetime import datetime

from .schema import PROGRAMS, TABLES

FORMAT = 'putevka.development-case'
VERSION = 1
MAX_BYTES = 64 * 1024 * 1024
ID = re.compile(r'[0-9a-f]{64}\Z')
HEADER = ('format', 'version', 'case_id', 'program', 'root_record_id', 'registry_version',
          'data_as_of', 'redaction_rules_version', 'automatically_redacted')


class BundleError(Exception):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BundleError('duplicate_json_key')
        result[key] = value
    return result


def loads(text):
    try:
        return json.loads(text, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(BundleError('invalid_number')))
    except (ValueError, RecursionError):
        raise BundleError('invalid_json') from None


def _json_value(value, depth=0):
    if depth > 40:
        raise BundleError('excessive_nesting')
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item, depth + 1)
    elif isinstance(value, dict) and all(isinstance(k, str) for k in value):
        for item in value.values():
            _json_value(item, depth + 1)
    else:
        raise BundleError('invalid_field_value')


def validate_bundle(bundle):
    if not isinstance(bundle, dict) or bundle.get('format') != FORMAT or type(bundle.get('version')) is not int or bundle['version'] != VERSION:
        raise BundleError('unsupported_format')
    if not set(HEADER) <= bundle.keys() or set(bundle) - set(HEADER) - {'records'}:
        raise BundleError('invalid_header')
    if bundle['program'] not in PROGRAMS or bundle['automatically_redacted'] is not True:
        raise BundleError('unredacted_or_unknown_program')
    if not all(isinstance(bundle[k], str) and ID.fullmatch(bundle[k]) for k in ('case_id', 'root_record_id')):
        raise BundleError('invalid_identifier')
    if not isinstance(bundle['registry_version'], str) or not re.fullmatch(r'[0-9a-f]{16}', bundle['registry_version']):
        raise BundleError('invalid_registry_version')
    if not isinstance(bundle['redaction_rules_version'], str) or len(bundle['redaction_rules_version']) > 80:
        raise BundleError('invalid_redaction_version')
    try:
        if datetime.fromisoformat(bundle['data_as_of']).tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError):
        raise BundleError('invalid_timestamp') from None
    records = bundle.get('records')
    if not isinstance(records, list) or not 1 <= len(records) <= 500:
        raise BundleError('invalid_record_count')
    indexed, participants = {}, set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {'id', 'table', 'links', 'fields'}:
            raise BundleError('invalid_record')
        table, token = record['table'], record['id']
        if table not in TABLES or not TABLES[table].output or not isinstance(token, str) or not ID.fullmatch(token) or token in indexed:
            raise BundleError('invalid_record_identity')
        spec = TABLES[table]
        allowed = set(spec.output) | ({'age_group'} if spec.age_field else set())
        if not isinstance(record['fields'], dict) or not record['fields'].keys() <= allowed:
            raise BundleError('unapproved_field')
        _json_value(record['fields'])
        if 'age_group' in record['fields'] and record['fields']['age_group'] not in {'unknown', 'under_14', '14_17', '18_24', '25_plus'}:
            raise BundleError('invalid_age_group')
        links = record['links']
        references = {key.removesuffix('_id'): target for key, target in spec.references.items() if TABLES[target].output}
        if not isinstance(links, dict) or not links.keys() <= references.keys() | {'participant'}:
            raise BundleError('unapproved_link')
        if any(not isinstance(v, str) or not ID.fullmatch(v) for v in links.values()):
            raise BundleError('invalid_link_identity')
        if 'participant' in links:
            participants.add(links['participant'])
        indexed[token] = record
    if len(participants) > 1:
        raise BundleError('multiple_participants')
    root = indexed.get(bundle['root_record_id'])
    if not root or root['table'] != PROGRAMS[bundle['program']][0]:
        raise BundleError('missing_root_record')
    for record in records:
        spec = TABLES[record['table']]
        for column, table in spec.references.items():
            token = record['links'].get(column.removesuffix('_id'))
            if token is not None and (token not in indexed or indexed[token]['table'] != table):
                raise BundleError('dangling_or_wrong_link')
    try:
        size = len(json.dumps(bundle, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    except (ValueError, RecursionError):
        raise BundleError('invalid_json') from None
    if size > MAX_BYTES:
        raise BundleError('bundle_too_large')
    return bundle


class Collector:
    """Reassemble full fields without losing text at page boundaries."""

    def __init__(self):
        self.header = None
        self.records = {}
        self.parts = {}
        self.pages = 0
        self.characters = 0
        self.done = False
        self.cursors = set()

    def add(self, page):
        if self.done or not isinstance(page, dict) or 'error' in page:
            raise BundleError('export_failed')
        header = {key: page.get(key) for key in HEADER}
        if self.header is None:
            self.header = header
        elif header != self.header:
            raise BundleError('inconsistent_export_snapshot')
        self.pages += 1
        items = page.get('items')
        if self.pages > 10000 or not isinstance(items, list) or not items or len(items) > 20:
            raise BundleError('invalid_export_page')
        for item in items:
            try:
                table, token, name = item['section'], item['record_id'], item['field']
                spec = TABLES[table]
                if name not in spec.output and not (spec.age_field and name == 'age_group'):
                    raise BundleError('unapproved_field')
                record = self.records.setdefault(token, {'id': token, 'table': table, 'links': item['links'], 'fields': {}})
                if record['table'] != table or record['links'] != item['links'] or name in record['fields']:
                    raise BundleError('duplicate_or_inconsistent_field')
                if item['encoding'] in {'text', 'json'}:
                    value, offset, total = item['value'], item['offset'], item['total_characters']
                    if not isinstance(value, str) or len(value) > 10000 or type(offset) is not int or type(total) is not int or total < 0 or (total and not value):
                        raise BundleError('invalid_text_chunk')
                    state = self.parts.setdefault((token, name), [0, total, item['encoding'], []])
                    if offset != state[0] or total != state[1] or item['encoding'] != state[2] or offset + len(value) > total:
                        raise BundleError('incomplete_text')
                    state[0] += len(value)
                    state[3].append(value)
                    self.characters += len(value)
                    if state[0] == total:
                        text = ''.join(state[3])
                        record['fields'][name] = loads(text) if state[2] == 'json' else text
                        del self.parts[(token, name)]
                elif item['encoding'] == 'scalar':
                    _json_value(item['value'])
                    record['fields'][name] = item['value']
                else:
                    raise BundleError('invalid_encoding')
            except (KeyError, TypeError):
                raise BundleError('invalid_export_item') from None
        cursor = page.get('next_cursor')
        if self.characters > MAX_BYTES or len(self.records) > 500:
            raise BundleError('bundle_too_large')
        if cursor:
            if not isinstance(cursor, str) or cursor in self.cursors:
                raise BundleError('repeated_cursor')
            self.cursors.add(cursor)
        else:
            self.done = True

    def finish(self):
        if not self.done or self.parts or self.header is None:
            raise BundleError('incomplete_export')
        return validate_bundle({**self.header, 'records': list(self.records.values())})
