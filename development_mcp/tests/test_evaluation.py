import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from development_mcp.eval_dataset import digest, freeze, read_dataset
from development_mcp.evaluation import Processor, compare
from .sample_bundle import sample_bundle, token


def local_processor(text, options):
    print(text)  # Trusted processors' accidental prints must not leak into reports.
    if options.get('raise'):
        raise RuntimeError(text)
    return {'score': options.get('score', 4)}


def example_dataset():
    example = {'id': token('example'), 'case_id': token('case'), 'record_id': token('record'),
               'table': 'core_motivationletter', 'field': 'letter_text',
               'text': 'Хочу учиться — и работать.', 'expected': {'word_count': 4}}
    import hashlib
    example['text_sha256'] = hashlib.sha256(example['text'].encode()).hexdigest()
    body = {'format': 'putevka.text-eval-dataset', 'version': 1, 'sources': [], 'examples': [example]}
    return {**body, 'sha256': digest(body)}


class EvaluationTests(unittest.TestCase):
    def test_freeze_is_stable_deduplicates_and_links_references(self):
        main, nto = sample_bundle('main'), sample_bundle('nto')
        fields = ['core_motivationletter.letter_text']
        refs = ['core_motivationletter.admin_score=score', 'core_motivationletterrubricreview.total_score=rubric.total']
        first = freeze([main, nto, main], fields, refs)
        second = freeze([nto, main], fields, refs)
        self.assertEqual(first, second)
        self.assertEqual(first['examples'][0]['expected'], {'score': 4, 'rubric.total': 7})
        transcript = freeze([main], ['review_by_tutor_interview.transcript'], ['review_by_tutor_interviewresult.interviewer_score=score'])
        self.assertEqual(transcript['examples'][0]['expected'], {'score': 5})

    def test_dataset_rejects_changes_in_frozen_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dataset.json'
            data = example_dataset()
            path.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(read_dataset(path), data)
            data['examples'][0]['text'] = 'CHANGED'
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(ValueError):
                read_dataset(path)

    def test_paired_metrics_and_report_do_not_contain_texts_or_outputs(self):
        base = Path(__file__).parents[1] / 'eval_examples'
        data = example_dataset()
        report, outputs = compare(data, Processor(base / 'baseline.json'), Processor(base / 'candidate.json'))
        self.assertEqual(report['changed_samples'], 1)
        self.assertEqual(report['variants']['baseline']['metrics']['numeric_mae'], 1)
        self.assertEqual(report['variants']['candidate']['metrics']['numeric_mae'], 0)
        self.assertNotIn(data['examples'][0]['text'], json.dumps(report, ensure_ascii=False))
        self.assertEqual(outputs, {})

    def test_python_processors_fail_safely_and_optional_outputs_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / 'a.json', Path(directory) / 'b.json']
            for path, name, fail in zip(paths, ['baseline', 'candidate'], [False, True]):
                path.write_text(json.dumps({'name': name, 'provider': 'python', 'callable': __name__ + ':local_processor', 'options': {'raise': fail}}), encoding='utf-8')
            data = example_dataset()
            data['examples'][0]['expected'] = {'score': 4}
            data['sha256'] = digest({key: value for key, value in data.items() if key != 'sha256'})
            stream = io.StringIO()
            from contextlib import redirect_stdout
            with redirect_stdout(stream):
                report, outputs = compare(data, Processor(paths[0]), Processor(paths[1]), save_outputs=True)
            self.assertEqual(stream.getvalue(), '')
            self.assertEqual(report['variants']['candidate']['metrics']['errors'], 1)
            self.assertNotIn(data['examples'][0]['text'], json.dumps(report, ensure_ascii=False))
            self.assertEqual(outputs['baseline'][0]['output'], {'score': 4})

    def test_openai_uses_only_text_and_prompt_never_reference_answers(self):
        response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='{"score":4}'))],
                                   usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4), model='chosen-model-snapshot')
        client = Mock()
        client.with_options.return_value = client
        client.chat.completions.create.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            prompt = Path(directory) / 'prompt.md'
            prompt.write_text('Верни JSON с ключом score.', encoding='utf-8')
            path.write_text(json.dumps({'name': 'prompt', 'provider': 'openai', 'model': 'chosen-model', 'prompt_file': 'prompt.md'}), encoding='utf-8')
            processor = Processor(path, client=client)
            value, usage = processor.run('Очищенный текст.')
            args = client.chat.completions.create.call_args.kwargs
            self.assertFalse(args['store'])
            self.assertEqual(args['messages'][1], {'role': 'user', 'content': 'Очищенный текст.'})
            self.assertEqual(usage['input_tokens'], 10)
            self.assertEqual(value, '{"score":4}')
            old = processor.fingerprint
            prompt.write_text('Другой промпт.', encoding='utf-8')
            self.assertNotEqual(Processor(path, client=client).fingerprint, old)

    def test_missing_expected_null_is_not_counted_as_an_exact_match(self):
        data = example_dataset()
        data['examples'][0]['expected'] = {'missing': None}
        data['sha256'] = digest({key: value for key, value in data.items() if key != 'sha256'})
        base = Path(__file__).parents[1] / 'eval_examples'
        report, _ = compare(data, Processor(base / 'baseline.json'), Processor(base / 'candidate.json'))
        self.assertEqual(report['variants']['candidate']['metrics']['exact_fields'], 0)
        self.assertEqual(report['variants']['candidate']['metrics']['reference_coverage'], 0)

    def test_does_not_freeze_unredacted_or_ambiguous_cases(self):
        main = sample_bundle('main')
        main['automatically_redacted'] = False
        with self.assertRaises(Exception):
            freeze([main], ['core_motivationletter.letter_text'])
        main = sample_bundle('main')
        altered = copy.deepcopy(main)
        next(r for r in altered['records'] if r['table'] == 'core_motivationletter')['fields']['letter_text'] = 'Другая версия'
        with self.assertRaises(ValueError):
            freeze([main, altered], ['core_motivationletter.letter_text'])
