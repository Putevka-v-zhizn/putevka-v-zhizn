"""Freeze selected cleaned case texts and optional reference answers for replay."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from .bundle import MAX_BYTES, loads, validate_bundle

FORMAT = 'putevka.text-eval-dataset'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _selector(value):
    table, field = value.rsplit('.', 1)
    if not re.fullmatch(r'[a-z_][a-z0-9_]*', table) or not re.fullmatch(r'[a-z_][a-z0-9_]*', field):
        raise ValueError('invalid_selector')
    return table, field


def freeze(bundles, fields, references=(), limit=20, max_characters=100000):
    if type(limit) is not int or not 1 <= limit <= 500 or type(max_characters) is not int or not 1 <= max_characters <= 1000000:
        raise ValueError('invalid_limits')
    selected = {_selector(value) for value in fields}
    refs = []
    for value in references:
        source, key = value.split('=', 1)
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*', key):
            raise ValueError('invalid_reference_key')
        refs.append((*_selector(source), key))
    if len({key for _, _, key in refs}) != len(refs):
        raise ValueError('duplicate_reference_key')
    examples, sources = {}, set()
    for bundle in bundles:
        validate_bundle(bundle)
        sources.add(digest(bundle))
        for record in bundle['records']:
            for table, field in sorted(selected):
                if record['table'] != table or not isinstance(record['fields'].get(field), str) or not record['fields'][field].strip():
                    continue
                text = record['fields'][field]
                if len(text) > max_characters:
                    raise ValueError('sample_too_large')
                expected = {}
                for ref_table, ref_field, key in refs:
                    related = [r for r in bundle['records'] if r['table'] == ref_table and
                               (r['id'] == record['id'] or record['id'] in r['links'].values() or r['id'] in record['links'].values())]
                    values = [r['fields'][ref_field] for r in related if r['fields'].get(ref_field) is not None]
                    if len(values) > 1:
                        raise ValueError('ambiguous_reference')
                    if values:
                        expected[key] = values[0]
                key = digest([bundle['case_id'], record['id'], table, field])
                example = {'id': key, 'case_id': bundle['case_id'], 'record_id': record['id'], 'table': table, 'field': field,
                           'text': text, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'expected': expected}
                if key in examples and examples[key] != example:
                    raise ValueError('conflicting_case_versions')
                examples[key] = example
    if not examples:
        raise ValueError('empty_selection')
    body = {'format': FORMAT, 'version': 1, 'sources': sorted(sources),
            'examples': [examples[key] for key in sorted(examples)[:limit]]}
    result = {**body, 'sha256': digest(body)}
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError('dataset_too_large')
    return result


def read_dataset(path):
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError('dataset_too_large')
    return validate_dataset(loads(raw.decode('utf-8')))


def validate_dataset(data):
    if data.get('format') != FORMAT or data.get('version') != 1 or set(data) != {'format', 'version', 'sources', 'examples', 'sha256'}:
        raise ValueError('invalid_dataset')
    body = {key: value for key, value in data.items() if key != 'sha256'}
    if data['sha256'] != digest(body) or not isinstance(data['examples'], list) or not 1 <= len(data['examples']) <= 500:
        raise ValueError('dataset_changed_or_empty')
    seen = set()
    for example in data['examples']:
        if set(example) != {'id', 'case_id', 'record_id', 'table', 'field', 'text', 'text_sha256', 'expected'}:
            raise ValueError('invalid_example_fields')
        _selector(example['table'] + '.' + example['field'])
        if example['id'] in seen or not all(re.fullmatch('[0-9a-f]{64}', example[key]) for key in ('id', 'case_id', 'record_id')):
            raise ValueError('invalid_example_id')
        seen.add(example['id'])
        if not isinstance(example['text'], str) or len(example['text']) > 1000000 or not isinstance(example['expected'], dict):
            raise ValueError('invalid_example')
        if example['text_sha256'] != hashlib.sha256(example['text'].encode()).hexdigest():
            raise ValueError('sample_changed')
        for key in example['expected']:
            if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*', key):
                raise ValueError('invalid_reference_key')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundles', nargs='+', type=Path)
    parser.add_argument('--field', action='append', required=True, help='table.field containing cleaned text')
    parser.add_argument('--reference', action='append', default=[], help='table.field=output_key; unique related reference')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--max-characters', type=int, default=100000)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        bundles, total_bytes = [], 0
        for path in args.bundles:
            with path.open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
            total_bytes += len(raw)
            if total_bytes > MAX_BYTES:
                raise ValueError('bundle_too_large')
            bundles.append(loads(raw.decode('utf-8')))
        dataset = freeze(bundles, args.field, args.reference, args.limit, args.max_characters)
        from .export import write_bundle
        write_bundle(args.output, dataset)
        print(json.dumps({'code': 'ok', 'samples': len(dataset['examples']), 'sha256': dataset['sha256'],
                          'characters': sum(len(e['text']) for e in dataset['examples']),
                          'samples_with_reference': sum(bool(e['expected']) for e in dataset['examples'])}))
        return 0
    except Exception:
        print('{"code":"dataset_freeze_failed_no_overwrite"}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
