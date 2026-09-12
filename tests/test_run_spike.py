"""Unit tests for run_spike.py (Statistical Spike Runner for Prototypes)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUN_SPIKE = ROOT / "skills/spike/scripts/run_spike.py"

sys.path.insert(0, str(ROOT / "skills/spike/scripts"))
import run_spike


class TestRunSpike(unittest.TestCase):
    def test_calculate_percentile(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        # p50 of 1..10 is 5.5
        p50 = run_spike.calculate_percentile(data, 50)
        self.assertAlmostEqual(p50, 5.5, places=1)

        p90 = run_spike.calculate_percentile(data, 90)
        self.assertAlmostEqual(p90, 9.1, places=1)

        p99 = run_spike.calculate_percentile(data, 99)
        self.assertTrue(9.5 < p99 <= 10.0)

        # Edge cases
        self.assertEqual(run_spike.calculate_percentile([], 50), 0.0)
        self.assertEqual(run_spike.calculate_percentile([42.0], 50), 42.0)

    def test_run_benchmark_execution(self):
        # Run 20 iterations of a fast echo command
        metrics = run_spike.run_benchmark(
            cmd=f"{sys.executable} -c 'pass'",
            iterations=20,
            warmup=5,
            concurrency=2
        )
        self.assertEqual(metrics.total_runs, 20)
        self.assertEqual(metrics.successful_runs, 20)
        self.assertEqual(metrics.failed_runs, 0)
        self.assertEqual(metrics.error_rate_pct, 0.0)
        self.assertGreater(metrics.rps, 0.0)
        self.assertLessEqual(metrics.min_ms, metrics.p50_ms)
        self.assertLessEqual(metrics.p50_ms, metrics.p95_ms)
        self.assertLessEqual(metrics.p95_ms, metrics.p99_ms)
        self.assertLessEqual(metrics.p99_ms, metrics.max_ms)

    def test_format_markdown_table_pass(self):
        metrics = run_spike.BenchmarkMetrics(
            total_runs=100, successful_runs=100, failed_runs=0, error_rate_pct=0.0,
            total_duration_sec=0.5, rps=200.0, min_ms=1.0, p50_ms=2.0, p90_ms=3.0,
            p95_ms=4.0, p99_ms=5.0, max_ms=6.0, mean_ms=2.5, stddev_ms=0.5
        )
        table, passed = run_spike.format_markdown_table(
            metrics, expected_p99=10.0, expected_rps=100.0, expected_err_pct=1.0
        )
        self.assertTrue(passed)
        self.assertIn("✅ Met", table)
        self.assertIn("Throughput / RPS", table)
        self.assertIn("Latency (p99)", table)

    def test_format_markdown_table_fail(self):
        metrics = run_spike.BenchmarkMetrics(
            total_runs=100, successful_runs=90, failed_runs=10, error_rate_pct=10.0,
            total_duration_sec=1.0, rps=100.0, min_ms=1.0, p50_ms=12.0, p90_ms=18.0,
            p95_ms=22.0, p99_ms=25.0, max_ms=30.0, mean_ms=15.0, stddev_ms=3.0
        )
        # Expected p99 < 15.0ms, observed is 25.0ms
        table, passed = run_spike.format_markdown_table(
            metrics, expected_p99=15.0, expected_rps=50.0, expected_err_pct=1.0
        )
        self.assertFalse(passed)
        self.assertIn("❌ Breached", table)

    def test_cli_execution_json(self):
        cmd = [
            sys.executable,
            str(RUN_SPIKE),
            "--cmd", f"{sys.executable} -c 'pass'",
            "--iterations", "10",
            "--warmup", "2",
            "--json"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertIn("metrics", data)
        self.assertIn("markdown_table", data)
        self.assertTrue(data["passed"])
        self.assertEqual(data["metrics"]["total_runs"], 10)

    def test_duration_based_execution(self):
        """Duration-based runs terminate within expected timeframe and remove completed futures."""
        metrics = run_spike.run_benchmark(
            cmd=f"{sys.executable} -c 'pass'",
            iterations=0,
            warmup=0,
            concurrency=2,
            duration_sec=0.3,
        )
        self.assertGreater(metrics.total_runs, 0)
        self.assertLess(metrics.total_duration_sec, 2.0)
        self.assertEqual(metrics.failed_runs, 0)

    def test_duration_based_slow_command_does_not_timeout_or_crash(self):
        """Slow commands whose iteration latency exceeds polling intervals do not crash with TimeoutError."""
        metrics = run_spike.run_benchmark(
            cmd=f"{sys.executable} -c 'import time; time.sleep(0.15)'",
            iterations=0,
            warmup=0,
            concurrency=1,
            duration_sec=0.25,
        )
        self.assertGreaterEqual(metrics.total_runs, 1)
        self.assertEqual(metrics.failed_runs, 0)

    def test_command_timeout_expired_handled_gracefully(self):
        """Commands exceeding timeout_sec are marked as failures rather than hanging or crashing."""
        metrics = run_spike.run_benchmark(
            cmd=f"{sys.executable} -c 'import time; time.sleep(1.0)'",
            iterations=2,
            warmup=0,
            concurrency=1,
            timeout_sec=0.1
        )
        self.assertEqual(metrics.total_runs, 2)
        self.assertEqual(metrics.failed_runs, 2)
        self.assertEqual(metrics.successful_runs, 0)
        self.assertEqual(metrics.error_rate_pct, 100.0)

    def test_cli_timeout_argument(self):
        """CLI accepts --timeout flag and enforces it."""
        cmd = [
            sys.executable,
            str(RUN_SPIKE),
            "--cmd", f"{sys.executable} -c 'import time; time.sleep(0.5)'",
            "--iterations", "2",
            "--warmup", "0",
            "--timeout", "0.1",
            "--json"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(res.stdout)
        self.assertEqual(data["metrics"]["failed_runs"], 2)
        self.assertEqual(data["metrics"]["error_rate_pct"], 100.0)

    def test_timeout_terminates_child_process_group(self):
        """Commands that time out have their entire process group killed, not leaving orphaned children."""
        import tempfile
        import time

        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "child_finished.txt"
            script = (
                f"import subprocess, time\n"
                f"subprocess.Popen(['{sys.executable}', '-c', 'import time; time.sleep(0.4); open(\"{marker}\", \"w\").write(\"done\")'])\n"
                f"time.sleep(5)\n"
            )
            runner_file = Path(td) / "runner.py"
            runner_file.write_text(script)

            metrics = run_spike.run_benchmark(
                cmd=f"{sys.executable} {runner_file}",
                iterations=1,
                warmup=0,
                concurrency=1,
                timeout_sec=0.1,
            )
            self.assertEqual(metrics.total_runs, 1)
            self.assertEqual(metrics.failed_runs, 1)

            # Wait to ensure background child would have finished if it had survived
            time.sleep(0.5)
            self.assertFalse(marker.exists(), "Child process survived timeout and wrote marker file!")

    def test_calculate_percentile_clamping(self):
        """Negative percentiles or percentiles above 100 must be clamped to 0.0 and 100.0."""
        data = [10.0, 20.0, 30.0, 40.0, 50.0]
        # Negative percentile must clamp to 0 (min)
        self.assertEqual(run_spike.calculate_percentile(data, -50), 10.0)
        # Percentile above 100 must clamp to 100 (max)
        self.assertEqual(run_spike.calculate_percentile(data, 150), 50.0)

    def test_benchmark_concurrency_and_negative_input_clamping(self):
        """Negative iterations, negative warmup, and zero workers must be clamped safely without crashing."""
        metrics = run_spike.run_benchmark(
            cmd="python3 -c 'exit(0)'",
            iterations=-5,
            warmup=-2,
            concurrency=0,
            timeout_sec=5.0
        )
        self.assertEqual(metrics.total_runs, 0)
        self.assertEqual(metrics.error_rate_pct, 100.0)


if __name__ == "__main__":
    unittest.main()

