import fs from "node:fs";
import path from "node:path";

export interface TaskProfile { task: string; model: string; model_rationale: string; effort: string; effort_rationale: string; allowed_tools: string[]; frontmatter_yaml: string }

export function evaluateTaskProfile(task: string, filesCount = 1, risk = "medium", ambiguity = "medium", allowBash = true, allowWrite = true): TaskProfile {
  const lower = task.toLowerCase();
  const mechanical = /\b(format|lint|rename|sort|grep|search|find|clean\s*up|typo|comment)\b/.test(lower);
  const frontier = /\b(proof|cryptograph|formal\s*verif|distributed\s*consensus|paxos|raft)\b/.test(lower);
  let model: string, model_rationale: string;
  if (mechanical && filesCount <= 2 && risk === "low" && ambiguity === "low") { model = "claude-3-5-haiku"; model_rationale = "Mechanical task with low risk and clear requirements; optimal cost and latency."; }
  else if (frontier || (ambiguity === "high" && risk === "high" && filesCount > 10)) { model = "claude-3-opus"; model_rationale = "High-frontier problem or extreme conceptual ambiguity requiring deep reasoning."; }
  else { model = "claude-3-7-sonnet"; model_rationale = "Balanced frontier engineering workhorse for implementation, TDD, and code review."; }
  let effort: string, effort_rationale: string;
  if (mechanical || (risk === "low" && ambiguity === "low")) { effort = "low"; effort_rationale = "Deterministic execution path with minimal branching."; }
  else if (frontier || risk === "high" || /\b(race\s*condition|deadlock|concurrency|invariant)\b/.test(lower)) { effort = risk === "critical" ? "max" : "high"; effort_rationale = "Multi-system invariants, potential race conditions, or high failure impact."; }
  else if (ambiguity === "high" || filesCount >= 5) { effort = "high"; effort_rationale = "Multiple files and cross-cutting design choices."; }
  else { effort = "medium"; effort_rationale = "Standard software development task with moderate branching."; }
  let tools = ["Read", "Glob", "Grep"];
  if (allowWrite) tools.push("Edit", "Write");
  if (allowBash) tools.push("Bash");
  const readOnly = /\b(review|audit|inspect|check|explore|search|find)\b/.test(lower) && !/\b(fix|repair|implement|write|create|update|modify|refactor)\b/.test(lower);
  if (readOnly && !allowBash) tools = ["Read", "Glob", "Grep"];
  const name = task.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 30).replace(/^-+|-+$/g, "") || "claude-task";
  const frontmatter_yaml = ["---", `name: ${name}`, `description: Task profile for ${task.trim()}`, `model: ${model}`, `effort: ${effort}`, "allowed-tools:", ...tools.map(t => `  - ${t}`), "---"].join("\n");
  return {task, model, model_rationale, effort, effort_rationale, allowed_tools: tools, frontmatter_yaml};
}

export function main(argv = process.argv.slice(2)): number {
  const value = (key: string, fallback?: string) => { const i = argv.findIndex(a => a === key || a.startsWith(`${key}=`)); return i < 0 ? fallback : argv[i].includes("=") ? argv[i].split("=").slice(1).join("=") : argv[i + 1]; };
  const task = value("--task"); if (!task) { console.error("--task is required"); return 1; }
  const result = evaluateTaskProfile(task, Number(value("--files", "1")), value("--risk", "medium"), value("--ambiguity", "medium"), !argv.includes("--no-bash"), !argv.includes("--no-write"));
  if (argv.includes("--json")) console.log(JSON.stringify(result, null, 2)); else console.log(`🎯 Task: ${result.task}\n🤖 Recommended Model:  ${result.model} (${result.model_rationale})\n⚡ Reasoning Effort:   ${result.effort} (${result.effort_rationale})\n🛠️  Allowed Tools:      ${result.allowed_tools.join(", ")}\n\n📋 Recommended SKILL.md Frontmatter:\n${result.frontmatter_yaml}`);
  return 0;
}
if (import.meta.url === `file://${process.argv[1]}`) process.exit(main());
