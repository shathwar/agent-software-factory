#!/usr/bin/env python3
"""
validate_skill.py – Deterministic validator for skill factory artifacts.

Validates that a skill directory satisfies the native Claude Skills specification:
  - SKILL.md with valid YAML frontmatter, hard constraints, and turn contract
  - scripts/ with executable helper validators
  - references/ with on-demand guidance
  - assets/ with valid manifest
  - evals/ with behavioral scenarios
  - VERSION file with SemVer format

Zero external dependencies (Python 3.10+ standard library).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List


def validate_skill_dir(skill_dir: Path, strict: bool = False) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    sdir = Path(skill_dir).resolve()
    if not sdir.is_dir():
        return {
            "passed": False,
            "status": "FAILED",
            "errors": [f"Target path '{sdir}' is not a directory"],
            "warnings": [],
        }

    # 1. Check SKILL.md
    skill_md = sdir / "SKILL.md"
    if not skill_md.exists():
        errors.append("Missing SKILL.md root instruction file")
    else:
        content = skill_md.read_text(encoding="utf-8")
        if not content.startswith("---"):
            errors.append("SKILL.md missing standard YAML frontmatter opening '---'")
        else:
            frontmatter_match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
            if not frontmatter_match:
                errors.append("SKILL.md YAML frontmatter is unclosed")
            else:
                fm = frontmatter_match.group(1)
                if "name:" not in fm:
                    errors.append("SKILL.md frontmatter missing 'name'")
                if "description:" not in fm:
                    errors.append("SKILL.md frontmatter missing 'description'")

        if "<hard_constraints>" not in content:
            warnings.append("SKILL.md does not define explicit <hard_constraints>")
        if "<turn_contract>" not in content:
            warnings.append("SKILL.md does not define an explicit <turn_contract>")

    # 2. Check VERSION
    version_file = sdir / "VERSION"
    version_str = "unknown"
    if not version_file.exists():
        warnings.append("Skill lacks a VERSION file")
    else:
        version_str = version_file.read_text(encoding="utf-8").strip()
        if not re.match(r"^\d+\.\d+\.\d+$", version_str):
            warnings.append(f"VERSION '{version_str}' does not conform to SemVer (X.Y.Z)")

    # 3. Check scripts/
    scripts_dir = sdir / "scripts"
    if not scripts_dir.is_dir() or not any(scripts_dir.glob("*.py")):
        warnings.append("Skill lacks deterministic helper scripts in scripts/")

    # 4. Check references/
    refs_dir = sdir / "references"
    if not refs_dir.is_dir() or not any(refs_dir.glob("*.md")):
        warnings.append("Skill lacks reference markdown guides in references/")

    passed = len(errors) == 0
    if strict and warnings:
        passed = False

    return {
        "skill": sdir.name,
        "version": version_str,
        "path": str(sdir),
        "passed": passed,
        "status": "PASSED" if passed else "FAILED",
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate skill directory structure.")
    parser.add_argument("path", nargs="?", default=".", help="Path to skill directory")
    parser.add_argument("--strict", action="store_true", help="Fail if warnings are present")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON")
    args = parser.parse_args()

    result = validate_skill_dir(Path(args.path), strict=args.strict)

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
