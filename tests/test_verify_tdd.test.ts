import test, { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import {
  isProductionCode,
  isTestFile,
  isExcluded,
  isTypeDefinition,
  checkAntiPatterns,
  auditTDD,
  trimTestReceipt,
  auditTestDiff,
  verifyTDD,
  main,
} from "../src/ship/tools/tdd.ts";

const SCRIPT_PATH = path.resolve("src/ship/tools/tdd.ts");

describe("TypeScript TDD Verification & Anti-Pattern Auditor (verify_tdd.ts)", () => {
  it("categorizes files properly", () => {
    // Production code
    assert.equal(isProductionCode("src/user_service.py"), true);
    assert.equal(isProductionCode("pkg/auth/handler.go"), true);
    assert.equal(isProductionCode("app/services/payment.ts"), true);
    assert.equal(isProductionCode("components/Button.tsx"), true);

    // Test files
    assert.equal(isTestFile("tests/test_user.py"), true);
    assert.equal(isTestFile("src/user_service_test.go"), true);
    assert.equal(isTestFile("tests/payment.spec.ts"), true);
    assert.equal(isTestFile("tests/unit/calc.test.ts"), true);
    assert.equal(isProductionCode("tests/test_user.py"), false);

    // Excluded paths
    assert.equal(isExcluded("docs/architecture.md"), true);
    assert.equal(isExcluded(".scratch/spike/bench.py"), true);
    assert.equal(isExcluded("config.json"), true);
    assert.equal(isProductionCode("docs/architecture.md"), false);

    // Type definitions (exempted from 1:1 behavioral unit tests)
    assert.equal(isTypeDefinition("types/user.d.ts"), true);
    assert.equal(isTypeDefinition("src/types/models.ts"), true);
    assert.equal(isTypeDefinition("src/interfaces/repo.ts"), true);
    assert.equal(isProductionCode("types/user.d.ts"), false);
  });

  it("detects assertless tests", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tdd-assertless-"));
    try {
      const testFile = path.join(tmpDir, "example.test.ts");
      fs.writeFileSync(
        testFile,
        `
it("does math without asserting", () => {
  const x = 1 + 1;
  const y = x * 2;
});
`
      );
      const findings = checkAntiPatterns(testFile);
      const categories = findings.map((f) => f.category);
      assert.ok(categories.includes("assertless_test"));
      assert.ok(findings.some((f) => f.ruleId === "TDD-ASRT-001"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("detects tautological assertions", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tdd-tautology-"));
    try {
      const testFile = path.join(tmpDir, "tautology.test.ts");
      fs.writeFileSync(
        testFile,
        `
it("tautological test", () => {
  expect(true).toBe(true);
});
`
      );
      const findings = checkAntiPatterns(testFile);
      const categories = findings.map((f) => f.category);
      assert.ok(categories.includes("tautological_assertion"));
      assert.ok(findings.some((f) => f.ruleId === "TDD-TAUT-001"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("detects whitebox spy private member inspection", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tdd-whitebox-"));
    try {
      const testFile = path.join(tmpDir, "whitebox.test.ts");
      fs.writeFileSync(
        testFile,
        `
it("inspects private member", () => {
  const svc = new UserService();
  assert.equal(svc._internalCache, null);
});
`
      );
      const findings = checkAntiPatterns(testFile);
      const categories = findings.map((f) => f.category);
      assert.ok(categories.includes("whitebox_spy"));
      assert.ok(findings.some((f) => f.ruleId === "TDD-SPY-001"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("detects mocked database violations", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tdd-mock-db-"));
    try {
      const testFile = path.join(tmpDir, "mock_db.test.ts");
      fs.writeFileSync(
        testFile,
        `
it("mocks database driver", () => {
  const db = mock(pg_client);
  assert.ok(db);
});
`
      );
      const findings = checkAntiPatterns(testFile);
      const categories = findings.map((f) => f.category);
      assert.ok(categories.includes("mocked_database"));
      assert.ok(findings.some((f) => f.ruleId === "TDD-MOCK-DB-001"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("detects hollow mocks (>8 mock references)", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tdd-hollow-"));
    try {
      const testFile = path.join(tmpDir, "hollow.test.ts");
      const lines = ["it('heavy mock test', () => {"];
      for (let i = 0; i < 10; i++) {
        lines.push(`  const mock${i} = mockFn();`);
      }
      lines.push("  assert.ok(mock0);");
      lines.push("});");
      fs.writeFileSync(testFile, lines.join("\n"));
      const findings = checkAntiPatterns(testFile);
      const categories = findings.map((f) => f.category);
      assert.ok(categories.includes("hollow_mock"));
      assert.ok(findings.some((f) => f.ruleId === "TDD-MOCK-001"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("passes clean test files without anti-patterns", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tdd-clean-"));
    try {
      const testFile = path.join(tmpDir, "clean.test.ts");
      fs.writeFileSync(
        testFile,
        `
it("asserts public outcome", () => {
  const svc = new UserService();
  const res = svc.register("alice");
  assert.equal(res.isActive, true);
});
`
      );
      const findings = checkAntiPatterns(testFile);
      assert.equal(findings.length, 0);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("fails auditTDD on test parity when production files changed with 0 test files", () => {
    const files = ["src/billing/engine.ts", "src/billing/invoices.ts"];
    const result = auditTDD(files, undefined, true);
    assert.equal(result.passed, false);
    assert.equal(result.untestedFiles.length, 2);
    assert.ok(result.findings.some((f) => f.ruleId === "TDD-PAR-001"));
  });

  it("passes auditTDD on test parity when tests are present", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "tdd-parity-"));
    try {
      const testPath = path.join(tmpDir, "engine.test.ts");
      fs.writeFileSync(
        testPath,
        `
it("tests engine", () => {
  assert.equal(1, 1);
});
`
      );
      const files = ["src/billing/engine.ts", testPath];
      const result = auditTDD(files, undefined, true);
      assert.equal(result.passed, true);
      assert.equal(result.untestedFiles.length, 0);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("trims test receipts down to failure traces and summaries", () => {
    const rawLines: string[] = [];
    for (let i = 0; i < 50; i++) {
      rawLines.push(`Compiling package dependency #${i}...`);
    }
    rawLines.push("FAILED tests/payment.test.ts::test_charge - AssertionError: expected 200 got 500");
    rawLines.push("Error: expected 200 got 500");
    rawLines.push("    at Object.<anonymous> (payment.test.ts:22:12)");
    rawLines.push("=================== 1 failed, 24 passed in 1.42s ===================");

    const trimmed = trimTestReceipt(rawLines.join("\n"));
    assert.ok(trimmed.includes("TDD Receipt Trimmer: Compact Output"));
    assert.ok(trimmed.includes("### 🔴 Failure Trace:"));
    assert.ok(trimmed.includes("AssertionError: expected 200 got 500"));
    assert.ok(trimmed.includes("### 📊 Test Suite Summary:"));
    assert.ok(!trimmed.includes("Compiling package dependency #10..."));
  });

  it("audits git diff to detect test weakening (assertions removed)", () => {
    const diffText = `
diff --git a/tests/user.test.ts b/tests/user.test.ts
index 1234567..89abcdef 100644
--- a/tests/user.test.ts
+++ b/tests/user.test.ts
@@ -10,4 +10,2 @@
-  assert.equal(user.age, 30);
-  assert.equal(user.role, "admin");
+  // weakened test
`;
    const findings = auditTestDiff(diffText);
    assert.equal(findings.length, 1);
    assert.equal(findings[0].category, "test_weakening");
    assert.equal(findings[0].ruleId, "TDD-WEAK-001");
  });

  it("runs CLI in --trim-receipt and --json modes", () => {
    // Trim receipt mode (>40 lines triggers trimming)
    const rawLines = Array.from({ length: 45 }, (_, i) => `Log line #${i}`);
    rawLines.push("FAILED tests/sample.test.ts - AssertionError: expected 1 got 2");
    rawLines.push("Ran 10 tests, 1 failed");
    const stdoutTrim = execFileSync(process.execPath, [SCRIPT_PATH, "--trim-receipt", "-"], {
      input: rawLines.join("\n"),
      encoding: "utf-8",
    });
    assert.ok(stdoutTrim.includes("TDD Receipt Trimmer: Compact Output"));

    // JSON mode on specific files
    const stdoutJson = execFileSync(
      process.execPath,
      [SCRIPT_PATH, "--json", "--files", "tests/fake.test.ts"],
      {
        encoding: "utf-8",
      }
    );
    const parsed = JSON.parse(stdoutJson);
    assert.ok("passed" in parsed);
    assert.ok("findings" in parsed);
  });
});
