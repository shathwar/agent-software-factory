"""Negative controls for unsupported rubric success claims."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tests.evaluation.evaluate_design_rubric import DesignRubricEvaluator
from tests.evaluation.evaluate_evals_rubric import EvalsRubricEvaluator
from tests.evaluation.evaluate_review_rubric import ReviewRubricEvaluator
from tests.evaluation.review_benchmark import CASES
from tests.test_review_benchmark import report_for


class RubricAdversarialTests(unittest.TestCase):
    def test_empty_artifacts_never_pass_any_skill_rubric(self):
        from tests.evaluation.evaluate_debug_rubric import DebugRubricEvaluator
        from tests.evaluation.evaluate_ship_rubric import ShipRubricEvaluator
        from tests.evaluation.evaluate_simplify_rubric import SimplifyRubricEvaluator
        from tests.evaluation.evaluate_spike_rubric import SpikeRubricEvaluator
        from tests.evaluation.evaluate_tdd_rubric import TDDRubricEvaluator
        from tests.evaluation.evaluate_ux_rubric import UXRubricEvaluator
        reports = [DesignRubricEvaluator().evaluate_text(''), ReviewRubricEvaluator().evaluate_report({}),
                   EvalsRubricEvaluator().evaluate_eval_suite({}), DebugRubricEvaluator().evaluate_bugfix({}),
                   ShipRubricEvaluator().evaluate_delivery(''), SimplifyRubricEvaluator().evaluate_code(''),
                   SpikeRubricEvaluator().evaluate_report(''), TDDRubricEvaluator().evaluate_test_code(''),
                   UXRubricEvaluator().evaluate_component({})]
        for report in reports:
            with self.subTest(rubric=type(report).__name__):
                self.assertFalse(report.passed)

    def test_design_keyword_stuffing_and_negation_cannot_certify_quality(self):
        words = ('single source of truth atomic invariant lock idempotent race timeout retry fallback '
                 'migration index backfill feature flag metric rollback delete role non-goal')
        for text in (words, '\n'.join('We reject ' + word for word in words.split()), words * 100):
            report = DesignRubricEvaluator().evaluate_text(text)
            self.assertFalse(report.passed)
            self.assertNotEqual(report.status, 'PASS')
            self.assertEqual(report.to_dict()['assessment_kind'], 'keyword_lint')

    def test_review_requires_schema_and_actual_source_lines(self):
        evaluator = ReviewRubricEvaluator()
        for report in ({}, {'status': 'complete', 'findings': []}, {'findings': 'perfect review'}):
            self.assertFalse(evaluator.evaluate_report(report).passed)
        case = CASES['empty-average']
        report = report_for(case, case['buggy'])
        self.assertEqual(evaluator.evaluate_report(report).status, 'INCONCLUSIVE')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'subject.py').write_text(case['buggy'])
            self.assertTrue(evaluator.evaluate_report(report, repo_root=root).passed)
            for key, value in [('line', 'L1'), ('line', 'L999'), ('evidence', 'a plausible invented snippet'),
                               ('confidence', True), ('confidence', float('nan'))]:
                bad = deepcopy(report)
                bad['findings'][0][key] = value
                with self.subTest(key=key, value=value):
                    self.assertFalse(evaluator.evaluate_report(bad, repo_root=root).passed)

    def test_eval_boolean_claims_leakage_and_nonfinite_numbers_fail(self):
        good = {'evaluators': [{'name': 'schema', 'type': 'code'},
                              {'name': 'meaning', 'type': 'llm_judge', 'model': 'judge-2026-01-01',
                               'prompt': 'Give a justification and return Pass or Fail.'}],
                'splits': {'train': ['a'], 'dev': ['b'], 'test': ['c']},
                'calibration': {'tpr': .95, 'tnr': .95}}
        evaluator = EvalsRubricEvaluator()
        self.assertTrue(evaluator.evaluate_eval_suite(good).passed)
        bad_splits = [{}, {'train': ['a']}, {'test': ['c']}, {'train': ['a'], 'test': ['a']},
                      {'train': ['a'], 'dev': ['c'], 'test': ['c']},
                      {'train': ['a'], 'few_shot': ['c'], 'test': ['c']},
                      {'train': ['a', 'a'], 'test': ['c']}, {'train': 'abc', 'test': ['c']}]
        for split in bad_splits:
            bad = deepcopy(good)
            bad.update(splits=split, splits_isolated=True)
            self.assertFalse(evaluator.evaluate_eval_suite(bad).passed)
        for value in (float('inf'), float('nan'), -1, 1.01, True, '0.99', None):
            bad = deepcopy(good)
            bad['calibration']['tpr'] = value
            self.assertFalse(evaluator.evaluate_eval_suite(bad).passed)
        for model in ('', 'latest', 'judge-latest', 'judge-production'):
            bad = deepcopy(good)
            bad['evaluators'][1]['model'] = model
            self.assertFalse(evaluator.evaluate_eval_suite(bad).passed)
        bad = deepcopy(good)
        bad['production_monitoring'] = {'observed_pass_rate': .9, 'rogan_gladen_corrected': True}
        self.assertFalse(evaluator.evaluate_eval_suite(bad).passed)
