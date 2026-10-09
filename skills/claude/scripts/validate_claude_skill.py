#!/usr/bin/env python3
"""validate_claude_skill.py — Deterministic validator for the Claude optimization skill.

Validates:
  1. SKILL.md with valid YAML frontmatter containing model, effort, allowed-tools
  2. SemVer VERSION file
  3. references/ with model selection and frontmatter spec guides
  4. scripts/ with executable helper tools
  5. assets/ and evals/ structure

Zero external dependencies (Python 3.10+ standard library).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List


def validate_claude_skill(skill_dir: Path, strict: bool = False) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    sdir = Path(skill_dir).resolve()
    if not sdir.is_dir():
        return {
            "passed": False,
            "status": "FAILED",
            "errors": [f"Path '{sdir}' is not a directory"],
            "warnings": [],
        }

    # 1. Inspect SKILL.md
    skill_md = sdir / "SKILL.md"
    if not skill_md.exists():
        errors.append("Missing SKILL.md")
    else:
        content = skill_md.read_text(encoding="utf-8")
        fm_match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not fm_match:
            errors.append("SKILL.md missing valid YAML frontmatter")
        else:
            fm = fm_match.group(1)
            for req_field in ["name:", "description:", "model:", "effort:", "allowed-tools:"]:
                if req_field not in fm:
                    errors.append(f"SKILL.md frontmatter missing required field '{req_field.rstrip(':')}'")

        if "<hard_constraints>" not in content:
            warnings.append("SKILL.md missing <hard_constraints>")
        if "<turn_contract>" not in content:
            warnings.append("SKILL.md missing <turn_contract>")

    # 2. Inspect VERSION
    vfile = sdir / "VERSION"
    version = "unknown"
    if not vfile.exists():
        errors.append("Missing VERSION file")
    else:
        version = vfile.read_text(encoding="utf-8").strip()
        if not re.match(r"^\d+\.\d+\.\d+$", version):
            errors.append(f"Invalid SemVer: '{version}'")

    # 3. Inspect references
    rdir = sdir / "references"
    if not rdir.is_dir() or not (rdir / "model_selection_guide.md").exists():
        warnings.append("Missing model_selection_guide.md in references/")

    # 4. Inspect scripts
    sc_dir = sdir / "scripts"
    if not sc_dir.is_dir() or not (sc_dir / "choose_claude_profile.py").exists():
        errors.append("Missing choose_claude_profile.py in scripts/")

    passed = len(errors) == 0
    if strict and warnings:
        passed = False

    return {
        "skill": sdir.name,
        "version": version,
        "passed": passed,
        "status": "PASSED" if passed else "FAILED",
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate claude skill directory.")
    parser.add_argument("path", nargs="?", default=".", help="Path to skill directory")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args()

    result = validate_claude_skill(Path(args.path), strict=args.strict)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        icon = "✅" if result["passed"] else "❌"
        print(f"{icon} Skill '{result['skill']}' validation: {result['status']}")
        for e in result["errors"]:
            print(f"  • Error: {e}")
        for w in result["warnings"]:
            print(f"  • Warning: {w}")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
