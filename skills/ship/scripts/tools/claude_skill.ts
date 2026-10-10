import fs from "node:fs";
import path from "node:path";

export function validateClaudeSkill(skillDir: string, strict = false): any {
  const errors: string[] = [], warnings: string[] = [], dir = path.resolve(skillDir);
  if (!fs.statSync(dir, {throwIfNoEntry: false})?.isDirectory()) return {passed: false, status: "FAILED", errors: [`Path '${dir}' is not a directory`], warnings: []};
  const skillPath = path.join(dir, "SKILL.md");
  if (!fs.existsSync(skillPath)) errors.push("Missing SKILL.md");
  else { const content = fs.readFileSync(skillPath, "utf8"); const fm = /^---\n([\s\S]*?)\n---/.exec(content)?.[1]; if (!fm) errors.push("SKILL.md missing valid YAML frontmatter"); else for (const field of ["name:", "description:", "model:", "effort:", "allowed-tools:"]) if (!fm.includes(field)) errors.push(`SKILL.md frontmatter missing required field '${field.slice(0, -1)}'`); if (!content.includes("<hard_constraints>")) warnings.push("SKILL.md missing <hard_constraints>"); if (!content.includes("<turn_contract>")) warnings.push("SKILL.md missing <turn_contract>"); }
  const versionPath = path.join(dir, "VERSION"); let version = "unknown";
  if (!fs.existsSync(versionPath)) errors.push("Missing VERSION file"); else { version = fs.readFileSync(versionPath, "utf8").trim(); if (!/^\d+\.\d+\.\d+$/.test(version)) errors.push(`Invalid SemVer: '${version}'`); }
  if (!fs.existsSync(path.join(dir, "scripts", "choose_claude_profile.ts"))) errors.push("Missing choose_claude_profile.ts in scripts/");
  const passed = errors.length === 0 && (!strict || warnings.length === 0);
  return {skill: path.basename(dir), version, passed, status: passed ? "PASSED" : "FAILED", errors, warnings};
}
export function main(argv = process.argv.slice(2)): number { const dir = argv.find(a => !a.startsWith("-")) ?? "."; const result = validateClaudeSkill(dir, argv.includes("--strict")); console.log(argv.includes("--json") ? JSON.stringify(result, null, 2) : `${result.passed ? "✅" : "❌"} Skill '${result.skill}' validation: ${result.status}`); return result.passed ? 0 : 1; }
if (import.meta.url === `file://${process.argv[1]}`) process.exit(main());
