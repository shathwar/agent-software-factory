import { describe, it } from "bun:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import {
  isTestFile,
  auditDiff,
  runTestCommand,
  main,
} from "../src/ship/tools/debug.ts";

const SCRIPT_PATH = path.resolve("src/ship/tools/debug.ts");

describe("TypeScript Bugfix Verification & Anti-Cheat Scanner (verify_fix.ts)", () => {
  it("identifies test files correctly", () => {
    assert.equal(isTestFile("tests/test_api.py"), true);
    assert.equal(isTestFile("src/foo_test.go"), true);
    assert.equal(isTestFile("specs/worker.spec.ts"), true);
    assert.equal(isTestFile("tests/unit/calc.test.ts"), true);
    assert.equal(isTestFile("src/engine/worker.py"), false);
    assert.equal(isTestFile("lib/auth.ts"), false);
  });

  it("passes a clean bugfix with production code and a reproduction test", () => {
    const diff = `diff --git a/src/calc.py b/src/calc.py
--- a/src/calc.py
+++ b/src/calc.py
@@ -10,2 +10,2 @@
-    return a / b
+    if b == 0: raise ValueError('Zero division')
+    return a / b
diff --git a/tests/test_calc.py b/tests/test_calc.py
--- a/tests/test_calc.py
+++ b/tests/test_calc.py
@@ -20,2 +20,4 @@
+def test_calc_zero_division():
+    with pytest.raises(ValueError):
+        calc(1, 0)
`;
    const result = auditDiff(diff);
    assert.equal(result.passed, true);
    assert.equal(result.reproTestFound, true);
    assert.equal(result.violations.length, 0);
    assert.equal(result.prodFilesModified.length, 1);
    assert.equal(result.testFilesModified.length, 1);
  });

  it("fails when production code is modified without a reproduction test", () => {
    const diff = `diff --git a/src/calc.py b/src/calc.py
--- a/src/calc.py
+++ b/src/calc.py
@@ -10,2 +10,2 @@
-    return a / b
+    return a / max(b, 1)
`;
    const result = auditDiff(diff);
    assert.equal(result.passed, false);
    assert.equal(result.reproTestFound, false);
    assert.ok(result.violations.some((v) => v.includes("Reproduction Mandate Violation")));
  });

  it("detects symptom masking (swallowed exceptions & empty catch)", () => {
    const diffPy = `diff --git a/src/service.py b/src/service.py
--- a/src/service.py
+++ b/src/service.py
@@ -10,2 +10,4 @@
+    except Exception: pass
`;
    const resPy = auditDiff(diffPy);
    assert.ok(resPy.violations.some((v) => v.includes("Symptom Masking Anti-Pattern")));

    const diffTs = `diff --git a/src/client.ts b/src/client.ts
--- a/src/client.ts
+++ b/src/client.ts
@@ -10,2 +10,4 @@
+    } catch (e) {}
`;
    const resTs = auditDiff(diffTs);
    assert.ok(resTs.violations.some((v) => v.includes("Symptom Masking Anti-Pattern")));
  });

  it("detects defensive null guards masking root cause unless annotated", () => {
    const diffUnguarded = `diff --git a/src/user.py b/src/user.py
--- a/src/user.py
+++ b/src/user.py
@@ -10,2 +10,3 @@
+    if user is None: return None
`;
    const resUnguarded = auditDiff(diffUnguarded);
    assert.ok(resUnguarded.violations.some((v) => v.includes("Defensive null guard")));

    // Annotated guard passes symptom masking check
    const diffAnnotated = `diff --git a/src/user.py b/src/user.py
--- a/src/user.py
+++ b/src/user.py
@@ -10,2 +10,3 @@
+    if user is None: return None  # root-cause-guard
diff --git a/tests/test_user.py b/tests/test_user.py
--- a/tests/test_user.py
+++ b/tests/test_user.py
@@ -10,2 +10,3 @@
+def test_none(): assert True == False
`;
    const resAnnotated = auditDiff(diffAnnotated);
    assert.ok(!resAnnotated.violations.some((v) => v.includes("Defensive null guard")));
  });

  it("detects test weakening (skips and disabled tests)", () => {
    const diff = `diff --git a/tests/test_auth.ts b/tests/test_auth.ts
--- a/tests/test_auth.ts
+++ b/tests/test_auth.ts
@@ -10,2 +10,3 @@
+it.skip("flaky test", () => {});
`;
    const res = auditDiff(diff);
    assert.ok(res.violations.some((v) => v.includes("Test Weakening Violation")));
  });

  it("detects hollow tautological tests", () => {
    const diff = `diff --git a/tests/test_auth.ts b/tests/test_auth.ts
--- a/tests/test_auth.ts
+++ b/tests/test_auth.ts
@@ -10,2 +10,3 @@
+    expect(true).toBe(true);
`;
    const res = auditDiff(diff);
    assert.ok(res.violations.some((v) => v.includes("Hollow Repro Test Violation")));
  });

  it("detects assertion degradation (net deleted assertions with 0 added)", () => {
    const diff = `diff --git a/tests/test_math.ts b/tests/test_math.ts
--- a/tests/test_math.ts
+++ b/tests/test_math.ts
@@ -10,4 +10,1 @@
-    assert.equal(a, 1);
-    assert.equal(b, 2);
`;
    const res = auditDiff(diff);
    assert.ok(res.violations.some((v) => v.includes("Assertion Degradation Violation")));
  });

  it("detects excessive scope creep (>5 prod files or >150 lines)", () => {
    let diff = "";
    for (let i = 0; i < 7; i++) {
      diff += `diff --git a/src/file_${i}.ts b/src/file_${i}.ts\n+++ b/src/file_${i}.ts\n@@ -1 +1 @@\n+const a = 1;\n`;
    }
    diff += `diff --git a/tests/test_foo.ts b/tests/test_foo.ts\n+++ b/tests/test_foo.ts\n@@ -1 +1 @@\n+assert.ok(true);\n`;
    const res = auditDiff(diff);
    assert.ok(res.violations.some((v) => v.includes("Excessive Scope Violation")));
  });

  it("runs CLI on pre-extracted diff file in json and text modes", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "verify-fix-cli-"));
    try {
      const cleanDiff = `diff --git a/src/a.ts b/src/a.ts
--- a/src/a.ts
+++ b/src/a.ts
@@ -1 +1 @@
+const fixed = true;
diff --git a/tests/a.test.ts b/tests/a.test.ts
--- a/tests/a.test.ts
+++ b/tests/a.test.ts
@@ -1 +1 @@
+assert.equal(fixed, true);
`;
      const diffPath = path.join(tmpDir, "patch.diff");
      fs.writeFileSync(diffPath, cleanDiff);

      // JSON format
      const stdoutJson = execFileSync(
        process.execPath,
        [SCRIPT_PATH, "--diff-file", diffPath, "--format", "json"],
        { encoding: "utf-8" }
      );
      const parsed = JSON.parse(stdoutJson);
      assert.equal(parsed.passed, true);
      assert.equal(parsed.reproTestFound, true);

      // Strict failure mode on bad diff
      const badDiffPath = path.join(tmpDir, "bad.diff");
      fs.writeFileSync(badDiffPath, "diff --git a/src/a.ts b/src/a.ts\n+++ b/src/a.ts\n+const x = 1;\n");

      let failed = false;
      try {
        execFileSync(process.execPath, [SCRIPT_PATH, "--diff-file", badDiffPath, "--strict"], {
          encoding: "utf-8",
          stdio: "pipe",
        });
      } catch (err: any) {
        failed = true;
        assert.equal(err.status, 1);
      }
      assert.equal(failed, true, "Expected strict mode to exit with status 1 on violations");
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
