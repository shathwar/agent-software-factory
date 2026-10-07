"""Benchmark controls exercise actual seeded defects and grading failure modes."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tests.evaluation.review_benchmark import CASES, digest, provision, score, summarize


def report_for(case, source, *, findings=True):
    return {'reviewer': 'judge', 'status': 'complete', 'coverage': ['subject.py'],
            'questions': [], 'routing_notes': [], 'findings': [{
                'id': 'FINDING-001', 'severity': 'HIGH', 'category': case['stage'],
                'file': 'subject.py', 'line': f'L{case["line"]}', 'title': case['defect'],
                'problem': case['contract'], 'evidence': source.splitlines()[case['line'] - 1],
                'impact': 'Violates the documented consumer contract.',
                'recommendation': 'Implement the documented behavior and add a regression test.',
                'confidence': 1.0, 'fixability': 'autonomous'}] if findings else []}


def adjudicate(report, matches):
    return {'evaluator': 'held-out-human', 'report_sha256': digest(json.dumps(report, sort_keys=True, allow_nan=False)), 'matches': matches}


class ReviewBenchmarkTests(unittest.TestCase):
    def test_each_seed_fails_its_oracle_and_clean_control_passes(self):
        for name, case in CASES.items():
            with self.subTest(case=name):
                with self.assertRaises((AssertionError, ZeroDivisionError)):
                    exec(compile(case['buggy'] + '\n' + case['oracle'], name, 'exec'), {})
                exec(compile(case['clean'] + '\n' + case['oracle'], name, 'exec'), {})

    def test_full_control_suite_and_withheld_answers(self):
        results = []
        with tempfile.TemporaryDirectory() as tmp:
            for name, case in CASES.items():
                for variant in ('buggy', 'clean'):
                    case_id = f'{name}:{variant}'
                    root = Path(tmp) / case_id
                    provision(case_id, root)
                    self.assertEqual({p.name for p in root.iterdir()}, {'subject.py', 'CONTRACT.md'})
                    report = report_for(case, case[variant], findings=variant == 'buggy')
                    matches = {'FINDING-001': case['defect']} if variant == 'buggy' else {}
                    results.append(score(case_id, root, report, adjudicate(report, matches)))
        summary = summarize(results)
        self.assertEqual(summary['status'], 'passed')
        self.assertEqual(summary['stages']['SOLID']['status'], 'unrun')
        self.assertIsNone(summary['stages']['SOLID']['recall'])

    def test_misses_noise_duplicates_and_missing_runs(self):
        case = CASES['empty-average']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'case'
            provision('empty-average:buggy', root)
            clean = report_for(case, case['buggy'], findings=False)
            missed = score('empty-average:buggy', root, clean, adjudicate(clean, {}))
            self.assertEqual(missed['false_negatives'], 1)
            self.assertEqual(missed['recall'], 0)
            report = report_for(case, case['buggy'])
            duplicate = deepcopy(report['findings'][0])
            duplicate['id'] = 'FINDING-002'
            report['findings'].append(duplicate)
            result = score('empty-average:buggy', root, report, adjudicate(report, {f['id']: case['defect'] for f in report['findings']}))
            self.assertEqual((result['true_positives'], result['false_positives'], result['precision']), (1, 1, .5))
            noise = score('empty-average:buggy', root, report, adjudicate(report, {f['id']: None for f in report['findings']}))
            self.assertEqual((noise['false_positives'], noise['false_negatives']), (2, 1))
        self.assertEqual(summarize([])['status'], 'inconclusive')
        with self.assertRaises(ValueError):
            summarize([missed, missed])

    def test_source_and_report_binding_cannot_be_forged_by_prose(self):
        case = CASES['empty-average']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'case'
            provision('empty-average:buggy', root)
            report = report_for(case, case['buggy'])
            decision = adjudicate(report, {'FINDING-001': case['defect']})
            for key, value in [('line', 'L99'), ('evidence', 'invented code'), ('file', '../subject.py')]:
                bad = deepcopy(report)
                bad['findings'][0][key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    score('empty-average:buggy', root, bad, adjudicate(bad, decision['matches']))
            report['findings'][0]['problem'] = 'changed after adjudication'
            with self.assertRaises(ValueError):
                score('empty-average:buggy', root, report, decision)
            (root / 'subject.py').write_text(case['clean'])
            with self.assertRaises(ValueError):
                score('empty-average:buggy', root, report, decision)
