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
import { spawn, spawnSync } from "node:child_process";
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

export async function runSingleIteration(cmd: string | string[], cwd?: string, timeoutSec: number | null = 60): Promise<[number, boolean]> {
  const start = performance.now();
  return new Promise(resolve => {
    let settled = false, timedOut = false;
    const child = Array.isArray(cmd)
      ? spawn(cmd[0], cmd.slice(1), {cwd, stdio: "ignore", detached: process.platform !== "win32"})
      : spawn(cmd, {shell: true, cwd, stdio: "ignore", detached: process.platform !== "win32"});
    let timer: ReturnType<typeof setTimeout> | undefined;
    const finish = (ok: boolean) => {
      if (settled) return;
      settled = true; clearTimeout(timer);
      resolve([performance.now() - start, ok && !timedOut]);
    };
    child.once("error", () => finish(false));
    child.once("close", code => finish(code === 0));
    if (timeoutSec != null) timer = setTimeout(() => {
      timedOut = true;
      if (child.pid) {
        try {
          if (process.platform === "win32") spawnSync("taskkill", ["/F", "/T", "/PID", String(child.pid)], {stdio: "ignore"});
          else process.kill(-child.pid, "SIGKILL");
        } catch { child.kill("SIGKILL"); }
      }
    }, Math.max(0, timeoutSec * 1000));
  });
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
  cmd: string | string[];
  iterations: number;
  warmup?: number;
  concurrency?: number;
  durationSec?: number | null;
  cwd?: string | null;
  timeoutSec?: number | null;
}

export async function runBenchmark(options: BenchmarkOptions): Promise<BenchmarkMetrics> {
  const {cmd, cwd, timeoutSec = 60} = options;
  const iterations = Math.max(0, Math.trunc(options.iterations));
  const warmup = Math.max(0, Math.trunc(options.warmup ?? 0));
  const concurrency = Math.max(1, Math.trunc(options.concurrency ?? 1));
  if (![iterations, warmup, concurrency].every(Number.isFinite)) throw new Error("Benchmark counts must be finite integers");
  if (options.durationSec != null && (!Number.isFinite(options.durationSec) || options.durationSec < 0)) throw new Error("Duration must be finite and nonnegative");
  if (timeoutSec != null && (!Number.isFinite(timeoutSec) || timeoutSec < 0)) throw new Error("Timeout must be finite and nonnegative");
  async function pool(count: number, deadline: number | null, record: (result: [number, boolean]) => void) {
    let launched = 0;
    const worker = async () => {
      while (deadline === null ? launched < count : performance.now() < deadline) {
        launched++;
        record(await runSingleIteration(cmd, cwd ?? undefined, timeoutSec));
      }
    };
    // Only active workers allocate promises; pending iterations never form an unbounded queue.
    await Promise.all(Array.from({length: deadline === null ? Math.min(count, concurrency) : concurrency}, worker));
  }
  await pool(warmup, null, () => {});
  const latencies: number[] = [];
  let successes = 0, failures = 0;
  const startTotal = performance.now();
  const deadline = options.durationSec != null ? startTotal + options.durationSec * 1000 : null;
  await pool(iterations, deadline, ([elapsed, ok]) => {latencies.push(elapsed); if (ok) successes++; else failures++;});

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

export function validateSpikeReport(reportText: string, filename = "SpikeReport.md"): SpikeValidationResult {
  const findings: SpikeFinding[] = [];
  const add = (rule_id: string, message: string, severity: "ERROR" | "WARNING" = "ERROR") => findings.push({rule_id, message, severity, file_path: filename});
  if (!/^##\s+🧪\s*Spike\s+Report:\s*(.+)$/m.test(reportText)) add("SPK-REP-001", "Missing required header: '## 🧪 Spike Report: <Spike Name>'");
  if (!reportText.includes("Empirical Question & Hypothesis")) add("SPK-REP-002", "Missing Empirical Question & Hypothesis section");
  else {
    const question = /-\s+\*\*Question\*\*:\s*(.+)$/m.exec(reportText);
    const hypothesis = /-\s+\*\*Hypothesis\*\*:\s*(.+)$/m.exec(reportText);
    if (!question?.[1].trim()) add("SPK-REP-003", "Missing or empty Question");
    if (!hypothesis?.[1].trim()) add("SPK-REP-004", "Missing or empty Hypothesis");
    else if (!/(?:[<>]=?\s*\d|\d+(?:\.\d+)?\s*(?:ms|s\b|rps|tps|qps|%|req|ops|writes|reads))/i.test(hypothesis[1])) add("SPK-HYP-001", "Hypothesis lacks a falsifiable numerical threshold");
  }
  if (!reportText.includes("Methodology & Setup") && !reportText.includes("Experimental Setup & Reproduction")) add("SPK-REP-005", "Missing Methodology & Setup section");
  else if (!reportText.includes("scratch/")) add("SPK-REP-006", "Methodology should document isolated sandbox location", "WARNING");
  const hasBreached = reportText.includes("❌ Breached");
  if (!reportText.includes("Empirical Results")) add("SPK-REP-007", "Missing Empirical Results section");
  else if (!reportText.includes("| Metric") || !reportText.includes("| Status")) add("SPK-REP-008", "Empirical Results table requires Metric, Expected, Observed, Status columns");
  if (!reportText.includes("Architectural Verdict")) add("SPK-REP-009", "Missing Architectural Verdict section");
  else {
    const verdict = /-\s+\*\*Verdict\*\*:\s*\*{0,2}(CONFIRMED|REFUTED|QUALIFIED)\*{0,2}/i.exec(reportText);
    if (!verdict) add("SPK-VER-001", "Verdict must state CONFIRMED, REFUTED, or QUALIFIED");
    else if (verdict[1].toUpperCase() === "CONFIRMED" && hasBreached) add("SPK-VER-002", "Verdict contradiction: CONFIRMED despite breached empirical metrics");
  }
  if (!reportText.includes("Reusable Snippets")) add("SPK-REP-010", "Include reusable snippets in the report", "WARNING");
  const errors = findings.filter(f => f.severity === "ERROR").length;
  return new SpikeValidationResult(errors === 0, findings, {errors, warnings: findings.length - errors, has_breached_row: hasBreached});
}

export async function main(argv = process.argv.slice(2)): Promise<number> {
  const values: Record<string, string> = {};
  const flags = new Set<string>();
  const auditPaths: string[] = [];
  const aliases: Record<string, string> = {"--workers": "--concurrency", "--expected-runs-per-second": "--expected-rps", "--expected-err-pct": "--expected-err", "--validate-report": "--audit-report"};
  const valueOptions = new Set(["--cmd", "--iterations", "--warmup", "--concurrency", "--duration", "--cwd", "--expected-p99", "--expected-rps", "--expected-err", "--timeout", "--audit-report", "--cleanup", "--format"]);
  try {
    for (let i = 0; i < argv.length; i++) {
      const eq = argv[i].indexOf("=");
      let key = eq < 0 ? argv[i] : argv[i].slice(0, eq);
      key = aliases[key] ?? key;
      if (["--help", "-h"].includes(key)) {
        console.log("Usage: run_spike.ts --cmd <command> [--iterations N] [--warmup N] [--workers N] [--duration seconds] [--timeout seconds] [--cwd path] [--probe] [--cleanup path] [--json] [--format json|table] [--expected-p99 ms] [--expected-rps N] [--expected-err percent] [--audit-report file] [--audit-paths paths...]"); return 0;
      }
      if (["--json", "--probe"].includes(key)) flags.add(key);
      else if (key === "--audit-paths") { while (i + 1 < argv.length && !argv[i + 1].startsWith("--")) auditPaths.push(argv[++i]); }
      else if (valueOptions.has(key)) {
        const value = eq >= 0 ? argv[i].slice(eq + 1) : argv[++i];
        if (value === undefined) throw new Error(`Missing value for ${key}`);
        values[key] = value;
      } else throw new Error(`Unknown option: ${key}`);
    }
    const json = flags.has("--json") || values["--format"] === "json";
    if (values["--audit-report"] || auditPaths.length) {
      const result = values["--audit-report"] ? validateSpikeReport(fs.readFileSync(values["--audit-report"], "utf8"), path.basename(values["--audit-report"])) : auditSpikeIsolation(auditPaths);
      console.log(json ? JSON.stringify(result.to_dict(), null, 2) : `Spike Validation: ${result.passed ? "PASSED" : "FAILED"}\n${result.findings.map(f => `[${f.rule_id}] ${f.message}`).join("\n")}`);
      return result.passed ? 0 : 1;
    }
    const cmd = values["--cmd"];
    if (!cmd) throw new Error("--cmd is required outside audit mode");
    const number = (key: string, fallback?: number) => {
      const result = values[key] === undefined ? fallback : Number(values[key]);
      if (result !== undefined && !Number.isFinite(result)) throw new Error(`Invalid number for ${key}`);
      return result;
    };
    const cwd = values["--cwd"], timeout = number("--timeout", 60);
    let passed: boolean, result: any;
    if (flags.has("--probe")) {
      const [elapsed_ms, success] = await runSingleIteration(cmd, cwd, timeout);
      passed = success; result = {probe: true, passed, elapsed_ms, cmd};
    } else {
      const metrics = await runBenchmark({cmd, iterations: number("--iterations", 100)!, warmup: number("--warmup", 10), concurrency: number("--concurrency", 1), durationSec: number("--duration"), cwd, timeoutSec: timeout});
      const [markdown_table, success] = formatMarkdownTable(metrics, number("--expected-p99"), number("--expected-rps"), number("--expected-err"));
      passed = success; result = {metrics, markdown_table, passed};
    }
    if (passed && values["--cleanup"]) fs.rmSync(values["--cleanup"], {recursive: true, force: true});
    console.log(json ? JSON.stringify(flags.has("--json") || result.probe ? result : result.metrics, null, 2) : result.markdown_table ?? `Probe: ${passed ? "PASSED" : "FAILED"}`);
    return passed ? 0 : 1;
  } catch (error: any) { console.error(error.message); return 1; }
}

if (import.meta.url === `file://${process.argv[1]}`) process.exit(await main());
