import { describe, it } from "bun:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import {
  loadTraces,
  extractFeatures,
  selectDiverseSample,
} from "../src/ship/tools/sample_traces.ts";

const SCRIPT_PATH = path.resolve("src/ship/tools/sample_traces.ts");

describe("TypeScript Trace Sampling Engine (sample_traces.ts)", () => {
  it("loads traces from jsonl, json, and csv files", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sample-load-"));
    try {
      // JSONL
      const jsonlPath = path.join(tmpDir, "traces.jsonl");
      fs.writeFileSync(
        jsonlPath,
        JSON.stringify({ input: "hello", output: "world" }) + "\n" +
        JSON.stringify({ id: "custom_id", input: "foo", output: "bar" }) + "\n"
      );
      const jsonlTraces = loadTraces(jsonlPath);
      assert.strictEqual(jsonlTraces.length, 2);
      assert.strictEqual(jsonlTraces[0].trace_id, "trace_1");
      assert.strictEqual(jsonlTraces[1].id, "custom_id");

      // JSON array
      const jsonPath = path.join(tmpDir, "traces.json");
      fs.writeFileSync(jsonPath, JSON.stringify([
        { input: "a", output: "b" },
        { id: "id_2", input: "c", output: "d" }
      ]));
      const jsonTraces = loadTraces(jsonPath);
      assert.strictEqual(jsonTraces.length, 2);
      assert.strictEqual(jsonTraces[0].trace_id, "trace_1");
      assert.strictEqual(jsonTraces[1].id, "id_2");

      // CSV
      const csvPath = path.join(tmpDir, "traces.csv");
      fs.writeFileSync(csvPath, "input,output\ntest1,resp1\ntest2,resp2\n");
      const csvTraces = loadTraces(csvPath);
      assert.strictEqual(csvTraces.length, 2);
      assert.strictEqual(csvTraces[0].trace_id, "trace_1");
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("extracts structural heuristics for stratified bucketing", () => {
    const shortRecord = { input: "hi", output: "hello", tool_calls: [] };
    const fShort = extractFeatures(shortRecord);
    assert.strictEqual(fShort.len_bucket, "short");
    assert.strictEqual(fShort.has_tools, false);
    assert.strictEqual(fShort.has_error, false);

    const longRecord = {
      input: "complex query",
      output: "a".repeat(1200),
      tools: ["search", "exec"],
      status: "error",
    };
    const fLong = extractFeatures(longRecord);
    assert.strictEqual(fLong.len_bucket, "long");
    assert.strictEqual(fLong.has_tools, true);
    assert.strictEqual(fLong.has_error, true);
  });

  it("selects diverse sample across stratified features and random picks", () => {
    const traces: Record<string, any>[] = [];
    for (let i = 0; i < 50; i++) {
      traces.push({
        id: `trace_${i}`,
        input: `query ${i}`,
        output: i % 2 === 0 ? "short" : "a".repeat(1200),
        tools: i % 3 === 0 ? ["tool"] : [],
        error: i % 5 === 0 ? "failed" : null,
      });
    }

    const sample = selectDiverseSample(traces, 15, 42);
    assert.strictEqual(sample.length, 15);

    // Verify all sampled IDs are unique
    const ids = new Set(sample.map((s) => s.id));
    assert.strictEqual(ids.size, 15);
  });

  it("returns all traces when sample size is greater than or equal to total traces", () => {
    const traces = [{ id: "1" }, { id: "2" }];
    const sample = selectDiverseSample(traces, 5);
    assert.strictEqual(sample.length, 2);
  });

  it("runs CLI with --input, --count, and --output", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sample-cli-"));
    try {
      const inputFile = path.join(tmpDir, "input.jsonl");
      const lines = [];
      for (let i = 0; i < 20; i++) {
        lines.push(JSON.stringify({ id: `item_${i}`, input: `q${i}`, output: `a${i}` }));
      }
      fs.writeFileSync(inputFile, lines.join("\n") + "\n");

      const outputFile = path.join(tmpDir, "sampled.jsonl");
      const out = execFileSync(process.execPath, [
        SCRIPT_PATH,
        "--input", inputFile,
        "--output", outputFile,
        "--count", "5",
        "--seed", "123",
      ], { encoding: "utf-8" });

      assert.ok(out.includes("Sampled 5 diverse traces"));
      assert.ok(fs.existsSync(outputFile));
      const content = fs.readFileSync(outputFile, "utf-8").trim().split("\n");
      assert.strictEqual(content.length, 5);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
