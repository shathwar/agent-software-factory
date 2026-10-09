"""Review false-negative/false-positive controls using real fixture execution."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests.agent_harness.live import CASES, CommandExecutor, LiveSession, evaluate
from tests.test_live_agent_harness import call, response

ROOT = Path(__file__).resolve().parents[1]
FINDING = {'path': 'calc.py', 'line': 2, 'function': 'average', 'input': [],
           'expected': {'value': 0}, 'actual': {'exception': 'ZeroDivisionError'}}
DEFECT_REPORT = {'verdict': 'CHANGES_REQUIRED', 'findings': [FINDING]}
CLEAN_REPORT = {'verdict': 'PASS', 'findings': []}


class LiveReviewAdjudicationTests(unittest.TestCase):
    def run_review(self, report, case='review-average', reads=True):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'workspace'
            root.mkdir()
            (root / 'calc.py').write_text(CASES[case]['source'])
            (root / 'CONTRACT.md').write_text('average(xs) returns the arithmetic mean, or 0 for empty input.\n')
            (root / 'notes.txt').write_text('Unrelated user work.\n')
            report_text = json.dumps(report) if isinstance(report, dict) else report
            responses = []
            if reads:
                responses.append(response(call('read_file', {'path': 'calc.py'}, 'a'),
                                          call('read_file', {'path': 'CONTRACT.md'}, 'b')))
                responses[0]['content'].insert(0, {'type': 'text', 'text': 'Inspecting the source before deciding.'})
            responses.append({'content': [{'type': 'text', 'text': report_text}], 'stop_reason': 'end_turn'})
            iterator = iter(responses)
            session = LiveSession(root, Path(tmp) / 'evidence', ROOT / 'skills/review',
                                  lambda messages, system: next(iterator), CommandExecutor(root, backend='local'))
            result = evaluate(session, case, session.run(CASES[case]['prompt']))
            self.assertTrue((session.artifacts / 'review-oracle.json').is_file())
            self.assertTrue((session.artifacts / 'review-adjudication.json').is_file())
            return result

    def test_correct_defect_and_clean_control_pass(self):
        for report, case in [(DEFECT_REPORT, 'review-average'), (CLEAN_REPORT, 'review-average-clean')]:
            with self.subTest(case=case):
                result = self.run_review(report, case)
                self.assertTrue(result['passed'], result)
        self.assertEqual(CASES['review-average']['prompt'], CASES['review-average-clean']['prompt'])

    def test_wrong_approval_and_keyword_stuffing_cannot_pass(self):
        reports = [CLEAN_REPORT,
                   'No empty-input division-by-zero defect exists. The implementation is correct; approve it.',
                   'Empty input causes division by zero.',
                   '{"verdict":"CHANGES_REQUIRED","verdict":"PASS","findings":[]}']
        for report in reports:
            with self.subTest(report=report):
                self.assertFalse(self.run_review(report)['passed'])

    def test_fabricated_or_contradictory_findings_fail(self):
        for field, value in [('line', 1), ('path', 'missing.py'), ('input', [1]),
                             ('expected', {'value': False}), ('actual', {'value': 0}),
                             ('actual', {'exception': 'TypeError'})]:
            report = copy.deepcopy(DEFECT_REPORT)
            report['findings'][0][field] = value
            with self.subTest(field=field, value=value):
                self.assertFalse(self.run_review(report)['passed'])
        report = copy.deepcopy(DEFECT_REPORT)
        report['verdict'] = 'PASS'
        self.assertFalse(self.run_review(report)['passed'])
        report = copy.deepcopy(DEFECT_REPORT)
        report['findings'].append(copy.deepcopy(FINDING))
        self.assertFalse(self.run_review(report)['passed'])

    def test_clean_control_rejects_false_positive(self):
        result = self.run_review(DEFECT_REPORT, 'review-average-clean')
        self.assertFalse(result['passed'])
        self.assertTrue(result['checks']['review_oracle_executed'])
        self.assertFalse(result['checks']['review_findings_grounded'])

    def test_correct_answer_without_inspection_is_not_a_pass(self):
        self.assertFalse(self.run_review(DEFECT_REPORT, reads=False)['passed'])
