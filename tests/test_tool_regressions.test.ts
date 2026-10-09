import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { computeMetrics, evaluateCalibration, formatReport, loadPairs } from "../src/ship/tools/evals.ts";
import { getGitDiff } from "../src/ship/tools/debug.ts";

describe("tool regressions migrated from Python", () => {
  let root: string;
  beforeEach(() => { root = fs.mkdtempSync(path.join(os.tmpdir(), "ship-regression-")); });
  afterEach(() => { fs.rmSync(root, { recursive: true, force: true }); });

  it("falls back from blank CSV columns without losing false labels", () => {
    const file = path.join(root, "labels.csv");
    fs.writeFileSync(file, "human,ground_truth,evaluator,prediction\n,Fail,,Pass\nPass,,Pass,\n");
    const pairs = loadPairs(file);
    expect(pairs).toEqual([["Fail", "Pass"], ["Pass", "Pass"]]);
    expect(computeMetrics(pairs).accuracy).toBe(0.5);
  });

  it("preserves false and zero labels in JSON and JSONL and reports false negatives", () => {
    const records = [{ human: true, evaluator: true }, { human: false, evaluator: true }, { human: 0, evaluator: 0 }];
    for (const suffix of [".json", ".jsonl"]) {
      const file = path.join(root, `labels${suffix}`);
      fs.writeFileSync(file, suffix === ".json" ? JSON.stringify(records) : records.map(record => JSON.stringify(record)).join("\n"));
      expect(loadPairs(file)).toEqual([["Pass", "Pass"], ["Fail", "Pass"], ["Fail", "Fail"]]);
    }
    expect(formatReport(evaluateCalibration([["Pass", "Fail"], ["Fail", "Fail"]]))).toContain("1 (FN");
  });

  it("prints a default Markdown calibration report", () => {
    const file = path.join(root, "labels.json");
    fs.writeFileSync(file, JSON.stringify([{ human: "Pass", evaluator: "Fail" }]));
    const result = spawnSync(process.execPath, [path.resolve("src/ship/tools/evals.ts"), "--input", file], { encoding: "utf8" });
    expect(result.error).toBeUndefined();
    expect(result.status).toBe(0);
    expect(result.stdout).toContain("1 (FN");
  });

  it("rejects a non-Git workspace through the API and strict CLI", () => {
    expect(() => getGitDiff(root)).toThrow();
    const result = spawnSync(process.execPath, [path.resolve("src/ship/tools/debug.ts"), "--path", root, "--strict"], { encoding: "utf8" });
    expect(result.error).toBeUndefined();
    expect(result.status).toBe(1);
  });
});
