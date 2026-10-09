import { describe, expect, it } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { evaluateTaskProfile } from "../src/ship/tools/claude_profile.ts";
import { validateClaudeSkill } from "../src/ship/tools/claude_skill.ts";

describe("Claude tool migrations", () => {
  it("selects the low-cost profile for clear mechanical work", () => {
    const result = evaluateTaskProfile("format two files", 2, "low", "low", false, false);
    expect(result.model).toBe("claude-3-5-haiku"); expect(result.effort).toBe("low"); expect(result.allowed_tools).toEqual(["Read", "Glob", "Grep"]);
    expect(result.frontmatter_yaml).toContain("name: format-two-files");
  });
  it("selects high effort for frontier and concurrency work", () => {
    expect(evaluateTaskProfile("prove distributed consensus", 1, "medium", "medium").model).toBe("claude-3-opus");
    expect(evaluateTaskProfile("fix a deadlock", 3, "high", "medium").effort).toBe("high");
    expect(evaluateTaskProfile("fix a critical race condition", 3, "critical", "medium").effort).toBe("max");
  });
  it("validates Claude skill structure and strict warnings", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "claude-skill-"));
    try {
      fs.writeFileSync(path.join(root, "SKILL.md"), "---\nname: x\ndescription: x\nmodel: x\neffort: low\nallowed-tools: []\n---\n<hard_constraints>\n<turn_contract>");
      fs.writeFileSync(path.join(root, "VERSION"), "1.2.3\n"); fs.mkdirSync(path.join(root, "references")); fs.mkdirSync(path.join(root, "scripts")); fs.writeFileSync(path.join(root, "references", "model_selection_guide.md"), "guide"); fs.writeFileSync(path.join(root, "scripts", "choose_claude_profile.ts"), "");
      expect(validateClaudeSkill(root, true).passed).toBe(true);
      fs.rmSync(path.join(root, "SKILL.md")); expect(validateClaudeSkill(root).errors).toContain("Missing SKILL.md");
    } finally { fs.rmSync(root, {recursive: true, force: true}); }
  });
});
