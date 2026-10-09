#!/usr/bin/env node
/**
 * validate_skill.ts – Deterministic validator and scaffolder for skill factory artifacts.
 *
 * Validates that a skill directory satisfies the native Claude Skills specification:
 *   - Micro Skill: Self-contained SKILL.md with frontmatter, hard constraints, and turn contract.
 *   - Standard Skill: SKILL.md + scripts/ + references/ + assets/ + evals/ + VERSION file.
 *
 * Zero external dependencies (Node.js 22+ / 25+ standard library).
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

export const MICRO_SKILL_TEMPLATE = `---
name: {name}
description: Concise, actionable description of what this skill does and trigger phrases.
type: micro
version: 1.0.0
---

# {title}

**Role**: Expert systems specialist.

<hard_constraints>
- Execution Rule 1: Non-negotiable constraint.
- Execution Rule 2: Surgical, minimal operations.
</hard_constraints>

<turn_contract>
Verify before ending the turn:
✓ 1. Task executed and confirmed.
✓ 2. Zero errors or regressions.
</turn_contract>

## Workflow

1. Step 1: Inspect input and context.
2. Step 2: Execute command or transform data.
3. Step 3: Verify output.
`;

export const FULL_SKILL_TEMPLATE = `---
name: {name}
description: Concise, actionable description of what this skill does and trigger phrases.
version: 1.0.0
---

# {title}

**Role**: Principal Systems Specialist.

<hard_constraints>
- Rule 1: Production-grade quality.
- Rule 2: Deterministic verification.
</hard_constraints>

<turn_contract>
Verify before ending the turn:
✓ 1. Specification aligned.
✓ 2. Tests and validations green.
</turn_contract>

## 1. Protocol

Execute workflow according to specifications in \`references/\`.
`;

export interface SkillValidationResult {
  skill: string;
  type: "micro" | "standard";
  version: string;
  path: string;
  passed: boolean;
  status: "PASSED" | "FAILED";
  errors: string[];
  warnings: string[];
}

export function scaffoldSkill(targetDir: string, name: string, micro: boolean = true): string {
  const sdir = path.resolve(targetDir, name);
  fs.mkdirSync(sdir, { recursive: true });
  const title = name.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  const template = micro ? MICRO_SKILL_TEMPLATE : FULL_SKILL_TEMPLATE;
  fs.writeFileSync(
    path.join(sdir, "SKILL.md"),
    template.replace(/\{name\}/g, name).replace(/\{title\}/g, title),
    "utf-8"
  );

  if (!micro) {
    fs.writeFileSync(path.join(sdir, "VERSION"), "1.0.0\n", "utf-8");
    fs.writeFileSync(
      path.join(sdir, "CHANGELOG.md"),
      `# Changelog\n\n## [1.0.0] - Initial release\n- Initial release of \`${name}\`.\n`,
      "utf-8"
    );

    const makeDir = (sub: string) => {
      const p = path.join(sdir, sub);
      fs.mkdirSync(p, { recursive: true });
      return p;
    };

    const scriptName = name.replace(/-/g, "_");
    fs.writeFileSync(
      path.join(makeDir("scripts"), `validate_${scriptName}.ts`),
      `#!/usr/bin/env node\n/**\n * Validator for ${name}.\n */\nimport process from "node:process";\n\nexport function main(): number {\n  console.log("Validation passed.");\n  return 0;\n}\n\nif (process.argv[1] && import.meta.filename && process.argv[1] === import.meta.filename) {\n  process.exit(main());\n}\n`,
      "utf-8"
    );
    fs.writeFileSync(
      path.join(makeDir("references"), `${name}_guide.md`),
      `# ${title} Reference Guide\n\nDetailed operational instructions.\n`,
      "utf-8"
    );
    fs.writeFileSync(
      path.join(makeDir("assets"), "manifest.json"),
      JSON.stringify({ name, version: "1.0.0" }, null, 2) + "\n",
      "utf-8"
    );
    fs.writeFileSync(
      path.join(makeDir("evals"), "eval_cases.json"),
      JSON.stringify([{ id: "eval_1", prompt: `Test ${name}`, expected: "success" }], null, 2) + "\n",
      "utf-8"
    );
  }

  return sdir;
}

export const scaffold_skill = scaffoldSkill;

export function validateSkillDir(
  skillDir: string,
  strict: boolean = false,
  micro: boolean = false
): SkillValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const sdir = path.resolve(skillDir);

  if (!fs.existsSync(sdir) || !fs.statSync(sdir).isDirectory()) {
    return {
      skill: path.basename(sdir),
      type: micro ? "micro" : "standard",
      version: "unknown",
      path: sdir,
      passed: false,
      status: "FAILED",
      errors: [`Target path '${sdir}' is not a directory`],
      warnings: [],
    };
  }

  const skillMd = path.join(sdir, "SKILL.md");
  let isMicroSkill = micro;
  let versionStr = "unknown";

  if (!fs.existsSync(skillMd)) {
    errors.push("Missing SKILL.md root instruction file");
  } else {
    const content = fs.readFileSync(skillMd, "utf-8");
    if (!content.startsWith("---")) {
      errors.push("SKILL.md missing standard YAML frontmatter opening '---'");
    } else {
      const match = content.match(/^---\n([\s\S]*?)\n---/);
      if (!match) {
        errors.push("SKILL.md YAML frontmatter is unclosed");
      } else {
        const fm = match[1];
        if (!fm.includes("name:")) errors.push("SKILL.md frontmatter missing 'name'");
        if (!fm.includes("description:")) errors.push("SKILL.md frontmatter missing 'description'");
        if (/type:\s*micro\b/.test(fm)) isMicroSkill = true;
        const vMatch = fm.match(/version:\s*([0-9\.]+)/);
        if (vMatch) versionStr = vMatch[1];
      }
    }

    if (!content.includes("<hard_constraints>")) warnings.push("SKILL.md does not define explicit <hard_constraints>");
    if (!content.includes("<turn_contract>")) warnings.push("SKILL.md does not define an explicit <turn_contract>");
  }

  const versionFile = path.join(sdir, "VERSION");
  if (!fs.existsSync(versionFile)) {
    if (!isMicroSkill) warnings.push("Skill lacks a VERSION file");
  } else {
    versionStr = fs.readFileSync(versionFile, "utf-8").trim();
    if (!/^\d+\.\d+\.\d+$/.test(versionStr)) {
      warnings.push(`VERSION '${versionStr}' does not conform to SemVer (X.Y.Z)`);
    }
  }

  const checkDirHas = (dir: string, filter: (f: string) => boolean, warnMsg: string) => {
    const full = path.join(sdir, dir);
    const has = fs.existsSync(full) && fs.statSync(full).isDirectory() && fs.readdirSync(full).some(filter);
    if (!has && !isMicroSkill) warnings.push(warnMsg);
  };

  checkDirHas("scripts", (f) => /\.(ts|py|sh|js)$/.test(f), "Skill lacks deterministic helper scripts in scripts/");
  checkDirHas("references", (f) => f.endsWith(".md"), "Skill lacks reference markdown guides in references/");

  const passed = errors.length === 0 && (!strict || warnings.length === 0);

  return {
    skill: path.basename(sdir),
    type: isMicroSkill ? "micro" : "standard",
    version: versionStr,
    path: sdir,
    passed,
    status: passed ? "PASSED" : "FAILED",
    errors,
    warnings,
  };
}

export const validate_skill_dir = validateSkillDir;

export function main(argv: string[] = process.argv.slice(2)): number {
  let targetPath = ".";
  let strict = false;
  let jsonOutput = false;
  let micro = false;
  let initName: string | null = null;

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--strict") strict = true;
    else if (arg === "--json") jsonOutput = true;
    else if (arg === "--micro") micro = true;
    else if (arg === "--init") initName = argv[++i] ?? null;
    else if (!arg.startsWith("-")) targetPath = arg;
  }

  if (initName) {
    const targetDir = targetPath !== "." ? path.resolve(targetPath) : process.cwd();
    const created = scaffoldSkill(targetDir, initName, micro);
    console.log(`✅ Initialized ${micro ? "micro" : "standard"} skill at: ${created}`);
    return 0;
  }

  const result = validateSkillDir(targetPath, strict, micro);

  if (jsonOutput) {
    console.log(JSON.stringify(result, null, 2));
  } else {
    console.log(`${result.passed ? "✅" : "❌"} Skill '${result.skill}' (${result.type}) validation: ${result.status}`);
    result.errors.forEach((e) => console.log(`  • Error: ${e}`));
    result.warnings.forEach((w) => console.log(`  • Warning: ${w}`));
  }

  return result.passed ? 0 : 1;
}

if (process.argv[1] && import.meta.filename && process.argv[1] === import.meta.filename) {
  process.exit(main());
}
