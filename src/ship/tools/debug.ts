#!/usr/bin/env node
/**
 * verify_fix.ts — Deterministic Bugfix Verification and Anti-Cheat Scanner.
 *
 * Audits bugfix diffs for:
 * 1. Reproduction Test Parity: Ensures a reproduction test is included in the diff.
 * 2. Anti-Cheat: Detects weakened, skipped, or deleted test assertions.
 * 3. Anti-Pattern Masking: Detects swallowed exceptions, bare except blocks, and defensive null guards masking root causes.
 * 4. Test Suite Execution: Optionally runs the test runner and verifies exit status 0.
 *
 * Zero external dependencies (Node.js 22+ / 25+ standard library).
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { execSync } from "node:child_process";

export const TEST_FILE_PATTERNS = [
  /(?:^|[\\/])(?:test|tests|spec|specs)[\\/]/,
  /[_.-](?:test|spec)\.[a-zA-Z0-9]+$/,
  /(?:^|[\\/])test_[a-zA-Z0-9_]+\.[a-zA-Z0-9]+$/,
];

export const TEST_WEAKENING_PATTERNS: [RegExp, string][] = [
  [/^\+\s*@pytest\.mark\.skip/, "Added @pytest.mark.skip decorator."],
  [/^\+\s*@pytest\.mark\.xfail/, "Added @pytest.mark.xfail decorator."],
  [/^\+\s*@unittest\.skip/, "Added @unittest.skip decorator."],
  [/^\+\s*@unittest\.expectedFailure/, "Added @unittest.expectedFailure decorator."],
  [/^\+\s*(?:it|test|describe)\.skip/, "Added skip to test runner."],
  [/^\+\s*xit\(/, "Added disabled xit() test block."],
  [/^\+\s*xdescribe\(/, "Added disabled xdescribe() suite block."],
  [/^\+\s*\/\/\s*(?:expect|assert)/, "Commented out test assertion."],
  [/^\+\s*#\s*self\.assert/, "Commented out unittest assertion."],
  [/^\+\s*#\s*assert /, "Commented out pytest assertion."],
];

export const TAUTOLOGICAL_TEST_PATTERNS: [RegExp, string][] = [
  [/^\+\s*assert\s+(?:True|1\s*==\s*1)\b/, "Hollow tautological assertion ('assert True')."],
  [/^\+\s*self\.assertTrue\(\s*True\s*\)/, "Hollow tautological assertion ('self.assertTrue(True)')."],
  [/^\+\s*expect\(\s*true\s*\)\.toBe\(\s*true\s*\)/, "Hollow tautological assertion ('expect(true).toBe(true)')."],
];

export const DEFENSIVE_NULL_GUARD_PATTERNS: [RegExp, string][] = [
  [/^\+\s*if\s+\w+\s+is\s+None\s*:\s*return(?:\s+None)?\s*(?:#.*)?$/, "Defensive null guard returning early at point of impact."],
  [/^\+\s*if\s+not\s+\w+\s*:\s*return(?:\s+None)?\s*(?:#.*)?$/, "Defensive guard returning early at point of impact."],
  [/^\+\s*if\s*\(\s*(?:!\w+|\w+\s*===\s*null|\w+\s*===\s*undefined)\s*\)\s*return(?:\s+null|\s+undefined)?\s*;?/, "Defensive null guard returning early at point of impact."],
];

export const SYMPTOM_MASKING_PATTERNS: [RegExp, string][] = [
  [/^\+\s*except\s*:\s*pass\b/, "Bare 'except: pass' swallows exceptions silently."],
  [/^\+\s*except\s+Exception\s*:\s*pass\b/, "Swallowed 'except Exception: pass' masks root cause."],
  [/^\+\s*catch\s*\([^)]*\)\s*\{\s*\}/, "Empty catch block swallows errors silently."],
  [/^\+\s*catch\s*\{\s*\}/, "Empty catch block swallows errors silently."],
];

export const MULTILINE_SYMPTOM_MASKING_PATTERNS: [RegExp, string][] = [
  [/except(?:\s+[\w\.]+)?\s*:\s*(?:\r?\n\s*(?:#[^\n]*)?)*\r?\n\s*pass\b/m, "Swallowed exception with pass masks root cause."],
  [/catch\s*(?:\([^)]*\))?\s*\{(?:\s*|\s*\/\/[^\n]*\s*|\s*\/\*[\s\S]*?\*\/\s*)*\}/, "Empty catch block swallows errors silently."],
];

export interface BugfixAuditResult {
  passed: boolean;
  reproTestFound: boolean;
  violations: string[];
  testFilesModified: string[];
  prodFilesModified: string[];
}

export function isTestFile(pathStr: string): boolean {
  const normalized = pathStr.replace(/\\/g, "/");
  return TEST_FILE_PATTERNS.some((pat) => pat.test(normalized));
}

export function getGitDiff(repoRoot: string, baseRef: string = "HEAD"): string {
  try {
    let diffOut = "";
    try {
      diffOut = execSync(`git diff ${baseRef}`, {
        cwd: repoRoot,
        encoding: "utf-8",
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (e: any) {
      throw new Error(e.stderr ? e.stderr.trim() : "git diff failed");
    }

    let untrackedDiff = "";
    try {
      const statusOut = execSync("git status --porcelain", {
        cwd: repoRoot,
        encoding: "utf-8",
        stdio: ["ignore", "pipe", "pipe"],
      });
      for (const line of statusOut.split(/\r?\n/)) {
        if (line.startsWith("?? ")) {
          const relPath = line.slice(3).trim();
          const p = path.join(repoRoot, relPath);
          if (fs.existsSync(p) && fs.statSync(p).isFile()) {
            try {
              const content = fs.readFileSync(p, "utf-8");
              untrackedDiff += `\ndiff --git a/${relPath} b/${relPath}\nnew file mode 100644\n--- /dev/null\n+++ b/${relPath}\n`;
              for (const cLine of content.split(/\r?\n/)) {
                untrackedDiff += `+${cLine}\n`;
              }
            } catch {}
          }
        }
      }
    } catch {}

    const combined = (diffOut + untrackedDiff).trim();
    if (combined) {
      return combined;
    }

    // Fallback to last commit if working tree is clean
    try {
      return execSync("git diff HEAD~1...HEAD", {
        cwd: repoRoot,
        encoding: "utf-8",
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch {
      return "";
    }
  } catch (err: any) {
    throw new Error(`Failed to execute git diff: ${err.message}`);
  }
}

export function auditDiff(diffText: string): BugfixAuditResult {
  const testFiles: string[] = [];
  const prodFiles: string[] = [];
  const violations: string[] = [];

  let currentFile = "";
  let isCurrentTest = false;
  let deletedAssertionsCount = 0;
  let addedAssertionsCount = 0;
  let totalProdLinesAdded = 0;
  const fileAddedLines: Record<string, string[]> = {};

  const lines = diffText.split(/\r?\n/);
  for (const line of lines) {
    if (line.startsWith("diff --git ")) {
      const parts = line.split(" ");
      if (parts.length >= 4) {
        const pathRaw = parts[3].replace(/^b\//, "");
        currentFile = pathRaw;
        isCurrentTest = isTestFile(currentFile);
        if (isCurrentTest) {
          if (!testFiles.includes(currentFile)) {
            testFiles.push(currentFile);
          }
        } else {
          if (!prodFiles.includes(currentFile)) {
            prodFiles.push(currentFile);
          }
        }
      }
      continue;
    }

    if (!currentFile) {
      continue;
    }

    // Check symptom masking in production files
    if (!isCurrentTest) {
      for (const [pat, desc] of SYMPTOM_MASKING_PATTERNS) {
        if (pat.test(line)) {
          violations.push(`[${currentFile}] Symptom Masking Anti-Pattern: ${desc}`);
        }
      }
      for (const [pat, desc] of DEFENSIVE_NULL_GUARD_PATTERNS) {
        if (pat.test(line) && !line.includes("root-cause-guard")) {
          violations.push(`[${currentFile}] Symptom Masking Anti-Pattern: ${desc}`);
        }
      }
      if (line.startsWith("+") && !line.startsWith("+++")) {
        totalProdLinesAdded++;
        if (!fileAddedLines[currentFile]) {
          fileAddedLines[currentFile] = [];
        }
        fileAddedLines[currentFile].push(line.slice(1));
      }
    }

    // Check test weakening in test files
    if (isCurrentTest) {
      for (const [pat, desc] of TEST_WEAKENING_PATTERNS) {
        if (pat.test(line)) {
          violations.push(
            `[${currentFile}] Test Weakening Violation: Added test skip or commented-out assertion: ${line.trim()}`
          );
        }
      }
      for (const [pat, desc] of TAUTOLOGICAL_TEST_PATTERNS) {
        if (pat.test(line)) {
          violations.push(`[${currentFile}] Hollow Repro Test Violation: ${desc}`);
        }
      }

      // Track assertions
      if (line.startsWith("-") && !line.startsWith("---")) {
        if (/\bassert\b|\bexpect\(|self\.assert/.test(line)) {
          deletedAssertionsCount++;
        }
      } else if (line.startsWith("+") && !line.startsWith("+++")) {
        if (/\bassert\b|\bexpect\(|self\.assert/.test(line)) {
          addedAssertionsCount++;
        }
      }
    }
  }

  // Check multiline symptom masking
  for (const [pFile, addedLines] of Object.entries(fileAddedLines)) {
    const addedText = addedLines.join("\n");
    for (const [pat, desc] of MULTILINE_SYMPTOM_MASKING_PATTERNS) {
      if (pat.test(addedText)) {
        const msg = `[${pFile}] Symptom Masking Anti-Pattern: ${desc}`;
        if (!violations.includes(msg)) {
          violations.push(msg);
        }
      }
    }
  }

  const reproTestFound = testFiles.length > 0;

  if (!reproTestFound && prodFiles.length > 0) {
    violations.push("Reproduction Mandate Violation: Production code modified without a reproduction test in tests/.");
  }

  // Flag net loss of assertions across test files
  if (deletedAssertionsCount > addedAssertionsCount && addedAssertionsCount === 0) {
    violations.push(
      `Assertion Degradation Violation: ${deletedAssertionsCount} assertions deleted with 0 added.`
    );
  }

  // Flag excessive scope creep
  if (prodFiles.length > 5 || totalProdLinesAdded > 150) {
    violations.push(
      `Excessive Scope Violation: Bugfix diff modified ${prodFiles.length} production files (${totalProdLinesAdded} lines added). Violates surgical repair constraint (laziness ladder).`
    );
  }

  const passed = violations.length === 0;

  return {
    passed,
    reproTestFound,
    violations,
    testFilesModified: testFiles,
    prodFilesModified: prodFiles,
  };
}

export function runTestCommand(testCmd: string, cwd: string): [boolean, string] {
  try {
    const out = execSync(testCmd, {
      cwd,
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    return [true, out.trim()];
  } catch (err: any) {
    const out = ((err.stdout || "") + "\n" + (err.stderr || "")).trim();
    return [false, out || err.message];
  }
}

export function main(argv: string[] = process.argv.slice(2)): number {
  let repoPath = ".";
  let diffFile: string | undefined;
  let baseRef = "HEAD";
  let testCmd: string | undefined;
  let format: "text" | "json" = "text";
  let strict = false;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--path") {
      repoPath = argv[++i];
    } else if (arg.startsWith("--path=")) {
      repoPath = arg.split("=")[1];
    } else if (arg === "--diff-file") {
      diffFile = argv[++i];
    } else if (arg.startsWith("--diff-file=")) {
      diffFile = arg.split("=")[1];
    } else if (arg === "--base") {
      baseRef = argv[++i];
    } else if (arg.startsWith("--base=")) {
      baseRef = arg.split("=")[1];
    } else if (arg === "--test-cmd") {
      testCmd = argv[++i];
    } else if (arg.startsWith("--test-cmd=")) {
      testCmd = arg.split("=")[1];
    } else if (arg === "--format") {
      const next = argv[++i];
      if (next === "json" || next === "text") {
        format = next;
      }
    } else if (arg.startsWith("--format=")) {
      const val = arg.split("=")[1];
      if (val === "json" || val === "text") {
        format = val;
      }
    } else if (arg === "--strict") {
      strict = true;
    }
  }

  const repoRoot = path.resolve(repoPath);
  let diffText = "";

  if (diffFile && fs.existsSync(diffFile)) {
    diffText = fs.readFileSync(diffFile, "utf-8");
  } else {
    try {
      diffText = getGitDiff(repoRoot, baseRef);
    } catch (err: any) {
      process.stderr.write(`Error reading git diff: ${err.message}\n`);
      return 1;
    }
  }

  const audit = auditDiff(diffText);
  let testRunPassed = true;
  let testOutput = "";

  if (testCmd) {
    const [passed, output] = runTestCommand(testCmd, repoRoot);
    testRunPassed = passed;
    testOutput = output;
    if (!testRunPassed) {
      audit.violations.push(`Test Execution Failed: '${testCmd}' exited non-zero.`);
      audit.passed = false;
    }
  }

  if (format === "json") {
    const data: Record<string, any> = { ...audit };
    if (testCmd) {
      data.testCmdPassed = testRunPassed;
      data.testOutputTail = testOutput.split(/\r?\n/).slice(-20).join("\n");
    }
    console.log(JSON.stringify(data, null, 2));
  } else {
    console.log("## 🛠️ Bugfix Verification & Integrity Audit");
    console.log(`- **Reproduction Test Found**: ${audit.reproTestFound ? "✅ Yes" : "❌ Missing"}`);
    console.log(`- **Modified Tests**: ${audit.testFilesModified.length} files (${audit.testFilesModified.join(", ") || "None"})`);
    console.log(`- **Modified Production Code**: ${audit.prodFilesModified.length} files (${audit.prodFilesModified.join(", ") || "None"})`);

    if (audit.violations.length > 0) {
      console.log("\n### ❌ Audit Violations");
      for (const v of audit.violations) {
        console.log(`- ${v}`);
      }
    } else {
      console.log("\n✅ **CLEAN**: Fix meets reproduction mandate with zero symptom masking or test weakening.");
    }

    if (testCmd) {
      console.log(`\n- **Test Run ('${testCmd}')**: ${testRunPassed ? "✅ PASS" : "❌ FAIL"}`);
    }
  }

  if (strict && !audit.passed) {
    return 1;
  }

  return 0;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const exitCode = main();
  process.exit(exitCode);
}
