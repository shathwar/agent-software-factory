import test, { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import {
  computeMetrics,
  roganGladenCorrection,
  bootstrapCi,
  loadPairs,
  verifySplitIsolation,
  auditJudgeRubric,
  evaluateCalibration,
  formatReport,
  PYDANTIC_JUDGE_TEMPLATE,
} from "../src/ship/tools/evals.ts";

const SCRIPT_PATH = path.resolve("src/ship/tools/evals.ts");

describe("TypeScript Evaluator Calibration & Rogan-Gladen Statistics (score_calibration.ts)", () => {
  it("calculates confusion matrix, TPR, TNR, and accuracy", () => {
    const pairs: [string, string][] = [
      ["Pass", "Pass"],
      ["Pass", "Pass"],
      ["Pass", "Pass"],
      ["Pass", "Pass"],
      ["Pass", "Fail"],
      ["Fail", "Fail"],
      ["Fail", "Fail"],
      ["Fail", "Fail"],
      ["Fail", "Fail"],
      ["Fail", "Pass"],
    ];

    const m = computeMetrics(pairs);
    assert.strictEqual(m.total, 10);
    assert.strictEqual(m.tp, 4);
    assert.strictEqual(m.fn, 1);
    assert.strictEqual(m.tn, 4);
    assert.strictEqual(m.fp, 1);
    assert.strictEqual(m.tpr, 0.80);
    assert.strictEqual(m.tnr, 0.80);
    assert.strictEqual(m.accuracy, 0.80);
  });

  it("calculates Rogan-Gladen corrected prevalence", () => {
    const theta = roganGladenCorrection(0.80, 0.92, 0.88);
    assert.ok(theta !== null);
    assert.ok(Math.abs(theta! - 0.85) < 0.01);

    // Near zero denominator returns null
    const uninformative = roganGladenCorrection(0.50, 0.50, 0.50);
    assert.strictEqual(uninformative, null);
  });

  it("computes bootstrap confidence intervals", () => {
    const pairs: [string, string][] = [];
    for (let i = 0; i < 40; i++) pairs.push(["Pass", "Pass"]);
    for (let i = 0; i < 40; i++) pairs.push(["Fail", "Fail"]);
    for (let i = 0; i < 10; i++) pairs.push(["Pass", "Fail"]);
    for (let i = 0; i < 10; i++) pairs.push(["Fail", "Pass"]);

    const [lower, upper] = bootstrapCi(pairs, 0.50, 200, 42);
    assert.ok(lower !== null && upper !== null);
    assert.ok(lower! < upper!);
    assert.ok(lower! >= 0.0 && upper! <= 1.0);
  });

  it("loads pairs from jsonl, json, and csv files", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "evals-load-"));
    try {
      // JSONL
      const jsonlPath = path.join(tmpDir, "data.jsonl");
      fs.writeFileSync(
        jsonlPath,
        JSON.stringify({ human: "Pass", evaluator: "Pass" }) + "\n" +
        JSON.stringify({ ground_truth: "0", prediction: "1" }) + "\n"
      );
      const jsonlPairs = loadPairs(jsonlPath);
      assert.strictEqual(jsonlPairs.length, 2);
      assert.deepStrictEqual(jsonlPairs[0], ["Pass", "Pass"]);
      assert.deepStrictEqual(jsonlPairs[1], ["Fail", "Pass"]);

      // CSV
      const csvPath = path.join(tmpDir, "data.csv");
      fs.writeFileSync(csvPath, "human,evaluator\nPass,Pass\nFail,Fail\n");
      const csvPairs = loadPairs(csvPath);
      assert.strictEqual(csvPairs.length, 2);
      assert.deepStrictEqual(csvPairs[0], ["Pass", "Pass"]);
      assert.deepStrictEqual(csvPairs[1], ["Fail", "Fail"]);

      // JSON array
      const jsonPath = path.join(tmpDir, "data.json");
      fs.writeFileSync(jsonPath, JSON.stringify([
        { label: "true", judge: "true" },
        { label: "false", judge: "false" }
      ]));
      const jsonPairs = loadPairs(jsonPath);
      assert.strictEqual(jsonPairs.length, 2);
      assert.deepStrictEqual(jsonPairs[0], ["Pass", "Pass"]);
      assert.deepStrictEqual(jsonPairs[1], ["Fail", "Fail"]);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("verifies train/test split isolation (EVL-LEAK-001)", () => {
    const [okClean, errsClean] = verifySplitIsolation(["t1", "t2"], ["v1", "v2"]);
    assert.strictEqual(okClean, true);
    assert.strictEqual(errsClean.length, 0);

    const [okLeaky, errsLeaky] = verifySplitIsolation(["t1", "leak_id", "t2"], ["v1", "leak_id"]);
    assert.strictEqual(okLeaky, false);
    assert.ok(errsLeaky[0].includes("EVL-LEAK-001"));
  });

  it("audits judge prompt rubrics for anti-patterns", () => {
    // Clean rubric
    const cleanPrompt = `You are an evaluator. Model: gpt-4o-2024-08-06.
Criteria: Must return status 200.
Step-by-step reasoning: Provide critique first.
Output Pass or Fail.`;
    const [okClean, errsClean] = auditJudgeRubric(cleanPrompt);
    assert.strictEqual(okClean, true);
    assert.strictEqual(errsClean.length, 0);

    // Likert rating pattern
    const likertPrompt = `Rate on a scale of 1 to 5. Step-by-step reasoning required. Model: gpt-4o-2024-08-06.`;
    const [okLikert, errsLikert] = auditJudgeRubric(likertPrompt);
    assert.strictEqual(okLikert, false);
    assert.ok(errsLikert.some((e) => e.includes("EVL-RUB-001")));

    // Missing critique pattern
    const noCritiquePrompt = `Model: gpt-4o-2024-08-06. If valid output Pass else Fail immediately.`;
    const [okCritique, errsCritique] = auditJudgeRubric(noCritiquePrompt);
    assert.strictEqual(okCritique, false);
    assert.ok(errsCritique.some((e) => e.includes("EVL-RUB-002")));

    // Unpinned model alias
    const unpinnedPrompt = `Model: gpt-4o. Provide step-by-step critique before deciding Pass or Fail.`;
    const [okUnpinned, errsUnpinned] = auditJudgeRubric(unpinnedPrompt);
    assert.strictEqual(okUnpinned, false);
    assert.ok(errsUnpinned.some((e) => e.includes("EVL-MOD-001")));
  });

  it("evaluates calibration and formats report", () => {
    const pairs: [string, string][] = [
      ["Pass", "Pass"],
      ["Pass", "Pass"],
      ["Fail", "Fail"],
      ["Fail", "Fail"],
    ];
    const res = evaluateCalibration(pairs, 0.5, 100);
    assert.strictEqual(res.status, "PASS");
    const report = formatReport(res);
    assert.ok(report.includes("LLM Judge Calibration & Alignment Report"));
    assert.ok(report.includes("Confusion Matrix"));
  });

  it("runs CLI with --template, --check-split, and --input", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "evals-cli-"));
    try {
      // --template
      const templateOut = execFileSync(process.execPath, [SCRIPT_PATH, "--template"], { encoding: "utf-8" });
      assert.ok(templateOut.includes("JudgeVerdict"));

      // --check-split
      const splitFile = path.join(tmpDir, "split.json");
      fs.writeFileSync(splitFile, JSON.stringify({ train: ["a", "b"], test: ["c", "d"] }));
      const splitOut = execFileSync(process.execPath, [SCRIPT_PATH, "--check-split", splitFile], { encoding: "utf-8" });
      assert.ok(splitOut.includes("Split isolation verified"));

      // --input with --format json
      const dataFile = path.join(tmpDir, "data.jsonl");
      fs.writeFileSync(
        dataFile,
        JSON.stringify({ human: "Pass", evaluator: "Pass" }) + "\n" +
        JSON.stringify({ human: "Fail", evaluator: "Fail" }) + "\n"
      );
      const jsonOut = execFileSync(process.execPath, [
        SCRIPT_PATH,
        "--input", dataFile,
        "--p-obs", "0.5",
        "--bootstrap", "50",
        "--format", "json",
      ], { encoding: "utf-8" });
      const parsed = JSON.parse(jsonOut);
      assert.strictEqual(parsed.status, "PASS");
      assert.strictEqual(parsed.metrics.total, 2);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
