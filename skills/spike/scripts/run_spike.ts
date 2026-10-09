#!/usr/bin/env node
/**
 * run_spike.ts — Automated Statistical Benchmark Harness for Prototype Spikes.
 * Zero external dependencies (Node.js 22+ / 25+ standard library).
 *
 * Measures:
 * - Latency percentiles: p50, p90, p95, p99, Min, Max, Mean, StdDev
 * - Throughput: Requests / operations per second (RPS)
 * - Reliability: Error count and error percentage
 * - Output: Official Markdown table matching spike/SKILL.md contract or JSON
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { execSync, spawnSync } from "node:child_process";
import { performance } from "node:perf_hooks";

export interface BenchmarkMetrics {
  total_runs: number;
  successful_runs: number;
  failed_runs: number;
  error_rate_pct: number;
  total_duration_sec: number;
  rps: number;
  min_ms: number;
  p50_ms: number;
  p90_ms: number;
  p95_ms: number;
  p99_ms: number;
  max_ms: number;
  mean_ms: number;
  stddev_ms: number;
  measurement_scope?: string;
  throughput_unit?: string;
}

export function runSingleIteration(cmd: string, cwd?: string, timeoutSec: number = 60.0): [number, boolean] {
  const start = performance.now();
  try {
    const res = spawnSync(cmd, {
      shell: true,
      cwd,
      timeout: timeoutSec * 1000,
      stdio: "ignore",
    });
    const elapsed = performance.now() - start;
    const ok = res.status === 0 && !res.error;
    return [elapsed, ok];
  } catch {
    const elapsed = performance.now() - start;
    return [elapsed, false];
  }
}

export function calculatePercentile(sortedData: number[], percentile: number): number {
  if (!sortedData || sortedData.length === 0) {
    return 0.0;
  }
  if (sortedData.length === 1) {
    return sortedData[0];
  }
  const clamped = Math.max(0.0, Math.min(100.0, percentile));
  const idx = (sortedData.length - 1) * (clamped / 100.0);
  const low = Math.floor(idx);
  const high = Math.min(low + 1, sortedData.length - 1);
  const weight = idx - low;
  return sortedData[low] * (1.0 - weight) + sortedData[high] * weight;
}

export interface BenchmarkOptions {
  cmd: string;
  iterations: number;
  warmup?: number;
  concurrency?: number;
  durationSec?: number | null;
  cwd?: string | null;
  timeoutSec?: number;
}

export function runBenchmark(options: BenchmarkOptions): BenchmarkMetrics {
  const { cmd, iterations, warmup = 0, cwd = undefined, timeoutSec = 60.0 } = options;

  // 1. Warmup
  for (let i = 0; i < warmup; i++) {
    runSingleIteration(cmd, cwd ?? undefined, timeoutSec);
  }

  // 2. Measurement
  const latencies: number[] = [];
  let successes = 0;
  let failures = 0;
  const startTotal = performance.now();

  for (let i = 0; i < iterations; i++) {
    const [elapsed, ok] = runSingleIteration(cmd, cwd ?? undefined, timeoutSec);
    latencies.push(elapsed);
    if (ok) {
      successes++;
    } else {
      failures++;
    }
  }

  const totalDurationSec = (performance.now() - startTotal) / 1000.0;
  const totalRuns = latencies.length;
  if (totalRuns === 0) {
    return {
      total_runs: 0,
      successful_runs: 0,
      failed_runs: 0,
      error_rate_pct: 100.0,
      total_duration_sec: totalDurationSec,
      rps: 0.0,
      min_ms: 0.0,
      p50_ms: 0.0,
      p90_ms: 0.0,
      p95_ms: 0.0,
      p99_ms: 0.0,
      max_ms: 0.0,
      mean_ms: 0.0,
      stddev_ms: 0.0,
      measurement_scope: "subprocess_wall_time",
      throughput_unit: "command_runs_per_second",
    };
  }

  latencies.sort((a, b) => a - b);
  const rps = totalDurationSec > 0 ? totalRuns / totalDurationSec : 0.0;
  const errPct = (failures / totalRuns) * 100.0;

  const sum = latencies.reduce((a, b) => a + b, 0);
  const mean = sum / totalRuns;
  const variance =
    totalRuns > 1 ? latencies.reduce((acc, val) => acc + Math.pow(val - mean, 2), 0) / (totalRuns - 1) : 0.0;
  const stddev = Math.sqrt(variance);

  return {
    total_runs: totalRuns,
    successful_runs: successes,
    failed_runs: failures,
    error_rate_pct: Math.round(errPct * 100) / 100,
    total_duration_sec: Math.round(totalDurationSec * 1000) / 1000,
    rps: Math.round(rps * 10) / 10,
    min_ms: Math.round(latencies[0] * 100) / 100,
    p50_ms: Math.round(calculatePercentile(latencies, 50) * 100) / 100,
    p90_ms: Math.round(calculatePercentile(latencies, 90) * 100) / 100,
    p95_ms: Math.round(calculatePercentile(latencies, 95) * 100) / 100,
    p99_ms: Math.round(calculatePercentile(latencies, 99) * 100) / 100,
    max_ms: Math.round(latencies[latencies.length - 1] * 100) / 100,
    mean_ms: Math.round(mean * 100) / 100,
    stddev_ms: Math.round(stddev * 100) / 100,
    measurement_scope: "subprocess_wall_time",
    throughput_unit: "command_runs_per_second",
  };
}

export function formatMarkdownTable(
  metrics: BenchmarkMetrics,
  expectedP99?: number | null,
  expectedRps?: number | null,
  expectedErrPct?: number | null
): [string, boolean] {
  let allPassed = true;
  const rows: string[] = [];

  // RPS check
  const rpsExpectedStr = expectedRps !== undefined && expectedRps !== null ? `> ${expectedRps.toLocaleString()}` : "-";
  let rpsStatus = "ℹ️ Recorded";
  if (expectedRps !== undefined && expectedRps !== null) {
    rpsStatus = metrics.rps >= expectedRps ? "✅ Met" : "❌ Breached";
    if (metrics.rps < expectedRps) {
      allPassed = false;
    }
  }
  rows.push(`| Command runs / second | ${rpsExpectedStr} | ${metrics.rps.toLocaleString()} | ${rpsStatus} |`);

  // p50
  rows.push(`| Command duration (p50) | - | ${metrics.p50_ms.toFixed(2)}ms | ℹ️ Recorded |`);
  // p95
  rows.push(`| Command duration (p95) | - | ${metrics.p95_ms.toFixed(2)}ms | ℹ️ Recorded |`);

  // p99 check
  const p99ExpectedStr = expectedP99 !== undefined && expectedP99 !== null ? `< ${expectedP99.toFixed(1)}ms` : "-";
  let p99Status = "ℹ️ Recorded";
  if (expectedP99 !== undefined && expectedP99 !== null) {
    p99Status = metrics.p99_ms <= expectedP99 ? "✅ Met" : "❌ Breached";
    if (metrics.p99_ms > expectedP99) {
      allPassed = false;
    }
  }
  rows.push(`| Command duration (p99) | ${p99ExpectedStr} | ${metrics.p99_ms.toFixed(2)}ms | ${p99Status} |`);

  // Max
  rows.push(`| Max command duration | - | ${metrics.max_ms.toFixed(2)}ms | ℹ️ Recorded |`);

  // Error Rate check
  const threshold = expectedErrPct !== undefined && expectedErrPct !== null ? expectedErrPct : 1.0;
  const errExpectedStr = expectedErrPct !== undefined && expectedErrPct !== null ? `< ${expectedErrPct.toFixed(1)}%` : "< 1.0%";
  const errStatus = metrics.error_rate_pct <= threshold ? "✅ Met" : "❌ Breached";
  if (metrics.error_rate_pct > threshold) {
    allPassed = false;
  }
  rows.push(`| Command failure rate | ${errExpectedStr} | ${metrics.error_rate_pct.toFixed(2)}% | ${errStatus} |`);

  const lines = [
    "### 📊 Empirical Results",
    `*Conducted ${metrics.total_runs} total runs over ${metrics.total_duration_sec.toFixed(2)}s*`,
    "",
    "| Metric / Condition | Expected | Observed | Status |",
    "|---|---|---|---|",
    ...rows,
    "",
    `*(Mean: ${metrics.mean_ms.toFixed(2)}ms, StdDev: ${metrics.stddev_ms.toFixed(2)}ms, Min: ${metrics.min_ms.toFixed(2)}ms)*`,
  ];

  return [lines.join("\n"), allPassed];
}

export interface SpikeFinding {
  rule_id: string;
  severity: "ERROR" | "WARNING" | "INFO";
  message: string;
  file_path?: string | null;
  line_number?: number | null;
}

export class SpikeValidationResult {
  passed: boolean;
  findings: SpikeFinding[];
  metrics: Record<string, any>;

  constructor(passed: boolean, findings: SpikeFinding[] = [], metrics: Record<string, any> = {}) {
    this.passed = passed;
    this.findings = findings;
    this.metrics = metrics;
  }

  get errors(): SpikeFinding[] {
    return this.findings.filter((f) => f.severity === "ERROR");
  }

  get warnings(): SpikeFinding[] {
    return this.findings.filter((f) => f.severity === "WARNING");
  }

  to_dict(): Record<string, any> {
    return {
      passed: this.passed,
      error_count: this.errors.length,
      warning_count: this.warnings.length,
      findings: this.findings,
      metrics: this.metrics,
    };
  }
}

export const FORBIDDEN_PROD_PREFIXES = ["src/", "lib/", "app/", "pkg/", "internal/"];

export function auditSpikeIsolation(filePaths: (string | any)[]): SpikeValidationResult {
  const findings: SpikeFinding[] = [];

  for (const p of filePaths) {
    const pStr = String(p).replace(/\\/g, "/");
    const normPath = pStr.replace(/^\.\//, "");

    if (FORBIDDEN_PROD_PREFIXES.some((prefix) => normPath.startsWith(prefix))) {
      findings.push({
        rule_id: "SPK-ISO-001",
        severity: "ERROR",
        message: `Prototype code leaked into production directory: '${pStr}'. Spikes must remain strictly isolated inside .scratch/<spike-name>/.`,
        file_path: pStr,
      });
    }
  }

  const errors = findings.filter((f) => f.severity === "ERROR");
  return new SpikeValidationResult(errors.length === 0, findings, {
    total_paths_audited: filePaths.length,
    violations: errors.length,
  });
}

export function validateSpikeReport(reportText: string, filename: string = "SpikeReport.md"): SpikeValidationResult {
  const findings: SpikeFinding[] = [];

  // 1. Header
  if (!/^##\s+🧪\s*Spike\s+Report:\s*(.+)$/m.test(reportText)) {
    findings.push({
      rule_id: "SPK-REP-001",
      severity: "ERROR",
      message: "Missing required header: '## 🧪 Spike Report: <Spike Name>'",
      file_path: filename,
    });
  }

  // 2. Question & Hypothesis
  if (!reportText.includes("Empirical Question & Hypothesis")) {
    findings.push({
      rule_id: "SPK-REP-002",
      severity: "ERROR",
      message: "Missing required section: '### 🎯 Empirical Question & Hypothesis'",
      file_path: filename,
    });
  }

  // 3. Setup & Reproduction
  if (!reportText.includes("Experimental Setup & Reproduction")) {
    findings.push({
      rule_id: "SPK-REP-003",
      severity: "ERROR",
      message: "Missing required section: '### 🔬 Experimental Setup & Reproduction'",
      file_path: filename,
    });
  }

  // 4. Empirical Results
  if (!reportText.includes("Empirical Results")) {
    findings.push({
      rule_id: "SPK-REP-004",
      severity: "ERROR",
      message: "Missing required section: '### 📊 Empirical Results'",
      file_path: filename,
    });
  }

  // 5. Architectural Verdict
  if (!reportText.includes("Architectural Verdict & Settled Frontier")) {
    findings.push({
      rule_id: "SPK-REP-005",
      severity: "ERROR",
      message: "Missing required section: '### ⚖️ Architectural Verdict & Settled Frontier'",
      file_path: filename,
    });
  }

  const errors = findings.filter((f) => f.severity === "ERROR");
  return new SpikeValidationResult(errors.length === 0, findings, {
    findings_count: findings.length,
    errors: errors.length,
  });
}

export function main(argv: string[] = process.argv.slice(2)): number {
  let cmd: string | undefined;
  let iterations = 10;
  let warmup = 0;
  let format: "table" | "json" = "table";
  let expectedP99: number | undefined;
  let expectedRps: number | undefined;
  let expectedErrPct: number | undefined;
  let reportFile: string | undefined;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--cmd") {
      cmd = argv[++i];
    } else if (arg.startsWith("--cmd=")) {
      cmd = arg.split("=")[1];
    } else if (arg === "--iterations") {
      iterations = parseInt(argv[++i], 10);
    } else if (arg.startsWith("--iterations=")) {
      iterations = parseInt(arg.split("=")[1], 10);
    } else if (arg === "--warmup") {
      warmup = parseInt(argv[++i], 10);
    } else if (arg.startsWith("--warmup=")) {
      warmup = parseInt(arg.split("=")[1], 10);
    } else if (arg === "--format") {
      const next = argv[++i];
      if (next === "json" || next === "table") {
        format = next;
      }
    } else if (arg.startsWith("--format=")) {
      const val = arg.split("=")[1];
      if (val === "json" || val === "table") {
        format = val;
      }
    } else if (arg === "--expected-p99") {
      expectedP99 = parseFloat(argv[++i]);
    } else if (arg.startsWith("--expected-p99=")) {
      expectedP99 = parseFloat(arg.split("=")[1]);
    } else if (arg === "--expected-rps") {
      expectedRps = parseFloat(argv[++i]);
    } else if (arg.startsWith("--expected-rps=")) {
      expectedRps = parseFloat(arg.split("=")[1]);
    } else if (arg === "--expected-err-pct") {
      expectedErrPct = parseFloat(argv[++i]);
    } else if (arg.startsWith("--expected-err-pct=")) {
      expectedErrPct = parseFloat(arg.split("=")[1]);
    } else if (arg === "--validate-report") {
      reportFile = argv[++i];
    } else if (arg.startsWith("--validate-report=")) {
      reportFile = arg.split("=")[1];
    }
  }

  if (reportFile) {
    const text = fs.readFileSync(reportFile, "utf-8");
    const res = validateSpikeReport(text, reportFile);
    if (format === "json") {
      console.log(JSON.stringify(res.to_dict(), null, 2));
    } else {
      console.log(`Spike Report Validation: ${res.passed ? "PASSED" : "FAILED"}`);
      for (const f of res.findings) {
        console.log(`  • [${f.severity}] ${f.rule_id}: ${f.message}`);
      }
    }
    return res.passed ? 0 : 1;
  }

  if (!cmd) {
    process.stderr.write("Usage: run_spike.ts --cmd '<command>' [--iterations <n>] [--warmup <n>] [--format json|table]\n");
    return 1;
  }

  const metrics = runBenchmark({ cmd, iterations, warmup });

  if (format === "json") {
    console.log(JSON.stringify(metrics, null, 2));
    return 0;
  }

  const [table, passed] = formatMarkdownTable(metrics, expectedP99, expectedRps, expectedErrPct);
  console.log(table);
  return passed ? 0 : 1;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const exitCode = main();
  process.exit(exitCode);
}
