"""Comprehensive tests for AgentFlow Evaluation & Regression Benchmark Harness."""

import json
from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.evaluation import (
    BenchmarkDimension,
    EvaluationReport,
    EvaluationRunner,
    STANDARD_SCENARIOS,
    format_terminal_report,
    run_all_benchmarks,
    scenario_false_approvals,
    scenario_false_blocks,
    scenario_policy_enforcement,
    scenario_recovery_reconciliation,
)


class TestEvaluationHarness(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_individual_policy_scenario(self):
        """Test individual policy enforcement benchmark scenario."""
        res = scenario_policy_enforcement(self.repo_root)
        self.assertTrue(res.passed, f"Scenario failed: {res.error}")
        self.assertEqual(res.dimension, BenchmarkDimension.POLICY_ENFORCEMENT.value)
        self.assertGreater(res.metrics["checks_enforced"], 0)

    def test_individual_false_approvals_scenario(self):
        """Test false approval deflection (target 0.0% false approvals)."""
        res = scenario_false_approvals(self.repo_root)
        self.assertTrue(res.passed, f"Scenario failed: {res.error}")
        self.assertEqual(res.metrics["false_approval_rate"], 0.0)

    def test_individual_false_blocks_scenario(self):
        """Test false block prevention (target 0.0% false blocks)."""
        res = scenario_false_blocks(self.repo_root)
        self.assertTrue(res.passed, f"Scenario failed: {res.error}")
        self.assertEqual(res.metrics["false_block_rate"], 0.0)

    def test_individual_recovery_scenario(self):
        """Test deterministic crash recovery reconciliation."""
        res = scenario_recovery_reconciliation(self.repo_root)
        self.assertTrue(res.passed, f"Scenario failed: {res.error}")
        self.assertEqual(res.metrics["recovery_success"], 1.0)

    def test_evaluation_runner_full_suite(self):
        """Test running the full standard benchmark suite across isolated sandboxes."""
        runner = EvaluationRunner()
        report = runner.run_suite()

        self.assertEqual(report.total_scenarios, len(STANDARD_SCENARIOS))
        self.assertEqual(report.failed_scenarios, 0, f"Some scenarios failed: {[s.name for s in report.scenario_results if not s.passed]}")
        self.assertEqual(report.pass_rate_pct, 100.0)

        # Core invariant guarantees
        self.assertEqual(report.false_approval_rate, 0.0)
        self.assertEqual(report.false_block_rate, 0.0)
        self.assertEqual(report.policy_enforcement_rate, 1.0)
        self.assertEqual(report.convergence_detection_rate, 1.0)
        self.assertEqual(report.recovery_success_rate, 1.0)
        self.assertEqual(report.race_condition_resilience, 1.0)
        self.assertEqual(report.autonomy_completion_rate, 1.0)

        # Latency statistics present
        self.assertIn("p50_ms", report.latency_percentiles_ms)
        self.assertIn("p95_ms", report.latency_percentiles_ms)

        # Formatter produces expected scorecard
        card = format_terminal_report(report)
        self.assertIn("AGENTFLOW SYSTEM BENCHMARK & EVALUATION REPORT", card)
        self.assertIn("Policy Enforcement Accuracy", card)
        self.assertIn("✅ PASS", card)

    def test_dimension_filtering(self):
        """Test filtering benchmark scenarios by dimension keyword."""
        runner = EvaluationRunner()
        report = runner.run_suite(dimension_filter="policy")
        self.assertEqual(report.total_scenarios, 1)
        self.assertEqual(report.scenario_results[0].dimension, BenchmarkDimension.POLICY_ENFORCEMENT.value)

    def test_cli_benchmark_integration(self):
        """Test agentflow benchmark CLI command."""
        from ship.cli import main as cli_main

        # 1. Text format
        exit_code = cli_main(["benchmark", "--suite", "policy"])
        self.assertEqual(exit_code, 0)

        # 2. JSON format with output file
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_file = f.name

        try:
            exit_code = cli_main(["benchmark", "--suite", "policy", "--json", "--output", out_file])
            self.assertEqual(exit_code, 0)
            data = json.loads(Path(out_file).read_text(encoding="utf-8"))
            self.assertEqual(data["passed_scenarios"], 1)
            self.assertEqual(data["summary_rates"]["policy_enforcement_rate"], 1.0)
        finally:
            if Path(out_file).exists():
                Path(out_file).unlink()


if __name__ == "__main__":
    unittest.main()
