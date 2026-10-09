import { describe, it } from "bun:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import {
  parseReport,
  validateReport,
  verifySourceEvidence,
  main,
} from "../src/ship/tools/review.ts";

const SCRIPT_PATH = path.resolve("src/ship/tools/review.ts");

const SAMPLE_FINDING = {
  id: "FINDING-001",
  severity: "MEDIUM",
  category: "Correctness",
  file: "average.py",
  line: "L2",
  title: "Empty input crashes instead of returning zero",
  problem: "Empty input divides by zero.",
  evidence: "return sum(values) / len(values)",
  impact: "Empty requests fail.",
  recommendation: "Return zero for an empty input.",
  confidence: 1.0,
  fixability: "autonomous",
};

function createReport(overrides = {}) {
  return {
    reviewer: "correctness",
    status: "complete",
    findings: [{ ...SAMPLE_FINDING }],
    coverage: ["Inspected average.py."],
    questions: [],
    routing_notes: [],
    ...overrides,
  };
}

describe("TypeScript Review Report Validator (validate_report.ts)", () => {
  it("validates a sound report and an empty report", () => {
    const valid = createReport();
    assert.deepEqual(validateReport(valid), []);

    const empty = createReport({ findings: [] });
    assert.deepEqual(validateReport(empty), []);
  });

  it("rejects invalid top-level fields and missing/extra keys", () => {
    const missingTop: any = createReport();
    delete missingTop.reviewer;
    const errorsMissing = validateReport(missingTop);
    assert.ok(errorsMissing.some((e: string) => e.includes("$.reviewer: field is required")));

    const extraTop: any = createReport({ unknownField: "unexpected" });
    const errorsExtra = validateReport(extraTop);
    assert.ok(errorsExtra.some((e: string) => e.includes("$.unknownField: unexpected property")));

    const badReviewer = createReport({ reviewer: "security" });
    assert.ok(validateReport(badReviewer).some((e: string) => e.includes("$.reviewer: must be one of")));

    const badStatus = createReport({ status: "in_progress" });
    assert.ok(validateReport(badStatus).some((e: string) => e.includes("$.status: must be one of")));
  });

  it("validates finding fields according to schema", () => {
    // Bad finding id pattern
    const badId = createReport({ findings: [{ ...SAMPLE_FINDING, id: "BAD-1" }] });
    assert.ok(validateReport(badId).some((e: string) => e.includes("must match pattern")));

    // Duplicate finding id
    const dupId = createReport({ findings: [{ ...SAMPLE_FINDING }, { ...SAMPLE_FINDING }] });
    assert.ok(validateReport(dupId).some((e: string) => e.includes("Duplicate finding ID")));

    // Bad severity
    const badSev = createReport({ findings: [{ ...SAMPLE_FINDING, severity: "URGENT" }] });
    assert.ok(validateReport(badSev).some((e: string) => e.includes("severity: must be one of")));

    // Bad category
    const badCat = createReport({ findings: [{ ...SAMPLE_FINDING, category: "Security" }] });
    assert.ok(validateReport(badCat).some((e: string) => e.includes("category: must be one of")));

    // Bad line format
    const badLine = createReport({ findings: [{ ...SAMPLE_FINDING, line: "L0" }] });
    assert.ok(validateReport(badLine).some((e: string) => e.includes("line: must match pattern")));

    // Reverse line range
    const revLine = createReport({ findings: [{ ...SAMPLE_FINDING, line: "L10-L5" }] });
    assert.ok(validateReport(revLine).some((e: string) => e.includes("line range ends before it starts")));

    // Absolute file path
    const absPath = createReport({ findings: [{ ...SAMPLE_FINDING, file: "/etc/passwd" }] });
    assert.ok(validateReport(absPath).some((e: string) => e.includes("must be a repository-relative path")));

    // Bad confidence range
    const badConf = createReport({ findings: [{ ...SAMPLE_FINDING, confidence: 1.5 }] });
    assert.ok(validateReport(badConf).some((e: string) => e.includes("confidence: must be a finite number")));
  });

  it("demotes manufactured stylistic issues marked CRITICAL or HIGH (REV-SEV-001)", () => {
    const stylistic = createReport({
      findings: [
        {
          ...SAMPLE_FINDING,
          severity: "HIGH",
          title: "Violation of camelCase naming convention in variable",
          problem: "Rename user_id to userId according to naming convention",
        },
      ],
    });
    const errors = validateReport(stylistic);
    assert.ok(errors.some((e: string) => e.includes("[REV-SEV-001]")));
  });

  it("parses report with fenced markdown blocks and detects duplicate JSON keys", () => {
    const rawFenced = "```json\n" + JSON.stringify(createReport()) + "\n```";
    const parsed = parseReport(rawFenced);
    assert.equal(parsed.reviewer, "correctness");

    const duplicateKeyJson = '{"reviewer": "correctness", "status": "complete", "status": "incomplete", "findings": [], "coverage": [], "questions": [], "routing_notes": []}';
    assert.throws(() => parseReport(duplicateKeyJson), /Duplicate JSON key/);
  });

  it("verifies source evidence against working tree files", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "review-source-"));
    try {
      const srcFile = path.join(tmpDir, "math.py");
      fs.writeFileSync(srcFile, "def average(values):\n    return sum(values) / len(values)\n");

      // Exact evidence match
      const reportValid = createReport({
        findings: [
          {
            ...SAMPLE_FINDING,
            file: "math.py",
            evidence: "return sum(values) / len(values)",
          },
        ],
      });
      const errorsValid = verifySourceEvidence(reportValid, tmpDir);
      assert.deepEqual(errorsValid, []);

      // Non-existent file (REV-SRC-001)
      const reportMissingFile = createReport({
        findings: [
          {
            ...SAMPLE_FINDING,
            file: "non_existent.py",
          },
        ],
      });
      const errorsMissing = verifySourceEvidence(reportMissingFile, tmpDir);
      assert.ok(errorsMissing.some((e: string) => e.includes("[REV-SRC-001]")));

      // Hallucinated evidence (REV-EV-001)
      const reportFakeEv = createReport({
        findings: [
          {
            ...SAMPLE_FINDING,
            file: "math.py",
            evidence: "hallucinated_variable = 999",
          },
        ],
      });
      const errorsFake = verifySourceEvidence(reportFakeEv, tmpDir);
      assert.ok(errorsFake.some((e: string) => e.includes("[REV-EV-001]")));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("runs CLI successfully on valid report file and stdin", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "review-cli-"));
    try {
      const reportFile = path.join(tmpDir, "report.json");
      fs.writeFileSync(reportFile, JSON.stringify(createReport()));

      const stdout = execFileSync(process.execPath, [SCRIPT_PATH, reportFile], {
        encoding: "utf-8",
      });
      assert.ok(stdout.includes("Report structure is valid"));

      // Stdin
      const stdinStdout = execFileSync(process.execPath, [SCRIPT_PATH, "-"], {
        input: JSON.stringify(createReport()),
        encoding: "utf-8",
      });
      assert.ok(stdinStdout.includes("Report structure is valid"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
