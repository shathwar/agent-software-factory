#!/usr/bin/env node
/**
 * verify_tdd.ts — Deterministic TDD Verification and Anti-Pattern Scanner
 * Zero external dependencies (Node.js 22+ / 25+ standard library).
 *
 * Validates:
 * 1. Test-to-Production Parity: Ensures production code changes have corresponding test changes.
 * 2. TDD Anti-Patterns: Detects assertless tests, excessive mocking, and private member inspection.
 * 3. Test Receipt Trimmer: Extracts clean, token-efficient failure stack traces and summaries.
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { execFileSync } from "node:child_process";

export const CODE_EXTENSIONS = new Set([
  ".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".cs",
  ".cpp", ".c", ".cc", ".cxx", ".h", ".hpp", ".hxx", ".swift", ".scala", ".dart", ".php", ".mjs", ".cjs"
]);

export const TEST_FILE_PATTERNS = [
  /(?:^|[\\/])(?:test|tests|spec|specs)[\\/]/,
  /[_.-](?:test|spec)\.[a-zA-Z0-9]+$/,
  /(?:^|[\\/])test_[a-zA-Z0-9_]+\.[a-zA-Z0-9]+$/,
];

export const EXCLUDE_PATH_PATTERNS = [
  /(?:^|[\\/])(?:\.git|\.agentflow|\.scratch|scratch|\.github|docs|dist|build|node_modules|venv|\.venv)[\\/]/,
  /\.(?:md|json|yml|yaml|toml|ini|cfg|txt|sql|html|css|scss|svg|png|jpg)$/,
];

export const TYPE_DEFINITION_PATTERNS = [
  /\.d\.ts$/,
  /(?:^|[\\/])(?:types|interfaces|dtos)[\\/].*\.(?:ts|js|py|go|rs|cs|java|kt)$/,
  /(?:^|[\\/])(?:types|interfaces|enums|dtos)\.(?:ts|js|py|go|rs|cs|java|kt)$/,
  /\.(?:types|dto|interface|schema)\.[a-zA-Z0-9]+$/,
  /(?:^|[\\/])(?:schema\.prisma|\.graphqls?|\.proto)$/,
];

export class GitDiscoveryError extends Error {}

export interface Finding {
  category: string;
  file: string;
  line: number;
  message: string;
  severity: "ERROR" | "WARNING";
  ruleId: string;
}

export interface TDDCheckResult {
  passed: boolean;
  productionFiles: string[];
  testFiles: string[];
  untestedFiles: string[];
  findings: Finding[];
  error?: string | null;
}

export function isTestFile(filePath: string): boolean {
  const normalized = filePath.replace(/\\/g, "/");
  return TEST_FILE_PATTERNS.some((p) => p.test(normalized));
}

export function isExcluded(filePath: string): boolean {
  const normalized = filePath.replace(/\\/g, "/");
  return EXCLUDE_PATH_PATTERNS.some((p) => p.test(normalized));
}

export function isTypeDefinition(filePath: string): boolean {
  const normalized = filePath.replace(/\\/g, "/");
  return TYPE_DEFINITION_PATTERNS.some((p) => p.test(normalized));
}

export function isProductionCode(filePath: string): boolean {
  if (isExcluded(filePath) || isTestFile(filePath) || isTypeDefinition(filePath)) {
    return false;
  }
  const ext = path.extname(filePath).toLowerCase();
  return CODE_EXTENSIONS.has(ext);
}

export function getChangedFiles(refRange?: string, repoRoot?: string): string[] {
  const root = repoRoot ?? process.cwd();
  try {
    const files: string[] = [];
    if (refRange) {
      const out = execFileSync("git", ["diff", "--name-only", refRange], {
        cwd: root,
        encoding: "utf-8",
      });
      for (const line of out.split(/\r?\n/)) {
        const trimmed = line.trim();
        if (trimmed && !files.includes(trimmed)) {
          files.push(trimmed);
        }
      }
    } else {
      let hasHead = false;
      try {
        execFileSync("git", ["rev-parse", "--verify", "HEAD"], {
          cwd: root,
          stdio: "ignore",
        });
        hasHead = true;
      } catch {
        hasHead = false;
      }

      if (hasHead) {
        const out = execFileSync("git", ["diff", "--name-only", "HEAD"], {
          cwd: root,
          encoding: "utf-8",
        });
        for (const line of out.split(/\r?\n/)) {
          const trimmed = line.trim();
          if (trimmed && !files.includes(trimmed)) {
            files.push(trimmed);
          }
        }
      } else {
        const staged = execFileSync("git", ["diff", "--name-only", "--cached"], {
          cwd: root,
          encoding: "utf-8",
        });
        const unstaged = execFileSync("git", ["diff", "--name-only"], {
          cwd: root,
          encoding: "utf-8",
        });
        for (const line of (staged + "\n" + unstaged).split(/\r?\n/)) {
          const trimmed = line.trim();
          if (trimmed && !files.includes(trimmed)) {
            files.push(trimmed);
          }
        }
      }
    }

    const untracked = execFileSync("git", ["ls-files", "--others", "--exclude-standard"], {
      cwd: root,
      encoding: "utf-8",
    });
    for (const line of untracked.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (trimmed && !files.includes(trimmed)) {
        files.push(trimmed);
      }
    }

    return files;
  } catch (err: any) {
    const msg = err.stderr ? err.stderr.trim() : err.message;
    throw new GitDiscoveryError(`Could not inspect changes: ${msg}`);
  }
}

export function checkAntiPatterns(filePath: string): Finding[] {
  const resolved = path.resolve(filePath);
  if (!fs.existsSync(resolved) || !fs.statSync(resolved).isFile()) {
    return [];
  }

  let content = "";
  try {
    content = fs.readFileSync(resolved, "utf-8");
  } catch {
    return [];
  }

  const findings: Finding[] = [];
  const lines = content.split(/\r?\n/);

  let inTestFunc = false;
  let currentFuncName = "";
  let currentFuncLine = 0;
  let funcHasAssertion = false;
  let mockCount = 0;

  const assertionPattern = /(?:\bassert(?:_|\b)|\.assert|self\.assert|expect\s*\(|\.toBe|\.toEqual|\.toThrow|\.toHave|pytest\.(?:raises|warns)|t\.Error|t\.Fatal|require\.)/;
  const testDefPattern = /^\s*(?:(?:async\s+)?def\s+(test_[a-zA-Z0-9_]+)|func\s+(Test[a-zA-Z0-9_]+)|(?:async\s+)?fn\s+(test_[a-zA-Z0-9_]+)|(?:it|test)(?:\.[a-zA-Z0-9_]+)?\s*\(\s*[`'"]([^`'"]+)[`'"])/;
  const privateAccessPattern = /\b[a-zA-Z0-9_]+\._[a-zA-Z0-9][a-zA-Z0-9_]*\b/g;
  const mockPattern = /(?:\b|_)(?:mock\w*|patch\w*|magicmock|spyon|sinon|gomock)\b/gi;
  const dbMockPattern = /(?:patch|mock)\w*\(.*(?:psycopg|sqlite3|mysql|pg_client|postgres|redis|ioredis|prisma|sqlalchemy|cursor)/i;
  const tautologicalPattern = /\bassert\s+True\b|\bassertTrue\(\s*True\s*\)|\bexpect\(\s*true\s*\)\.toBe\(\s*true\s*\)|\bassert(?:\.strictEqual|\.equal|\.deepEqual)?\(\s*true\s*,\s*true\s*\)/i;

  for (let i = 0; i < lines.length; i++) {
    const lineNum = i + 1;
    const line = lines[i];
    const stripped = line.trim();

    if (stripped.startsWith("#") || stripped.startsWith("//") || stripped.startsWith("/*") || stripped.startsWith("*")) {
      continue;
    }

    if (dbMockPattern.test(line)) {
      findings.push({
        category: "mocked_database",
        file: filePath,
        line: lineNum,
        message: "Mocking of database engine/client detected. Violates Tier 2 Dual-Speed Rule: use ephemeral SQLite/containers.",
        severity: "ERROR",
        ruleId: "TDD-MOCK-DB-001",
      });
    }

    if (tautologicalPattern.test(line)) {
      findings.push({
        category: "tautological_assertion",
        file: filePath,
        line: lineNum,
        message: "Tautological assertion ('assert True' / 'expect(true).toBe(true)') detected. Tests must assert actual observable behavior.",
        severity: "ERROR",
        ruleId: "TDD-TAUT-001",
      });
    }

    const privateMatches = line.match(privateAccessPattern);
    if (privateMatches) {
      const legit = privateMatches.filter((m) => !m.startsWith("self._") && !m.startsWith("this._") && !(m.endsWith("__") && m.includes(".__")));
      if (legit.length > 0) {
        findings.push({
          category: "whitebox_spy",
          file: filePath,
          line: lineNum,
          message: `Test directly inspects private member(s) (${legit.join(", ")}). Assert on observable public outcomes instead.`,
          severity: "WARNING",
          ruleId: "TDD-SPY-001",
        });
      }
    }

    const mockMatches = line.match(mockPattern);
    if (mockMatches) {
      mockCount += mockMatches.length;
    }

    const testDefMatch = testDefPattern.exec(line);
    if (testDefMatch) {
      if (inTestFunc && !funcHasAssertion) {
        findings.push({
          category: "assertless_test",
          file: filePath,
          line: currentFuncLine,
          message: `Test '${currentFuncName}' contains no detectable assertion. Tests must verify observable behavior.`,
          severity: "ERROR",
          ruleId: "TDD-ASRT-001",
        });
      }
      inTestFunc = true;
      currentFuncName = testDefMatch[1] || testDefMatch[2] || testDefMatch[3] || testDefMatch[4] || "unknown_test";
      currentFuncLine = lineNum;
      funcHasAssertion = false;
    }

    if (inTestFunc && assertionPattern.test(line)) {
      funcHasAssertion = true;
    }
  }

  if (inTestFunc && !funcHasAssertion) {
    findings.push({
      category: "assertless_test",
      file: filePath,
      line: currentFuncLine,
      message: `Test '${currentFuncName}' contains no detectable assertion. Tests must verify observable behavior.`,
      severity: "ERROR",
      ruleId: "TDD-ASRT-001",
    });
  }

  if (mockCount > 8) {
    findings.push({
      category: "hollow_mock",
      file: filePath,
      line: 1,
      message: `Test file contains ${mockCount} mock/spy references. High risk of testing mock setup rather than domain behavior. Prefer in-memory fakes or ephemeral databases.`,
      severity: "WARNING",
      ruleId: "TDD-MOCK-001",
    });
  }

  return findings;
}

export function auditTDD(files: string[], repoRoot?: string, strict: boolean = false): TDDCheckResult {
  const root = repoRoot ?? process.cwd();
  const prodFiles: string[] = [];
  const testFiles: string[] = [];
  const findings: Finding[] = [];

  for (const f of files) {
    if (isProductionCode(f)) {
      prodFiles.push(f);
    } else if (isTestFile(f)) {
      testFiles.push(f);
    }
  }

  const untestedFiles: string[] = [];
  if (prodFiles.length > 0 && testFiles.length === 0) {
    for (const p of prodFiles) {
      untestedFiles.push(p);
      findings.push({
        category: "test_parity",
        file: p,
        line: 1,
        message: "Production logic modified with ZERO test changes in the changeset. Enforce the Iron Law of Test-First.",
        severity: "ERROR",
        ruleId: "TDD-PAR-001",
      });
    }
  }

  for (const t of testFiles) {
    const p = path.isAbsolute(t) ? t : path.join(root, t);
    findings.push(...checkAntiPatterns(p));
  }

  const hasErrors = findings.some((f) => f.severity === "ERROR");
  const passed = strict ? !hasErrors : true;

  return {
    passed,
    productionFiles: prodFiles,
    testFiles,
    untestedFiles,
    findings,
  };
}

export function trimTestReceipt(rawOutput: string, maxLines: number = 40): string {
  const lines = rawOutput.split(/\r?\n/);
  if (lines.length <= maxLines) {
    return rawOutput;
  }

  const failureLines: string[] = [];
  const summaryLines: string[] = [];
  let captureFailure = false;

  const failureMarkers = /(?:\b(?:FAIL|FAILED|ERROR|AssertionError|panic)\b|\bException:)/i;
  const summaryMarkers = /(?:passed|failed|skipped|total|Ran \d+ tests|Tests:|ok\b)/i;

  for (const line of lines) {
    if (summaryMarkers.test(line)) {
      summaryLines.append ? summaryLines.push(line) : summaryLines.push(line);
      captureFailure = false;
    } else if (failureMarkers.test(line)) {
      captureFailure = true;
      failureLines.push(line);
      if (failureLines.length >= 25) {
        captureFailure = false;
      }
    } else if (captureFailure) {
      failureLines.push(line);
      if (failureLines.length >= 25) {
        captureFailure = false;
      }
    }
  }

  const trimmed: string[] = [
    "--- [TDD Receipt Trimmer: Compact Output] ---",
    `Original log: ${lines.length} lines -> Trimmed to key failure points & summary:`,
    "",
  ];
  if (failureLines.length > 0) {
    trimmed.push("### 🔴 Failure Trace:");
    trimmed.push(...failureLines.slice(0, 25));
    trimmed.push("");
  }
  if (summaryLines.length > 0) {
    trimmed.push("### 📊 Test Suite Summary:");
    trimmed.push(...summaryLines.slice(-5));
  } else {
    trimmed.push(...lines.slice(-10));
  }

  return trimmed.join("\n");
}

export function auditTestDiff(diffText: string): Finding[] {
  const findings: Finding[] = [];
  const lines = diffText.split(/\r?\n/);

  let currentFile = "";
  let inTestFile = false;
  let deletedAsserts = 0;
  let addedAsserts = 0;

  const assertKw = /(?:\bassert(?:_|\b)|\.assert|self\.assert|expect\(|\.toBe|\.toEqual)/i;

  for (const line of lines) {
    if (line.startsWith("diff --git")) {
      if (inTestFile && deletedAsserts > addedAsserts) {
        findings.push({
          category: "test_weakening",
          file: currentFile,
          line: 1,
          message: `Test weakening detected in '${currentFile}': ${deletedAsserts} assertion(s) removed but only ${addedAsserts} added. Do not weaken tests to pass faulty implementations.`,
          severity: "ERROR",
          ruleId: "TDD-WEAK-001",
        });
      }
      deletedAsserts = 0;
      addedAsserts = 0;
      const parts = line.split(/\s+/);
      currentFile = parts.length >= 4 ? parts[parts.length - 1].replace(/^b\//, "") : "unknown";
      inTestFile = isTestFile(currentFile);
    } else if (inTestFile) {
      if (line.startsWith("-") && !line.startsWith("---")) {
        if (assertKw.test(line)) {
          deletedAsserts++;
        }
      } else if (line.startsWith("+") && !line.startsWith("+++")) {
        if (assertKw.test(line)) {
          addedAsserts++;
        }
      }
    }
  }

  if (inTestFile && deletedAsserts > addedAsserts) {
    findings.push({
      category: "test_weakening",
      file: currentFile,
      line: 1,
      message: `Test weakening detected in '${currentFile}': ${deletedAsserts} assertion(s) removed but only ${addedAsserts} added. Do not weaken tests to pass faulty implementations.`,
      severity: "ERROR",
      ruleId: "TDD-WEAK-001",
    });
  }

  return findings;
}

export function verifyTDD(
  refRange?: string,
  files?: string[],
  repoRoot?: string,
  strict: boolean = false
): TDDCheckResult {
  try {
    const filesToCheck = files && files.length > 0 ? files : getChangedFiles(refRange, repoRoot);
    return auditTDD(filesToCheck, repoRoot, strict);
  } catch (err: any) {
    return {
      passed: false,
      productionFiles: [],
      testFiles: [],
      untestedFiles: [],
      findings: [
        {
          category: "git_discovery",
          file: "git",
          line: 1,
          message: err.message,
          severity: "ERROR",
          ruleId: "TDD-GIT-001",
        },
      ],
      error: err.message,
    };
  }
}

export function main(argv: string[] = process.argv.slice(2)): number {
  let refRange: string | undefined;
  const files: string[] = [];
  let strict = false;
  let jsonOutput = false;
  let trimReceiptPath: string | undefined;
  let auditDiffPath: string | undefined;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--ref-range") {
      refRange = argv[++i];
    } else if (arg.startsWith("--ref-range=")) {
      refRange = arg.split("=")[1];
    } else if (arg === "--files") {
      while (i + 1 < argv.length && !argv[i + 1].startsWith("-")) {
        files.push(argv[++i]);
      }
    } else if (arg === "--strict") {
      strict = true;
    } else if (arg === "--json") {
      jsonOutput = true;
    } else if (arg === "--trim-receipt") {
      trimReceiptPath = argv[++i];
    } else if (arg.startsWith("--trim-receipt=")) {
      trimReceiptPath = arg.split("=")[1];
    } else if (arg === "--audit-diff") {
      auditDiffPath = argv[++i];
    } else if (arg.startsWith("--audit-diff=")) {
      auditDiffPath = arg.split("=")[1];
    }
  }

  if (trimReceiptPath) {
    const raw = trimReceiptPath === "-" ? fs.readFileSync(0, "utf-8") : fs.readFileSync(trimReceiptPath, "utf-8");
    console.log(trimTestReceipt(raw));
    return 0;
  }

  if (auditDiffPath) {
    const rawDiff = auditDiffPath === "-" ? fs.readFileSync(0, "utf-8") : fs.readFileSync(auditDiffPath, "utf-8");
    const diffFindings = auditTestDiff(rawDiff);
    if (jsonOutput) {
      console.log(JSON.stringify(diffFindings, null, 2));
    } else {
      console.log(`Test Diff Weakening Audit: ${diffFindings.length === 0 ? "PASSED" : "FAILED"}`);
      for (const f of diffFindings) {
        console.log(`  • [${f.severity}] ${f.file}: ${f.message}`);
      }
    }
    return diffFindings.length > 0 ? 1 : 0;
  }

  let result: TDDCheckResult;
  try {
    const filesToCheck = files.length > 0 ? files : getChangedFiles(refRange);
    result = auditTDD(filesToCheck, undefined, strict);
  } catch (err: any) {
    result = {
      passed: false,
      productionFiles: [],
      testFiles: [],
      untestedFiles: [],
      findings: [
        {
          category: "git_discovery",
          file: "git",
          line: 1,
          message: err.message,
          severity: "ERROR",
          ruleId: "TDD-GIT-001",
        },
      ],
      error: err.message,
    };
  }

  if (jsonOutput) {
    console.log(JSON.stringify(result, null, 2));
    return result.passed ? 0 : 1;
  }

  console.log("==================================================");
  console.log("  TDD Audit & Verification Report");
  console.log("==================================================");
  console.log(`Production files changed : ${result.productionFiles.length}`);
  console.log(`Test files changed       : ${result.testFiles.length}`);
  console.log(`Untested production files: ${result.untestedFiles.length}`);
  console.log("--------------------------------------------------");

  if (result.findings.length === 0) {
    console.log("✅ PASS: Clean TDD parity. No anti-patterns detected.");
    return 0;
  }

  for (const f of result.findings) {
    const icon = f.severity === "ERROR" ? "❌" : "⚠️";
    console.log(`${icon} [${f.severity}] ${f.file}:${f.line} (${f.category})`);
    console.log(`   ${f.message}`);
  }

  console.log("--------------------------------------------------");
  if (!result.passed) {
    console.log("❌ FAILED: Strict TDD violations detected. Fix errors before advancing.");
    return 1;
  } else {
    console.log("⚠️ COMPLETED with warnings. Review findings before advancing.");
    return 0;
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const exitCode = main();
  process.exit(exitCode);
}
