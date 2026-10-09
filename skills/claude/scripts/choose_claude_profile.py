#!/usr/bin/env python3
"""choose_claude_profile.py — Deterministic selector for Claude model, effort, and tools.

Evaluates task complexity, file scope, risk, and ambiguity to recommend:
  1. Claude model tier (haiku, sonnet, opus)
  2. Reasoning effort level (low, medium, high, max)
  3. Tool permissions allowlist (allowed-tools)
  4. Complete YAML frontmatter for Claude Code / SKILL.md

Zero external dependencies (Python 3.10+ standard library).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, List


def evaluate_task_profile(
    task: str,
    files_count: int = 1,
    risk: str = "medium",
    ambiguity: str = "medium",
    allow_bash: bool = True,
    allow_write: bool = True,
) -> Dict[str, Any]:
    """Evaluate task attributes and recommend model, effort, and tools."""
    t_lower = task.lower()

    # 1. Model Selection
    is_mechanical = bool(
        re.search(r"\b(format|lint|rename|sort|grep|search|find|clean\s*up|typo|comment)\b", t_lower)
    )
    is_frontier = bool(
        re.search(r"\b(proof|cryptograph|formal\s*verif|distributed\s*consensus|paxos|raft)\b", t_lower)
    )

    if is_mechanical and files_count <= 2 and risk == "low" and ambiguity == "low":
        model = "claude-3-5-haiku"
        model_rationale = "Mechanical task with low risk and clear requirements; optimal cost and latency."
    elif is_frontier or (ambiguity == "high" and risk == "high" and files_count > 10):
        model = "claude-3-opus"
        model_rationale = "High-frontier problem or extreme conceptual ambiguity requiring deep reasoning."
    else:
        model = "claude-3-7-sonnet"
        model_rationale = "Balanced frontier engineering workhorse for implementation, TDD, and code review."

    # 2. Reasoning Effort
    if is_mechanical or (risk == "low" and ambiguity == "low"):
        effort = "low"
        effort_rationale = "Deterministic execution path with minimal branching."
    elif is_frontier or risk == "high" or re.search(r"\b(race\s*condition|deadlock|concurrency|invariant)\b", t_lower):
        effort = "high" if risk != "critical" else "max"
        effort_rationale = "Multi-system invariants, potential race conditions, or high failure impact."
    elif ambiguity == "high" or files_count >= 5:
        effort = "high"
        effort_rationale = "Multiple files and cross-cutting design choices."
    else:
        effort = "medium"
        effort_rationale = "Standard software development task with moderate branching."

    # 3. Tool Sandboxing
    tools: List[str] = ["Read", "Glob", "Grep"]
    if allow_write:
        tools.extend(["Edit", "Write"])
    if allow_bash:
        tools.append("Bash")

    # If pure inspection or review task
    is_read_only = bool(re.search(r"\b(review|audit|inspect|check|explore|search|find)\b", t_lower)) and not bool(
        re.search(r"\b(fix|repair|implement|write|create|update|modify|refactor)\b", t_lower)
    )
    if is_read_only and not allow_bash:
        tools = ["Read", "Glob", "Grep"]

    # 4. Generate Frontmatter
    safe_name = re.sub(r"[^a-z0-9]+", "-", task.lower().strip())[:30].strip("-") or "claude-task"
    frontmatter_lines = [
        "---",
        f"name: {safe_name}",
        f"description: Task profile for {task.strip()}",
        f"model: {model}",
        f"effort: {effort}",
        "allowed-tools:",
    ]
    for tool in tools:
        frontmatter_lines.append(f"  - {tool}")
    frontmatter_lines.append("---")
    frontmatter_yaml = "\n".join(frontmatter_lines)

    return {
        "task": task,
        "model": model,
        "model_rationale": model_rationale,
        "effort": effort,
        "effort_rationale": effort_rationale,
        "allowed_tools": tools,
        "frontmatter_yaml": frontmatter_yaml,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Choose optimal Claude model, effort, and tools for a task.")
    parser.add_argument("--task", required=True, help="Task description or title")
    parser.add_argument("--files", type=int, default=1, help="Estimated number of files touched")
    parser.add_argument("--risk", choices=["low", "medium", "high", "critical"], default="medium", help="Risk level")
    parser.add_argument("--ambiguity", choices=["low", "medium", "high"], default="medium", help="Requirement ambiguity")
    parser.add_argument("--no-bash", action="store_true", help="Disallow shell/bash execution")
    parser.add_argument("--no-write", action="store_true", help="Disallow file mutations")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()

    result = evaluate_task_profile(
        task=args.task,
        files_count=args.files,
        risk=args.risk,
        ambiguity=args.ambiguity,
        allow_bash=not args.no_bash,
        allow_write=not args.no_write,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"🎯 Task: {result['task']}")
        print(f"🤖 Recommended Model:  {result['model']} ({result['model_rationale']})")
        print(f"⚡ Reasoning Effort:   {result['effort']} ({result['effort_rationale']})")
        print(f"🛠️  Allowed Tools:      {', '.join(result['allowed_tools'])}")
        print("\n📋 Recommended SKILL.md Frontmatter:")
        print(result["frontmatter_yaml"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
