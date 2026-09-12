#!/usr/bin/env python3
"""
run_spike.py — Automated Statistical Benchmark Harness for Prototype Spikes
Zero external dependencies (Python 3.10+ standard library).

Measures:
- Latency percentiles: p50, p90, p95, p99, Min, Max, Mean, StdDev
- Throughput: Requests / operations per second (RPS)
- Reliability: Error count and error percentage
- Output: Official Markdown table matching spike/SKILL.md contract or JSON
"""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time


@dataclass
class BenchmarkMetrics:
    total_runs: int
    successful_runs: int
    failed_runs: int
    error_rate_pct: float
    total_duration_sec: float
    rps: float
    min_ms: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    mean_ms: float
    stddev_ms: float


def run_single_iteration(cmd: str, cwd: Path | None = None, timeout_sec: float | None = 60.0) -> tuple[float, bool]:
    """Execute a single run of the command in an isolated process group and measure elapsed time in milliseconds."""
    start = time.perf_counter()
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        proc.communicate(timeout=timeout_sec)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return elapsed_ms, proc.returncode == 0
    except subprocess.TimeoutExpired:
        if proc is not None:
            if hasattr(os, "killpg"):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except Exception:
                    pass
            else:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                proc.communicate(timeout=0.5)
            except Exception:
                pass
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return elapsed_ms, False
    except Exception:
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return elapsed_ms, False


def calculate_percentile(sorted_data: list[float], percentile: float) -> float:
    """Calculate percentile from sorted data using linear interpolation."""
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return sorted_data[0]
    idx = (len(sorted_data) - 1) * (percentile / 100.0)
    low = int(idx)
    high = min(low + 1, len(sorted_data) - 1)
    weight = idx - low
    return sorted_data[low] * (1.0 - weight) + sorted_data[high] * weight


def run_benchmark(
    cmd: str,
    iterations: int,
    warmup: int,
    concurrency: int,
    duration_sec: float | None = None,
    cwd: Path | None = None,
    timeout_sec: float | None = 60.0
) -> BenchmarkMetrics:
    """Run warmup and full benchmark suite."""
    # 1. Warmup Phase
    if warmup > 0:
        if concurrency > 1:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                list(executor.map(lambda _: run_single_iteration(cmd, cwd, timeout_sec), range(warmup)))
        else:
            for _ in range(warmup):
                run_single_iteration(cmd, cwd, timeout_sec)

    # 2. Measurement Phase
    latencies: list[float] = []
    successes = 0
    failures = 0
    start_total = time.perf_counter()

    if duration_sec and duration_sec > 0:
        # Duration-based run
        deadline = start_total + duration_sec
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures: set = set()
            while time.perf_counter() < deadline or futures:
                # Keep worker queue saturated while before deadline
                while len(futures) < concurrency and time.perf_counter() < deadline:
                    futures.add(executor.submit(run_single_iteration, cmd, cwd, timeout_sec))
                if not futures:
                    break
                # Wait for at least one future to complete or timeout
                done, not_done = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                futures = set(not_done)
                for f in done:
                    try:
                        elapsed_ms, ok = f.result()
                        latencies.append(elapsed_ms)
                        if ok:
                            successes += 1
                        else:
                            failures += 1
                    except Exception:
                        failures += 1
    else:
        # Iteration-based run
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(run_single_iteration, cmd, cwd, timeout_sec) for _ in range(iterations)]
            for f in as_completed(futures):
                try:
                    elapsed_ms, ok = f.result()
                    latencies.append(elapsed_ms)
                    if ok:
                        successes += 1
                    else:
                        failures += 1
                except Exception:
                    failures += 1

    total_duration_sec = time.perf_counter() - start_total
    total_runs = len(latencies)
    if total_runs == 0:
        return BenchmarkMetrics(
            total_runs=0, successful_runs=0, failed_runs=0, error_rate_pct=100.0,
            total_duration_sec=total_duration_sec, rps=0.0, min_ms=0.0, p50_ms=0.0,
            p90_ms=0.0, p95_ms=0.0, p99_ms=0.0, max_ms=0.0, mean_ms=0.0, stddev_ms=0.0
        )

    latencies.sort()
    rps = total_runs / total_duration_sec if total_duration_sec > 0 else 0.0
    err_pct = (failures / total_runs) * 100.0

    return BenchmarkMetrics(
        total_runs=total_runs,
        successful_runs=successes,
        failed_runs=failures,
        error_rate_pct=round(err_pct, 2),
        total_duration_sec=round(total_duration_sec, 3),
        rps=round(rps, 1),
        min_ms=round(latencies[0], 2),
        p50_ms=round(calculate_percentile(latencies, 50), 2),
        p90_ms=round(calculate_percentile(latencies, 90), 2),
        p95_ms=round(calculate_percentile(latencies, 95), 2),
        p99_ms=round(calculate_percentile(latencies, 99), 2),
        max_ms=round(latencies[-1], 2),
        mean_ms=round(statistics.mean(latencies), 2),
        stddev_ms=round(statistics.stdev(latencies) if len(latencies) > 1 else 0.0, 2)
    )


def format_markdown_table(
    metrics: BenchmarkMetrics,
    expected_p99: float | None = None,
    expected_rps: float | None = None,
    expected_err_pct: float | None = None
) -> tuple[str, bool]:
    """Formats metrics as markdown and returns (table_string, all_thresholds_passed)."""
    all_passed = True
    rows = []

    # RPS check
    rps_expected_str = f"> {expected_rps:,.0f}" if expected_rps is not None else "-"
    if expected_rps is not None:
        rps_status = "✅ Met" if metrics.rps >= expected_rps else "❌ Breached"
        if metrics.rps < expected_rps:
            all_passed = False
    else:
        rps_status = "ℹ️ Recorded"
    rows.append(f"| Throughput / RPS | {rps_expected_str} | {metrics.rps:,.1f} | {rps_status} |")

    # p50
    rows.append(f"| Latency (p50) | - | {metrics.p50_ms:.2f}ms | ℹ️ Recorded |")

    # p95
    rows.append(f"| Latency (p95) | - | {metrics.p95_ms:.2f}ms | ℹ️ Recorded |")

    # p99 check
    p99_expected_str = f"< {expected_p99:.1f}ms" if expected_p99 is not None else "-"
    if expected_p99 is not None:
        p99_status = "✅ Met" if metrics.p99_ms <= expected_p99 else "❌ Breached"
        if metrics.p99_ms > expected_p99:
            all_passed = False
    else:
        p99_status = "ℹ️ Recorded"
    rows.append(f"| Latency (p99) | {p99_expected_str} | {metrics.p99_ms:.2f}ms | {p99_status} |")

    # Max Latency
    rows.append(f"| Max Latency | - | {metrics.max_ms:.2f}ms | ℹ️ Recorded |")

    # Error Rate check
    err_expected_str = f"< {expected_err_pct:.1f}%" if expected_err_pct is not None else "< 1.0%"
    threshold = expected_err_pct if expected_err_pct is not None else 1.0
    err_status = "✅ Met" if metrics.error_rate_pct <= threshold else "❌ Breached"
    if metrics.error_rate_pct > threshold:
        all_passed = False
    rows.append(f"| Error Rate | {err_expected_str} | {metrics.error_rate_pct:.2f}% | {err_status} |")

    lines = [
        "### 📊 Empirical Results",
        f"*Conducted {metrics.total_runs} total runs over {metrics.total_duration_sec:.2f}s*",
        "",
        "| Metric / Condition | Expected | Observed | Status |",
        "|---|---|---|---|",
        *rows,
        "",
        f"*(Mean: {metrics.mean_ms:.2f}ms, StdDev: {metrics.stddev_ms:.2f}ms, Min: {metrics.min_ms:.2f}ms)*"
    ]
    return "\n".join(lines), all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Automated Statistical Spike Runner for Prototypes")
    parser.add_argument("--cmd", required=True, help="Command line string to benchmark")
    parser.add_argument("--iterations", type=int, default=100, help="Number of measurement runs (default: 100)")
    parser.add_argument("--warmup", type=int, default=10, help="Number of warmup runs (default: 10)")
    parser.add_argument("--workers", "--concurrency", dest="concurrency", type=int, default=1, help="Concurrent worker threads (default: 1)")
    parser.add_argument("--duration", type=float, help="Run for duration in seconds instead of fixed iterations")
    parser.add_argument("--cwd", help="Working directory to run command in (defaults to current dir)")
    parser.add_argument("--expected-p99", type=float, help="Expected p99 latency threshold in ms")
    parser.add_argument("--expected-rps", type=float, help="Expected minimum throughput (RPS)")
    parser.add_argument("--expected-err", type=float, help="Expected maximum error rate percentage")
    parser.add_argument("--timeout", type=float, default=60.0, help="Timeout per iteration in seconds (default: 60.0)")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    args = parser.parse_args()

    cwd = Path(args.cwd).resolve() if args.cwd else None

    metrics = run_benchmark(
        cmd=args.cmd,
        iterations=args.iterations,
        warmup=args.warmup,
        concurrency=args.concurrency,
        duration_sec=args.duration,
        cwd=cwd,
        timeout_sec=args.timeout
    )

    if args.json:
        table_str, passed = format_markdown_table(metrics, args.expected_p99, args.expected_rps, args.expected_err)
        out = {
            "metrics": asdict(metrics),
            "passed": passed,
            "markdown_table": table_str
        }
        print(json.dumps(out, indent=2))
        return 0 if passed else 1

    table_str, passed = format_markdown_table(metrics, args.expected_p99, args.expected_rps, args.expected_err)
    print("")
    print(table_str)
    print("")
    if passed:
        print("✅ Verdict: Pass. All empirical thresholds met.")
        return 0
    else:
        print("❌ Verdict: Fail. One or more empirical thresholds were breached.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
