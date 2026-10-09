import { describe, it } from "bun:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import {
  calculatePercentile,
  runBenchmark,
  formatMarkdownTable,
  auditSpikeIsolation,
  validateSpikeReport,
  main,
} from "../src/ship/tools/spike.ts";

const SCRIPT_PATH = path.resolve("src/ship/tools/spike.ts");

describe("TypeScript Prototype Spike Benchmark & Isolation Validator (run_spike.ts)", () => {
  it("calculates percentiles using linear interpolation", () => {
    const data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0];
    const p50 = calculatePercentile(data, 50);
    assert.ok(Math.abs(p50 - 5.5) < 0.1);

    const p90 = calculatePercentile(data, 90);
    assert.ok(Math.abs(p90 - 9.1) < 0.1);

    const p99 = calculatePercentile(data, 99);
    assert.ok(p99 > 9.5 && p99 <= 10.0);

    assert.equal(calculatePercentile([], 50), 0.0);
    assert.equal(calculatePercentile([42.0], 50), 42.0);
  });

  it("runs benchmark command iterations and records metrics", async () => {
    const metrics = await runBenchmark({
      cmd: `${process.execPath} -e "process.exit(0)"`,
      iterations: 15,
      warmup: 3,
      concurrency: 2,
    });
    assert.equal(metrics.total_runs, 15);
    assert.equal(metrics.successful_runs, 15);
    assert.equal(metrics.failed_runs, 0);
    assert.equal(metrics.error_rate_pct, 0.0);
    assert.ok(metrics.rps > 0);
    assert.ok(metrics.min_ms <= metrics.p50_ms);
    assert.ok(metrics.p50_ms <= metrics.p95_ms);
    assert.ok(metrics.p95_ms <= metrics.p99_ms);
    assert.ok(metrics.p99_ms <= metrics.max_ms);
  });

  it("formats markdown tables and checks SLO thresholds", () => {
    const fakeMetrics = {
      total_runs: 100,
      successful_runs: 100,
      failed_runs: 0,
      error_rate_pct: 0.0,
      total_duration_sec: 1.0,
      rps: 100.0,
      min_ms: 5.0,
      p50_ms: 10.0,
      p90_ms: 15.0,
      p95_ms: 18.0,
      p99_ms: 22.0,
      max_ms: 25.0,
      mean_ms: 11.0,
      stddev_ms: 2.5,
    };
    // Expected p99 < 30ms -> Met
    const [table1, passed1] = formatMarkdownTable(fakeMetrics as any, 30.0, 50.0, 1.0);
    assert.equal(passed1, true);
    assert.ok(table1.includes("✅ Met"));
    assert.ok(!table1.includes("❌ Breached"));

    // Expected p99 < 15ms -> Breached
    const [table2, passed2] = formatMarkdownTable(fakeMetrics as any, 15.0, 50.0, 1.0);
    assert.equal(passed2, false);
    assert.ok(table2.includes("❌ Breached"));
  });

  it("audits spike isolation ensuring zero leakage into production paths", () => {
    const badPaths = [".scratch/spike/test.ts", "src/leaked_prototype.ts"];
    const resBad = auditSpikeIsolation(badPaths);
    assert.equal(resBad.passed, false);
    assert.ok(resBad.findings.some((f) => f.rule_id === "SPK-ISO-001"));

    const goodPaths = [".scratch/spike/bench.ts", "docs/adr/ADR-0001.md"];
    const resGood = auditSpikeIsolation(goodPaths);
    assert.equal(resGood.passed, true);
  });

  it("validates a canonical Spike Report markdown", () => {
    const reportText = `## 🧪 Spike Report: Redis vs Kafka
### 🎯 Empirical Question & Hypothesis
- **Question**: Can Redis Streams sustain 20,000 writes/sec with < 5ms p99 latency?
- **Hypothesis**: Redis Streams in-memory structure achieves 25k RPS and p99 < 3ms.

### 🔬 Experimental Setup & Reproduction
- Code location: .scratch/redis-bench/
- Test command: node bench.js

### 📊 Empirical Results
| Metric / Condition | Expected | Observed | Status |
|---|---|---|---|
| RPS | > 20,000 | 24,500 | ✅ Met |
| p99 | < 5.0ms | 2.8ms | ✅ Met |

### ⚖️ Architectural Verdict & Settled Frontier
- **Verdict**: CONFIRMED
- **Decision Settled**: We will adopt Redis Streams.
- **Architectural Trade-offs**: High memory consumption accepted in exchange for sub-3ms latency.
`;
    const res = validateSpikeReport(reportText);
    assert.equal(res.passed, true);
  });

  it("runs CLI on fast command with JSON output", () => {
    const stdout = execFileSync(
      process.execPath,
      [
        SCRIPT_PATH,
        "--cmd",
        `${process.execPath} -e "process.exit(0)"`,
        "--iterations",
        "5",
        "--warmup",
        "1",
        "--format",
        "json",
      ],
      { encoding: "utf-8" }
    );
    const parsed = JSON.parse(stdout);
    assert.equal(parsed.total_runs, 5);
    assert.equal(parsed.successful_runs, 5);
  });
});
