"""Measure redaction on annotated control texts. Reports never contain source values."""

import argparse
import hashlib
import json
import logging
from pathlib import Path
import re
import sys
import time
from importlib.metadata import version

from . import RULES_VERSION
from .bundle import MAX_BYTES, loads
from .redaction import Cleaner, LABELS, RussianNER, normalize

DEFAULT_CORPUS = Path(__file__).with_name('redaction_cases.json')


def read_corpus(path):
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError('corpus_too_large')
    corpus = loads(raw.decode('utf-8'))
    if not isinstance(corpus, dict) or corpus.get('version') != 1 or not isinstance(corpus.get('cases'), list) or not 1 <= len(corpus['cases']) <= 1000:
        raise ValueError('invalid_corpus')
    seen = set()
    for case in corpus['cases']:
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', case['id']) or case['id'] in seen or not isinstance(case['text'], str):
            raise ValueError('invalid_case')
        seen.add(case['id'])
        if not case['sensitive'] or not all(isinstance(item['value'], str) and item['value'] for item in case['sensitive']):
            raise ValueError('missing_annotation')
        if any(identity['kind'] not in LABELS for identity in case.get('identities', [])):
            raise ValueError('invalid_identity')
        if not all(isinstance(value, str) and value and normalize(value) in normalize(case['text']) for value in case.get('preserve', [])):
            raise ValueError('invalid_preservation_annotation')
    return corpus


def evaluate_quality(corpus, ner, min_recall=1.0, min_preservation=1.0, min_precision=0.0):
    reports, totals = [], dict(gold_characters=0, predicted_characters=0, true_positive_characters=0,
                              sensitive_occurrences=0, removed_occurrences=0, preservation_checks=0, preserved_checks=0, errors=0)
    for case in corpus['cases']:
        start = time.monotonic()
        text, gold, annotations = normalize(case['text']), set(), []
        for number, item in enumerate(case['sensitive']):
            matches = list(re.finditer(re.escape(normalize(item['value'])), text, re.I))
            if not matches:
                raise ValueError('annotation_not_found')
            for match in matches:
                positions = {i for i in range(match.start(), match.end()) if text[i].isalnum()}
                if not positions:
                    raise ValueError('empty_annotation')
                gold |= positions
                annotations.append((number, positions))
        cleaner = Cleaner(ner)
        try:
            for identity in case.get('identities', []):
                cleaner.register(identity['value'], identity['kind'])
            cleaner.prepare([text])
            cleaned, spans = cleaner.clean_with_spans(text)
            predicted = {i for first, last, _ in spans for i in range(first, last) if text[i].isalnum()}
            missed = [number for number, positions in annotations if not positions <= predicted]
            preserved = sum(normalize(value) in cleaned for value in case.get('preserve', []))
            error = False
        except Exception:
            predicted, missed, preserved, error = set(), [number for number, _ in annotations], 0, True
        totals['gold_characters'] += len(gold)
        totals['predicted_characters'] += len(predicted)
        totals['true_positive_characters'] += len(gold & predicted)
        totals['sensitive_occurrences'] += len(annotations)
        totals['removed_occurrences'] += len(annotations) - len(missed)
        totals['preservation_checks'] += len(case.get('preserve', []))
        totals['preserved_checks'] += preserved
        totals['errors'] += int(error)
        reports.append({'id': case['id'], 'annotations': len(annotations), 'missed_annotation_indices': sorted(set(missed)),
                        'preserved_checks': preserved, 'preservation_checks': len(case.get('preserve', [])),
                        'error': error, 'elapsed_ms': round((time.monotonic() - start) * 1000)})
    recall = totals['removed_occurrences'] / totals['sensitive_occurrences'] if totals['sensitive_occurrences'] else 0
    precision = totals['true_positive_characters'] / totals['predicted_characters'] if totals['predicted_characters'] else 0
    preservation = totals['preserved_checks'] / totals['preservation_checks'] if totals['preservation_checks'] else 1
    fingerprint = hashlib.sha256(json.dumps(corpus, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'format': 'putevka.redaction-quality', 'version': 1, 'rules_version': RULES_VERSION,
            'implementation_sha256': hashlib.sha256(Path(__file__).with_name('redaction.py').read_bytes()).hexdigest(),
            'runtime': {'python': sys.version.split()[0], **{name: version(name) for name in ('natasha', 'pymorphy3', 'numpy')}},
            'corpus_sha256': fingerprint, 'passed': not totals['errors'] and recall >= min_recall and preservation >= min_preservation and precision >= min_precision,
            'metrics': {'annotated_occurrence_recall': recall, 'annotated_character_precision': precision, 'preservation': preservation, **totals},
            'thresholds': {'min_recall': min_recall, 'min_preservation': min_preservation, 'min_precision': min_precision}, 'cases': reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=DEFAULT_CORPUS)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--min-recall', type=float, default=1.0)
    parser.add_argument('--min-preservation', type=float, default=1.0)
    parser.add_argument('--min-precision', type=float, default=0.0)
    args = parser.parse_args()
    if any(not 0 <= value <= 1 for value in (args.min_recall, args.min_preservation, args.min_precision)):
        parser.error('Thresholds must be between zero and one')
    logging.disable(sys.maxsize)
    try:
        report = evaluate_quality(read_corpus(args.corpus), RussianNER(), args.min_recall, args.min_preservation, args.min_precision)
        if args.output:
            from .export import write_bundle
            write_bundle(args.output, report)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report['passed'] else 1
    except Exception:
        print('{"code":"quality_check_failed"}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
