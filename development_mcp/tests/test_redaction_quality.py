import json
import unittest

from development_mcp.redaction import RussianNER
from development_mcp.redaction_quality import DEFAULT_CORPUS, evaluate_quality, read_corpus
from .helpers import NoNER


class RedactionQualityTests(unittest.TestCase):
    def test_default_control_corpus_has_no_misses_or_preservation_losses(self):
        report = evaluate_quality(read_corpus(DEFAULT_CORPUS), RussianNER())
        self.assertTrue(report['passed'])
        self.assertEqual(report['metrics']['annotated_occurrence_recall'], 1)
        self.assertEqual(report['metrics']['preservation'], 1)

    def test_report_contains_metrics_and_no_sensitive_values(self):
        corpus = {'version': 1, 'cases': [{'id': 'contact', 'text': 'Почта private@example.org. Хочу учиться.',
                  'sensitive': [{'value': 'private@example.org'}], 'preserve': ['Хочу учиться.']}]}
        report = evaluate_quality(corpus, NoNER())
        self.assertTrue(report['passed'])
        self.assertNotIn('private@example.org', json.dumps(report))
        class Broken(NoNER):
            def entities(self, text):
                raise RuntimeError('private@example.org')
        failed = evaluate_quality(corpus, Broken())
        self.assertFalse(failed['passed'])
        self.assertEqual(failed['metrics']['errors'], 1)
        self.assertNotIn('private@example.org', json.dumps(failed))

    def test_missing_annotation_is_not_silently_counted_as_success(self):
        corpus = {'version': 1, 'cases': [{'id': 'bad', 'text': 'Текст', 'sensitive': [{'value': 'Отсутствует'}]}]}
        with self.assertRaises(ValueError):
            evaluate_quality(corpus, NoNER())
