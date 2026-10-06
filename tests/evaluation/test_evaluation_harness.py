"""Comprehensive tests for AgentFlow Evaluation & Regression Benchmark Harness."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr, redirect_stdout
import io

from ship.lifecycle.evaluation import (
    BenchmarkDimension,
    EvaluationRunner,
    ScenarioResult,
    STANDARD_SCENARIOS,
    format_terminal_report,
    scenario_false_approvals,
    scenario_false_blocks,
    scenario_policy_enforcement,
    scenario_recovery_reconciliation,
)


class TestEvaluationHarness(unittest.TestCase):
    def test_failed_recovery_is_not_reported_as_success(self):
        def scenario(root):
            return ScenarioResult('recovery', 'Recovery', 'recovery', False, 1,
                                  metrics={'recovery_success': 0.0})
        report = EvaluationRunner([scenario]).run_suite()
        self.assertEqual(report.recovery_success_rate, 0.0)
        self.assertEqual(report.dimension_statuses['recovery'], 'failed')
        self.assertEqual(report.status, 'failed')

    def test_failed_iterations_are_included_in_rates(self):
        results = iter([True, False])
        def scenario(root):
            passed = next(results)
            return ScenarioResult('recovery', 'Recovery', 'recovery', passed, 1,
                                  metrics={'recovery_success': float(passed)})
        report = EvaluationRunner([scenario]).run_suite(iterations=2)
        self.assertEqual(report.recovery_success_rate, 0.5)
        self.assertEqual(report.dimension_statuses['recovery'], 'failed')

    def test_policy_rate_counts_failed_iterations(self):
        results = iter([True, False])
        def scenario(root):
            return ScenarioResult('policy', 'Policy', 'policy_enforcement', next(results), 1)
        report = EvaluationRunner([scenario]).run_suite(iterations=2)
        self.assertEqual(report.policy_enforcement_rate, 0.5)

    def test_unrun_dimensions_have_no_measurement(self):
        report = EvaluationRunner().run_suite(dimension_filter='policy')
        self.assertIsNone(report.recovery_success_rate)
        self.assertEqual(report.dimension_statuses['recovery'], 'unrun')
        self.assertIsNone(report.to_dict()['summary_rates']['recovery_success_rate'])
        self.assertEqual(report.latency_percentiles_ms, {})
        self.assertIn('UNRUN', format_terminal_report(report))
        self.assertEqual(report.status, 'passed')

    def test_missing_or_invalid_metrics_are_inconclusive(self):
        for metrics in ({}, {'recovery_success': float('nan')},
                        {'recovery_success': 2}, {'recovery_success': 'yes'}):
            with self.subTest(metrics=metrics):
                def scenario(root):
                    return ScenarioResult('recovery', 'Recovery', 'recovery', True, 1, metrics=metrics)
                report = EvaluationRunner([scenario]).run_suite()
                self.assertIsNone(report.recovery_success_rate)
                self.assertEqual(report.dimension_statuses['recovery'], 'inconclusive')
                self.assertEqual(report.status, 'inconclusive')
                self.assertIn('INCONCLUSIVE', format_terminal_report(report))

    def test_missing_failed_metric_does_not_create_a_rate(self):
        results = iter([True, False])
        def scenario(root):
            passed = next(results)
            return ScenarioResult('recovery', 'Recovery', 'recovery', passed, 1,
                                  metrics={'recovery_success': 1.0} if passed else {})
        report = EvaluationRunner([scenario]).run_suite(iterations=2)
        self.assertIsNone(report.recovery_success_rate)
        self.assertEqual(report.dimension_statuses['recovery'], 'failed')

    def test_empty_suite_and_invalid_iterations(self):
        report = EvaluationRunner([]).run_suite()
        self.assertEqual(report.total_scenarios, 0)
        self.assertEqual(report.status, 'unrun')
        self.assertIsNone(report.pass_rate_pct)
        self.assertNotIn('✅ PASS', format_terminal_report(report))
        for iterations in (0, -1):
            with self.assertRaises(ValueError):
                EvaluationRunner().run_suite(iterations=iterations)
        with self.assertRaises(ValueError):
            EvaluationRunner().run_suite(dimension_filter='typo')

    def test_false_approval_rate_includes_failed_run(self):
        results = iter([True, False])
        def scenario(root):
            passed = next(results)
            return ScenarioResult('approval', 'Approval', 'false_approvals', passed, 1,
                                  metrics={'false_approval_rate': 0.0 if passed else 1.0})
        report = EvaluationRunner([scenario]).run_suite(iterations=2)
        self.assertEqual(report.false_approval_rate, 0.5)
        self.assertEqual(report.dimension_statuses['false_approvals'], 'failed')

    def test_exception_preserves_registered_dimension(self):
        def scenario_recovery_reconciliation(root):
            raise RuntimeError('recovery crashed')
        report = EvaluationRunner([scenario_recovery_reconciliation]).run_suite()
        self.assertEqual(report.dimension_statuses['recovery'], 'failed')
        self.assertIsNone(report.recovery_success_rate)
        self.assertEqual(report.scenario_results[0].error, 'recovery crashed')

    def test_measured_threshold_failure_overrides_scenario_pass(self):
        def scenario(root):
            return ScenarioResult('verification', 'Verification', 'verification_quality', True, 1,
                                  metrics={'grounding_accuracy': 0.5})
        report = EvaluationRunner([scenario]).run_suite()
        self.assertEqual(report.status, 'failed')
        self.assertEqual(report.dimension_statuses['verification_quality'], 'failed')

    def test_latency_averages_all_iteration_summaries(self):
        values = iter([10.0, 30.0])
        def scenario(root):
            value = next(values)
            return ScenarioResult('latency', 'Latency', 'latency', True, 1,
                                  metrics={key: value for key in
                                           ('min_ms', 'p50_ms', 'p90_ms', 'p95_ms', 'p99_ms', 'max_ms', 'mean_ms')})
        report = EvaluationRunner([scenario]).run_suite(iterations=2)
        self.assertEqual(report.latency_percentiles_ms['p95_ms'], 20.0)
        self.assertEqual(report.dimension_statuses['latency'], 'passed')

    def test_cli_rejects_invalid_or_nonpassing_suites(self):
        from ship.cli import main as cli_main
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            for args in (['--suite', 'typo'], ['--iterations', '0'], ['--iterations', '-1']):
                with self.assertRaises(SystemExit) as error:
                    cli_main(['benchmark'] + args)
                self.assertEqual(error.exception.code, 2)
            for scenarios in ([], [lambda root: ScenarioResult('recovery', 'Recovery', 'recovery', True, 1)],
                              [lambda root: ScenarioResult('recovery', 'Recovery', 'recovery', False, 1)]):
                report = EvaluationRunner(scenarios).run_suite()
                with patch.object(EvaluationRunner, 'run_suite', return_value=report):
                    self.assertEqual(cli_main(['benchmark', '--json']), 1)

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
