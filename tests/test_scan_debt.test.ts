import { describe, it } from "bun:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import {
  parseDebtMarker,
  scanFile,
  scanPaths,
  scanDebt,
  formatTable,
  auditCodeSimplicity,
  auditPathsSimplicity,
  REDUNDANT_DEPENDENCIES,
} from "../src/ship/tools/simplify.ts";

const SCRIPT_PATH = path.resolve("src/ship/tools/simplify.ts");

describe("TypeScript Simplify Debt Scanner (scan_debt.ts)", () => {
  it("parses valid simplify marker", () => {
    const line = "// simplify: In-memory cache. Ceiling: 1,000 items. Upgrade: Redis.";
    const res = parseDebtMarker(line, "src/cache.ts", 42);
    assert.equal(res.isValid, true);
    assert.equal(res.shortcut, "In-memory cache");
    assert.equal(res.ceiling, "1,000 items");
    assert.equal(res.upgrade, "Redis");
    assert.equal(res.file, "src/cache.ts");
    assert.equal(res.line, 42);
    assert.equal(res.errors.length, 0);
  });

  it("supports ponytail marker syntax", () => {
    const line = "// ponytail: In-memory cache. Ceiling: 1,000 items. Upgrade: Redis.";
    const res = parseDebtMarker(line, "src/cache.ts", 42);
    assert.equal(res.isValid, true);
    assert.equal(res.shortcut, "In-memory cache");
    assert.equal(res.ceiling, "1,000 items");
    assert.equal(res.upgrade, "Redis");
  });

  it("supports compact ponytail marker syntax with comma delimiter", () => {
    const line = "# ponytail: global lock, per-account locks if throughput matters";
    const res = parseDebtMarker(line, "src/sync.py", 12);
    assert.equal(res.isValid, true);
    assert.equal(res.shortcut, "global lock");
    assert.equal(res.upgrade, "per-account locks if throughput matters");
  });

  it("detects missing ceiling", () => {
    const line = "# simplify: Simple SQLite. Upgrade: Postgres RDS.";
    const res = parseDebtMarker(line, "db.py", 10);
    assert.equal(res.isValid, false);
    assert.ok(res.errors.includes("Missing 'Ceiling:' threshold"));
  });

  it("detects missing upgrade path", () => {
    const line = "/* simplify: O(N) array filter. Ceiling: 50 users. */";
    const res = parseDebtMarker(line, "users.c", 88);
    assert.equal(res.isValid, false);
    assert.ok(res.errors.includes("Missing 'Upgrade:' path"));
  });

  it("rejects empty ceiling and upgrade values", () => {
    const emptyLine = "// simplify: In-memory store. Ceiling: . Upgrade: .";
    const res = parseDebtMarker(emptyLine, "store.ts", 12);
    assert.equal(res.isValid, false);
    assert.ok(res.errors.includes("Empty 'Ceiling:' threshold"));
    assert.ok(res.errors.includes("Empty 'Upgrade:' path"));
  });

  it("handles pipe-separated format correctly", () => {
    const pipeLine = "// simplify: In-memory store | Ceiling: 500 req/s | Upgrade: Redis cache";
    const res = parseDebtMarker(pipeLine, "store.ts", 20);
    assert.equal(res.isValid, true);
    assert.equal(res.shortcut, "In-memory store");
    assert.equal(res.ceiling, "500 req/s");
    assert.equal(res.upgrade, "Redis cache");
  });

  it("rejects vague shortcut descriptions", () => {
    const line = "// simplify: todo. Ceiling: 100. Upgrade: fix it.";
    const res = parseDebtMarker(line, "app.go", 15);
    assert.equal(res.isValid, false);
    assert.ok(res.errors.some((e) => e.includes("Vague or missing")));
  });

  it("rejects template placeholders like <Shortcut>", () => {
    const templateLine = "// simplify: <Shortcut>. Ceiling: <Threshold/Limit>. Upgrade: <Next Architecture>.";
    const res = parseDebtMarker(templateLine, "syntax.ts", 5);
    assert.equal(res.isValid, false);
    assert.ok(res.errors.some((e) => e.includes("placeholder in shortcut description")));
    assert.ok(res.errors.some((e) => e.includes("placeholder in 'Ceiling:'")));
    assert.ok(res.errors.some((e) => e.includes("placeholder in 'Upgrade:'")));
  });

  it("rejects placeholder ceilings and upgrades like none, N/A, TBD", () => {
    for (const placeholder of ["none", "N/A", "TBD", "todo", "fixme"]) {
      const line1 = `// simplify: Quick cache. Ceiling: ${placeholder}. Upgrade: Redis.`;
      const res1 = parseDebtMarker(line1, "cache.ts", 10);
      assert.equal(res1.isValid, false);
      assert.ok(res1.errors.some((e) => e.includes("Ceiling")));

      const line2 = `// simplify: Quick cache. Ceiling: 1k users. Upgrade: ${placeholder}.`;
      const res2 = parseDebtMarker(line2, "cache.ts", 12);
      assert.equal(res2.isValid, false);
      assert.ok(res2.errors.some((e) => e.includes("Upgrade")));
    }
  });

  it("ignores non-comment strings and code occurrences of simplify:", () => {
    const nonComments = [
      'if ("simplify:" in line.lower()):',
      'const pattern = "simplify:\\s*(.+)$";',
      '│   • Code Refactorer: Simplifies under green; adds simplify: debt markers    │',
      "Scan codebases for simplify: technical debt markers",
      'const markerName = "simplify: custom";',
    ];
    for (const line of nonComments) {
      const res = parseDebtMarker(line, "app.ts", 1);
      assert.deepEqual(res, {} as any);
    }
  });

  it("formats markdown table properly", () => {
    const markers = [
      {
        file: "src/cache.ts",
        line: 10,
        shortcut: "In-memory cache",
        ceiling: "1k items",
        upgrade: "Redis",
        isValid: true,
        errors: [],
        raw: "",
      },
      {
        file: "src/db.ts",
        line: 20,
        shortcut: "SQLite",
        ceiling: "N/A",
        upgrade: "Postgres",
        isValid: false,
        errors: ["Missing 'Ceiling:' threshold"],
        raw: "",
      },
    ];
    const table = formatTable(markers, true);
    assert.ok(table.includes("| Location | Shortcut Taken |"));
    assert.ok(table.includes("`src/cache.ts:10`"));
    assert.ok(table.includes("✅ Valid"));
    assert.ok(table.includes("❌ Invalid: Missing 'Ceiling:' threshold"));
  });

  it("scans files, handles binary and markdown text fences properly", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "scan-debt-ts-"));
    try {
      // 1. Valid file
      const validFile = path.join(tmpDir, "valid.ts");
      fs.writeFileSync(
        validFile,
        "// simplify: Local Map. Ceiling: 5k keys. Upgrade: Memcached.\nexport const map = new Map();\n"
      );

      // 2. Binary file with simplify: string
      const binFile = path.join(tmpDir, "image.png");
      const binBuf = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x00]), Buffer.from("simplify: bad\x00")]);
      fs.writeFileSync(binFile, binBuf);

      // 3. Markdown file with doc fence and header
      const mdFile = path.join(tmpDir, "README.md");
      fs.writeFileSync(
        mdFile,
        "# simplify: Lazy Senior Developer Engine\n```text\n// simplify: <Shortcut>. Ceiling: <Limit>. Upgrade: <Next>.\n```\n```ts\n// simplify: Real shortcut. Ceiling: 50 RPS. Upgrade: Worker pool.\n```\n"
      );

      const markers = scanPaths([tmpDir]);
      const shortcuts = markers.map((m) => m.shortcut);
      assert.ok(shortcuts.includes("Local Map"));
      assert.ok(shortcuts.includes("Real shortcut"));
      assert.ok(!shortcuts.includes("Lazy Senior Developer Engine"));
      assert.ok(!shortcuts.includes("<Shortcut>"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("audits code simplicity for redundant dependencies", () => {
    const tsCode = 'import { v4 } from "uuid";\nimport clone from "lodash.clonedeep";\nimport axios from "axios";\n';
    const findings = auditCodeSimplicity("test.ts", tsCode);
    assert.equal(findings.length, 3);
    assert.ok(findings.every((f) => f.ruleId === "SMP-DEP-001"));
    assert.ok(findings.every((f) => f.severity === "ERROR"));
  });

  it("audits code simplicity for speculative factories and shallow wrappers in TS/JS", () => {
    const tsCode = `
class SvcFactory {
  static create() { return null; }
}

class SvcWrapper {
  private _inner: any;
  constructor(inner: any) { this._inner = inner; }
  a() { return this._inner.a(); }
  b() { return this._inner.b(); }
}
`;
    const findings = auditCodeSimplicity("svc.ts", tsCode);
    const ruleIds = findings.map((f) => f.ruleId);
    assert.ok(ruleIds.includes("SMP-ABS-001"), "Expected SMP-ABS-001 for SvcFactory");
    assert.ok(ruleIds.includes("SMP-WRAP-001"), "Expected SMP-WRAP-001 for SvcWrapper");
  });

  it("runs CLI in normal, json and strict modes", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "scan-debt-cli-"));
    try {
      const validFile = path.join(tmpDir, "valid.ts");
      fs.writeFileSync(
        validFile,
        "// simplify: Mutex lock. Ceiling: 1k RPS. Upgrade: Channel fan-out.\nconst a = 1;\n"
      );

      // JSON mode
      const stdoutJson = execFileSync(process.execPath, [SCRIPT_PATH, "--format", "json", tmpDir], {
        encoding: "utf-8",
      });
      const data = JSON.parse(stdoutJson);
      assert.equal(data.length, 1);
      assert.equal(data[0].isValid, true);
      assert.equal(data[0].ceiling, "1k RPS");

      // Strict failure mode
      const badFile = path.join(tmpDir, "bad.ts");
      fs.writeFileSync(badFile, "// simplify: Bad shortcut without ceiling.\n");

      let failed = false;
      try {
        execFileSync(process.execPath, [SCRIPT_PATH, "--strict", tmpDir], {
          encoding: "utf-8",
          stdio: "pipe",
        });
      } catch (err: any) {
        failed = true;
        assert.equal(err.status, 1);
        assert.ok(err.stderr.includes("invalid debt marker"));
      }
      assert.equal(failed, true, "Expected strict mode to exit with status 1");
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
