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
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import shlex
import signal
import statistics
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Sequence


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
    measurement_scope: str = "subprocess_wall_time"
    throughput_unit: str = "command_runs_per_second"


def run_single_iteration(cmd: str | Sequence[str], cwd: Path | None = None, timeout_sec: float | None = 60.0) -> tuple[float, bool]:
    """Execute a single run of the command in an isolated process group and measure elapsed time in milliseconds."""
    start = time.perf_counter()
    proc = None
    try:
        use_shell = False
        if isinstance(cmd, str):
            shell_chars = {"|", "&", ";", ">", "<", "`", "$"}
            if any(sc in cmd for sc in shell_chars):
                args: str | list[str] = cmd
                use_shell = True
            else:
                try:
                    args = shlex.split(cmd)
                except Exception:
                    args = cmd
                    use_shell = True
        else:
            args = list(cmd)

        proc = subprocess.Popen(
            args,
            shell=use_shell,
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
            if sys.platform == "win32":
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            elif hasattr(os, "killpg"):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
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
    clamped_percentile = max(0.0, min(100.0, float(percentile)))
    idx = (len(sorted_data) - 1) * (clamped_percentile / 100.0)
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
    concurrency = max(1, concurrency)
    iterations = max(0, iterations)
    warmup = max(0, warmup)

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
        # Iteration-based run with bounded in-flight window to prevent OOM
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures: set = set()
            submitted = 0
            window_size = max(concurrency * 4, 32)
            while submitted < iterations and len(futures) < window_size:
                futures.add(executor.submit(run_single_iteration, cmd, cwd, timeout_sec))
                submitted += 1

            while futures:
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

                while submitted < iterations and len(futures) < window_size:
                    futures.add(executor.submit(run_single_iteration, cmd, cwd, timeout_sec))
                    submitted += 1

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
    rows.append(f"| Command runs / second | {rps_expected_str} | {metrics.rps:,.1f} | {rps_status} |")

    # p50
    rows.append(f"| Command duration (p50) | - | {metrics.p50_ms:.2f}ms | ℹ️ Recorded |")

    # p95
    rows.append(f"| Command duration (p95) | - | {metrics.p95_ms:.2f}ms | ℹ️ Recorded |")

    # p99 check
    p99_expected_str = f"< {expected_p99:.1f}ms" if expected_p99 is not None else "-"
    if expected_p99 is not None:
        p99_status = "✅ Met" if metrics.p99_ms <= expected_p99 else "❌ Breached"
        if metrics.p99_ms > expected_p99:
            all_passed = False
    else:
        p99_status = "ℹ️ Recorded"
    rows.append(f"| Command duration (p99) | {p99_expected_str} | {metrics.p99_ms:.2f}ms | {p99_status} |")

    # Max Latency
    rows.append(f"| Max command duration | - | {metrics.max_ms:.2f}ms | ℹ️ Recorded |")

    # Error Rate check
    err_expected_str = f"< {expected_err_pct:.1f}%" if expected_err_pct is not None else "< 1.0%"
    threshold = expected_err_pct if expected_err_pct is not None else 1.0
    err_status = "✅ Met" if metrics.error_rate_pct <= threshold else "❌ Breached"
    if metrics.error_rate_pct > threshold:
        all_passed = False
    rows.append(f"| Command failure rate | {err_expected_str} | {metrics.error_rate_pct:.2f}% | {err_status} |")

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


@dataclass
class SpikeFinding:
    rule_id: str
    severity: str  # ERROR, WARNING, INFO
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None


@dataclass
class SpikeValidationResult:
    passed: bool
    findings: List[SpikeFinding] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> List[SpikeFinding]:
        return [f for f in self.findings if f.severity == "ERROR"]

    @property
    def warnings(self) -> List[SpikeFinding]:
        return [f for f in self.findings if f.severity == "WARNING"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [asdict(f) for f in self.findings],
            "metrics": self.metrics,
        }


# Isolation check: Prototype code must never leak into production paths
FORBIDDEN_PROD_PREFIXES = ("src/", "lib/", "app/", "pkg/", "internal/")
ALLOWED_SPIKE_PREFIXES = (".scratch/", "scratch/", "docs/adr/", "openspec/", "tests/")

FALSIFIABLE_THRESHOLD_REGEX = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:ms|s|rps|tps|qps|req/sec|ops|kb|mb|gb|%)\b|[<>]=?\s*\d+)",
    re.IGNORECASE,
)


def audit_spike_isolation(file_paths: Sequence[str | Path]) -> SpikeValidationResult:
    """Audit changed or created paths during a spike to ensure zero leakage into production paths."""
    findings: List[SpikeFinding] = []

    for p in file_paths:
        p_str = str(p).replace("\\", "/")
        norm_path = p_str.lstrip("./")

        if any(norm_path.startswith(prefix) for prefix in FORBIDDEN_PROD_PREFIXES):
            findings.append(SpikeFinding(
                rule_id="SPK-ISO-001",
                severity="ERROR",
                message=f"Prototype code leaked into production directory: '{p_str}'. Spikes must remain strictly isolated inside .scratch/<spike-name>/.",
                file_path=p_str,
            ))

    errors = [f for f in findings if f.severity == "ERROR"]
    return SpikeValidationResult(
        passed=len(errors) == 0,
        findings=findings,
        metrics={"total_paths_audited": len(file_paths), "violations": len(errors)},
    )


def validate_spike_report(report_text: str, filename: str = "SpikeReport.md") -> SpikeValidationResult:
    """Validate a Spike Report against the canonical SKILL.md Section 3 schema and anti-cheat constraints."""
    findings: List[SpikeFinding] = []

    # 1. Header
    report_header = re.search(r"^##\s+🧪\s*Spike\s+Report:\s*(.+)$", report_text, re.MULTILINE)
    if not report_header:
        findings.append(SpikeFinding(
            rule_id="SPK-REP-001",
            severity="ERROR",
            message="Missing required header: '## 🧪 Spike Report: <Spike Name>'",
            file_path=filename,
        ))

    # 2. Question & Hypothesis
    if "### 🎯 Empirical Question & Hypothesis" not in report_text and "Empirical Question & Hypothesis" not in report_text:
        findings.append(SpikeFinding(
            rule_id="SPK-REP-002",
            severity="ERROR",
            message="Missing required section: '### 🎯 Empirical Question & Hypothesis'",
            file_path=filename,
        ))
    else:
        q_match = re.search(r"-\s+\*\*Question\*\*:\s*(.+)$", report_text, re.MULTILINE)
        h_match = re.search(r"-\s+\*\*Hypothesis\*\*:\s*(.+)$", report_text, re.MULTILINE)

        if not q_match or not q_match.group(1).strip():
            findings.append(SpikeFinding(
                rule_id="SPK-REP-003",
                severity="ERROR",
                message="Missing or empty '- **Question**: <Unresolved question>'",
                file_path=filename,
            ))

        if not h_match or not h_match.group(1).strip():
            findings.append(SpikeFinding(
                rule_id="SPK-REP-004",
                severity="ERROR",
                message="Missing or empty '- **Hypothesis**: <Expected outcome with numerical threshold>'",
                file_path=filename,
            ))
        else:
            hypo_text = h_match.group(1).strip()
            # Anti-Cheat: Hypothesis must contain numerical threshold / falsifiable SLI
            if not FALSIFIABLE_THRESHOLD_REGEX.search(hypo_text):
                findings.append(SpikeFinding(
                    rule_id="SPK-HYP-001",
                    severity="ERROR",
                    message=f"Hypothesis '{hypo_text}' lacks a falsifiable numerical threshold (e.g. '< 15ms', '> 5000 RPS', '< 1%').",
                    file_path=filename,
                ))

    # 3. Methodology & Setup
    if "### 🧪 Methodology & Setup" not in report_text and "Methodology & Setup" not in report_text:
        findings.append(SpikeFinding(
            rule_id="SPK-REP-005",
            severity="ERROR",
            message="Missing required section: '### 🧪 Methodology & Setup'",
            file_path=filename,
        ))
    else:
        if ".scratch/" not in report_text and "scratch/" not in report_text:
            findings.append(SpikeFinding(
                rule_id="SPK-REP-006",
                severity="WARNING",
                message="Methodology should document isolated sandbox location (e.g. '.scratch/<spike-name>/')",
                file_path=filename,
            ))

    # 4. Empirical Results Table
    results_match = re.search(r"###\s+📊\s*Empirical\s+Results", report_text, re.MULTILINE)
    has_breached_row = False
    if not results_match and "Empirical Results" not in report_text:
        findings.append(SpikeFinding(
            rule_id="SPK-REP-007",
            severity="ERROR",
            message="Missing required section: '### 📊 Empirical Results'",
            file_path=filename,
        ))
    else:
        # Check table columns: Metric / Condition | Expected | Observed | Status
        if "| Metric" not in report_text or "| Status" not in report_text:
            findings.append(SpikeFinding(
                rule_id="SPK-REP-008",
                severity="ERROR",
                message="Empirical Results table must include columns: '| Metric / Condition | Expected | Observed | Status |'",
                file_path=filename,
            ))
        if "❌ Breached" in report_text:
            has_breached_row = True

    # 5. Architectural Verdict
    verdict_match = re.search(r"###\s+⚖️\s*Architectural\s+Verdict", report_text, re.MULTILINE)
    if not verdict_match and "Architectural Verdict" not in report_text:
        findings.append(SpikeFinding(
            rule_id="SPK-REP-009",
            severity="ERROR",
            message="Missing required section: '### ⚖️ Architectural Verdict'",
            file_path=filename,
        ))
    else:
        v_token = re.search(r"-\s+\*\*Verdict\*\*:\s*\*{0,2}(CONFIRMED|REFUTED|QUALIFIED)\*{0,2}", report_text, re.IGNORECASE)
        if not v_token:
            findings.append(SpikeFinding(
                rule_id="SPK-VER-001",
                severity="ERROR",
                message="Verdict must explicitly state one of: CONFIRMED, REFUTED, or QUALIFIED",
                file_path=filename,
            ))
        else:
            verdict_val = v_token.group(1).upper()
            # Anti-Cheat: If any metric breached, verdict cannot be CONFIRMED
            if verdict_val == "CONFIRMED" and has_breached_row:
                findings.append(SpikeFinding(
                    rule_id="SPK-VER-002",
                    severity="ERROR",
                    message="Verdict contradiction: Marked 'CONFIRMED' despite one or more empirical metrics being '❌ Breached'.",
                    file_path=filename,
                ))

    # 6. Reusable Snippets
    if "### 💎 Reusable Snippets" not in report_text and "Reusable Snippets" not in report_text:
        findings.append(SpikeFinding(
            rule_id="SPK-REP-010",
            severity="WARNING",
            message="Spike report should include '### 💎 Reusable Snippets' extracted to ADR or production config",
            file_path=filename,
        ))

    errors = [f for f in findings if f.severity == "ERROR"]
    return SpikeValidationResult(
        passed=len(errors) == 0,
        findings=findings,
        metrics={
            "errors": len(errors),
            "warnings": len([f for f in findings if f.severity == "WARNING"]),
            "has_breached_row": has_breached_row,
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Automated Statistical Spike Runner for Prototypes")
    parser.add_argument("--cmd", help="Command line string to benchmark")
    parser.add_argument("--iterations", type=int, default=100, help="Number of measurement runs (default: 100)")
    parser.add_argument("--warmup", type=int, default=10, help="Number of warmup runs (default: 10)")
    parser.add_argument("--workers", "--concurrency", dest="concurrency", type=int, default=1, help="Concurrent worker threads (default: 1)")
    parser.add_argument("--duration", type=float, help="Run for duration in seconds instead of fixed iterations")
    parser.add_argument("--cwd", help="Working directory to run command in (defaults to current dir)")
    parser.add_argument("--expected-p99", type=float, help="Maximum p99 whole-command duration in ms, including process startup")
    parser.add_argument("--expected-runs-per-second", "--expected-rps", dest="expected_rps", type=float, help="Minimum completed commands/second; --expected-rps is a legacy alias, not service RPS")
    parser.add_argument("--expected-err", type=float, help="Expected maximum error rate percentage")
    parser.add_argument("--timeout", type=float, default=60.0, help="Timeout per iteration in seconds (default: 60.0)")
    parser.add_argument("--audit-report", help="Path to Spike Report markdown file to validate")
    parser.add_argument("--audit-paths", nargs="*", help="File paths to audit for prototype sandbox isolation")
    parser.add_argument("--probe", action="store_true", help="Run single-shot behavioral probe (checks single execution exit code and duration)")
    parser.add_argument("--cleanup", type=Path, help="Directory to clean up (.scratch/<spike-name>) upon passing result")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    args = parser.parse_args(argv)

    # 1. Audit Report Mode
    if args.audit_report:
        report_file = Path(args.audit_report).resolve()
        if not report_file.is_file():
            sys.stderr.write(f"Error: Report file not found: {report_file}\n")
            return 1
        report_text = report_file.read_text(encoding="utf-8")
        result = validate_spike_report(report_text, filename=report_file.name)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"Spike Report Validation: {'PASSED' if result.passed else 'FAILED'}")
            print(f"Errors: {len(result.errors)}, Warnings: {len(result.warnings)}")
            for f in result.findings:
                print(f"  • [{f.severity}] {f.rule_id}: {f.message}")
        return 0 if result.passed else 1

    # 2. Audit Paths Mode
    if args.audit_paths:
        result = audit_spike_isolation(args.audit_paths)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"Spike Sandbox Isolation: {'PASSED' if result.passed else 'FAILED'}")
            print(f"Violations: {len(result.errors)}")
            for f in result.findings:
                print(f"  • [{f.severity}] {f.rule_id}: {f.message}")
        return 0 if result.passed else 1

    # 3. Benchmark Mode
    if not args.cmd:
        parser.error("--cmd is required when not running in audit mode (--audit-report or --audit-paths)")

    cwd = Path(args.cwd).resolve() if args.cwd else None

    # 3. Behavioral Probe Mode (Archetype 1)
    if args.probe:
        elapsed_ms, success = run_single_iteration(args.cmd, cwd=cwd, timeout_sec=args.timeout)
        if args.cleanup and success and args.cleanup.exists():
            import shutil
            shutil.rmtree(args.cleanup, ignore_errors=True)

        if args.json:
            out = {
                "probe": True,
                "passed": success,
                "elapsed_ms": elapsed_ms,
                "cmd": args.cmd,
            }
            print(json.dumps(out, indent=2))
            return 0 if success else 1

        print(f"\n🧪 Behavioral Probe: {'PASSED' if success else 'FAILED'} ({elapsed_ms:.1f}ms)")
        print(f"Command: {args.cmd}")
        if success:
            print("✅ Verdict: Pass. Probe succeeded.")
            return 0
        else:
            print("❌ Verdict: Fail. Probe exited with failure or timed out.")
            return 1

    # 4. Benchmark Mode (Archetype 2)
    metrics = run_benchmark(
        cmd=args.cmd,
        iterations=args.iterations,
        warmup=args.warmup,
        concurrency=args.concurrency,
        duration_sec=args.duration,
        cwd=cwd,
        timeout_sec=args.timeout
    )

    table_str, passed = format_markdown_table(metrics, args.expected_p99, args.expected_rps, args.expected_err)

    if args.cleanup and passed and args.cleanup.exists():
        import shutil
        shutil.rmtree(args.cleanup, ignore_errors=True)

    if args.json:
        out = {
            "metrics": asdict(metrics),
            "passed": passed,
            "markdown_table": table_str
        }
        print(json.dumps(out, indent=2))
        return 0 if passed else 1

    print("")
    print(table_str)
    print("")
    if passed:
        print("✅ Verdict: Pass. Command-level thresholds met; service SLIs require workload measurements.")
        return 0
    else:
        print("❌ Verdict: Fail. One or more empirical thresholds were breached.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
