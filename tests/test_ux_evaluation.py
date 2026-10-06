"""Unit test for UX pipeline evaluation suite and benchmark fixtures."""

from __future__ import annotations

from pathlib import Path
import unittest

from tests.evaluation.evaluate_ux_pipeline import UXPipelineEvaluator

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests/fixtures/ux"


class TestUXEvaluation(unittest.TestCase):
    def setUp(self):
        self.assertTrue(FIXTURES_DIR.is_dir(), f"Missing fixtures directory at {FIXTURES_DIR}")
        self.evaluator = UXPipelineEvaluator(FIXTURES_DIR)

    def test_all_fixtures_present(self):
        expected_fixtures = [
            "01-good-dashboard.tsx",
            "02-bad-form.tsx",
            "03-ai-slop-landing-page.tsx",
            "04-accessibility-broken.tsx",
            "05-mobile-broken.tsx",
            "06-design-system-inconsistent.tsx",
            "07-complex-data-table.tsx",
            "08-destructive-workflow.tsx",
        ]
        for f in expected_fixtures:
            path = FIXTURES_DIR / f
            self.assertTrue(path.is_file(), f"Missing fixture file: {f}")

    def test_pipeline_evaluation_runs_and_produces_valid_metrics(self):
        data = self.evaluator.run_benchmark()
        summary = data["summary"]

        configs = ["UX Only", "UX + Impeccable", "UX + Hallmark", "UX + Both"]
        for cfg in configs:
            self.assertIn(cfg, summary)
            stats = summary[cfg]
            self.assertEqual(stats["fixtures_evaluated"], 8)
            self.assertGreater(stats["total_issues_found"], 0)
            self.assertEqual(stats["regressions"], 0)
            self.assertEqual(stats["false_positives"], 0)

        # Full pipeline must find strictly more actionable issues than UX Only
        ux_actionable = summary["UX Only"]["actionable_issues"]
        both_actionable = summary["UX + Both"]["actionable_issues"]
        self.assertGreater(both_actionable, ux_actionable)


if __name__ == "__main__":
    unittest.main()
