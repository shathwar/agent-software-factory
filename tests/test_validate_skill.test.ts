import { describe, it } from "bun:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import {
  scaffoldSkill,
  validateSkillDir,
  main,
} from "../src/ship/tools/skill.ts";

const SCRIPT_PATH = path.resolve("src/ship/tools/skill.ts");

describe("TypeScript Skill Factory Validator & Scaffolder (validate_skill.ts)", () => {
  it("scaffolds and validates a micro skill", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "skill-micro-"));
    try {
      const sdir = scaffoldSkill(tmpDir, "quick-audit", true);
      assert.ok(fs.existsSync(path.join(sdir, "SKILL.md")));
      assert.ok(!fs.existsSync(path.join(sdir, "scripts")));

      const res = validateSkillDir(sdir, true, true);
      assert.strictEqual(res.passed, true);
      assert.strictEqual(res.status, "PASSED");
      assert.strictEqual(res.type, "micro");
      assert.strictEqual(res.errors.length, 0);
      assert.strictEqual(res.warnings.length, 0);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("scaffolds and validates a standard enterprise skill", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "skill-standard-"));
    try {
      const sdir = scaffoldSkill(tmpDir, "full-audit", false);
      assert.ok(fs.existsSync(path.join(sdir, "SKILL.md")));
      assert.ok(fs.existsSync(path.join(sdir, "VERSION")));
      assert.ok(fs.existsSync(path.join(sdir, "CHANGELOG.md")));
      assert.ok(fs.existsSync(path.join(sdir, "scripts", "validate_full_audit.ts")));
      assert.ok(fs.existsSync(path.join(sdir, "references", "full-audit_guide.md")));
      assert.ok(fs.existsSync(path.join(sdir, "assets", "manifest.json")));
      assert.ok(fs.existsSync(path.join(sdir, "evals", "eval_cases.json")));

      const res = validateSkillDir(sdir, true, false);
      assert.strictEqual(res.passed, true);
      assert.strictEqual(res.status, "PASSED");
      assert.strictEqual(res.type, "standard");
      assert.strictEqual(res.errors.length, 0);
      assert.strictEqual(res.warnings.length, 0);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("fails when target is not a directory or does not exist", () => {
    const res = validateSkillDir("/non/existent/path/for/sure");
    assert.strictEqual(res.passed, false);
    assert.strictEqual(res.status, "FAILED");
    assert.ok(res.errors[0].includes("is not a directory"));
  });

  it("detects missing SKILL.md", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "skill-missing-"));
    try {
      const res = validateSkillDir(tmpDir);
      assert.strictEqual(res.passed, false);
      assert.ok(res.errors.includes("Missing SKILL.md root instruction file"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("detects frontmatter errors in SKILL.md", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "skill-fm-"));
    try {
      // 1. Missing opening '---'
      fs.writeFileSync(path.join(tmpDir, "SKILL.md"), "name: test\n---\n# Title\n", "utf-8");
      let res = validateSkillDir(tmpDir);
      assert.ok(res.errors.includes("SKILL.md missing standard YAML frontmatter opening '---'"));

      // 2. Unclosed frontmatter
      fs.writeFileSync(path.join(tmpDir, "SKILL.md"), "---\nname: test\ndescription: desc\n# Title\n", "utf-8");
      res = validateSkillDir(tmpDir);
      assert.ok(res.errors.includes("SKILL.md YAML frontmatter is unclosed"));

      // 3. Missing name and description
      fs.writeFileSync(path.join(tmpDir, "SKILL.md"), "---\nversion: 1.0.0\n---\n# Title\n", "utf-8");
      res = validateSkillDir(tmpDir);
      assert.ok(res.errors.includes("SKILL.md frontmatter missing 'name'"));
      assert.ok(res.errors.includes("SKILL.md frontmatter missing 'description'"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("detects missing constraints and turn contract warnings", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "skill-warn-"));
    try {
      fs.writeFileSync(
        path.join(tmpDir, "SKILL.md"),
        "---\nname: test\ndescription: test desc\ntype: micro\n---\n# Title\n",
        "utf-8"
      );
      const res = validateSkillDir(tmpDir);
      assert.ok(res.warnings.includes("SKILL.md does not define explicit <hard_constraints>"));
      assert.ok(res.warnings.includes("SKILL.md does not define an explicit <turn_contract>"));
      assert.strictEqual(res.passed, true); // In non-strict mode, warnings still pass

      const strictRes = validateSkillDir(tmpDir, true);
      assert.strictEqual(strictRes.passed, false);
      assert.strictEqual(strictRes.status, "FAILED");
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("checks VERSION, scripts/, and references/ in standard skills", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "skill-std-checks-"));
    try {
      // Standard skill without VERSION, scripts, references
      fs.writeFileSync(
        path.join(tmpDir, "SKILL.md"),
        "---\nname: std-skill\ndescription: standard skill\n---\n<hard_constraints></hard_constraints>\n<turn_contract></turn_contract>\n",
        "utf-8"
      );
      let res = validateSkillDir(tmpDir);
      assert.ok(res.warnings.includes("Skill lacks a VERSION file"));
      assert.ok(res.warnings.includes("Skill lacks deterministic helper scripts in scripts/"));
      assert.ok(res.warnings.includes("Skill lacks reference markdown guides in references/"));

      // Invalid SemVer in VERSION
      fs.writeFileSync(path.join(tmpDir, "VERSION"), "v1.0-beta\n", "utf-8");
      res = validateSkillDir(tmpDir);
      assert.ok(res.warnings.some((w) => w.includes("does not conform to SemVer (X.Y.Z)")));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it("runs CLI with --init, --strict, and --json", () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "skill-cli-"));
    try {
      // Init micro skill via CLI
      const initOut = execFileSync(process.execPath, [
        SCRIPT_PATH,
        "--init",
        "cli-created",
        "--micro",
        tmpDir,
      ], { encoding: "utf-8" });
      assert.ok(initOut.includes("Initialized micro skill"));

      const targetPath = path.join(tmpDir, "cli-created");
      assert.ok(fs.existsSync(path.join(targetPath, "SKILL.md")));

      // Validate with --json
      const jsonOut = execFileSync(process.execPath, [
        SCRIPT_PATH,
        targetPath,
        "--micro",
        "--strict",
        "--json",
      ], { encoding: "utf-8" });
      const parsed = JSON.parse(jsonOut);
      assert.strictEqual(parsed.passed, true);
      assert.strictEqual(parsed.status, "PASSED");
      assert.strictEqual(parsed.skill, "cli-created");
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
