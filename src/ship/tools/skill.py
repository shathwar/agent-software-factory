#!/usr/bin/env python3
"""validate_skill.py – Deterministic validator and scaffolder for skill factory artifacts.

Validates that a skill directory satisfies the native Claude Skills specification:
  - Micro Skill: Self-contained SKILL.md with frontmatter, hard constraints, and turn contract.
  - Standard Skill: SKILL.md + scripts/ + references/ + assets/ + evals/ + VERSION file.

Zero external dependencies (Python 3.10+ standard library).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Sequence


MICRO_SKILL_TEMPLATE = """---
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
"""

FULL_SKILL_TEMPLATE = """---
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

Execute workflow according to specifications in `references/`.
"""


def scaffold_skill(target_dir: Path, name: str, micro: bool = True) -> Path:
    """Scaffold a new skill directory (Micro or Full package)."""
    sdir = target_dir / name
    sdir.mkdir(parents=True, exist_ok=True)
    title = " ".join(word.capitalize() for word in name.replace("-", " ").replace("_", " ").split())

    if micro:
        (sdir / "SKILL.md").write_text(MICRO_SKILL_TEMPLATE.format(name=name, title=title), encoding="utf-8")
    else:
        (sdir / "SKILL.md").write_text(FULL_SKILL_TEMPLATE.format(name=name, title=title), encoding="utf-8")
        (sdir / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (sdir / "CHANGELOG.md").write_text(
            f"# Changelog\n\n## [1.0.0] - Initial release\n- Initial release of `{name}`.\n",
            encoding="utf-8",
        )
        scripts_dir = sdir / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        py_name = name.replace("-", "_")
        (scripts_dir / f"validate_{py_name}.py").write_text(
            f"#!/usr/bin/env python3\n\"\"\"Validator for {name}.\"\"\"\nimport sys\n\ndef main():\n    print('Validation passed.')\n    return 0\n\nif __name__ == '__main__':\n    sys.exit(main())\n",
            encoding="utf-8",
        )
        refs_dir = sdir / "references"
        refs_dir.mkdir(exist_ok=True)
        (refs_dir / f"{name}_guide.md").write_text(
            f"# {title} Reference Guide\n\nDetailed operational instructions.\n",
            encoding="utf-8",
        )
        assets_dir = sdir / "assets"
        assets_dir.mkdir(exist_ok=True)
        (assets_dir / "manifest.json").write_text(
            json.dumps({"name": name, "version": "1.0.0"}, indent=2) + "\n",
            encoding="utf-8",
        )
        evals_dir = sdir / "evals"
        evals_dir.mkdir(exist_ok=True)
        (evals_dir / "eval_cases.json").write_text(
            json.dumps([{"id": "eval_1", "prompt": f"Test {name}", "expected": "success"}], indent=2) + "\n",
            encoding="utf-8",
        )

    return sdir


def validate_skill_dir(skill_dir: Path, strict: bool = False, micro: bool = False) -> Dict[str, Any]:
    """Validate a skill directory against specification (Micro or Standard)."""
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
    is_micro_skill = micro
    version_str = "unknown"

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
                if re.search(r"type:\s*micro\b", fm):
                    is_micro_skill = True
                v_match = re.search(r"version:\s*([0-9\.]+)", fm)
                if v_match:
                    version_str = v_match.group(1)

        if "<hard_constraints>" not in content:
            warnings.append("SKILL.md does not define explicit <hard_constraints>")
        if "<turn_contract>" not in content:
            warnings.append("SKILL.md does not define an explicit <turn_contract>")

    # 2. Check VERSION
    version_file = sdir / "VERSION"
    if not version_file.exists():
        if not is_micro_skill:
            warnings.append("Skill lacks a VERSION file")
    else:
        version_str = version_file.read_text(encoding="utf-8").strip()
        if not re.match(r"^\d+\.\d+\.\d+$", version_str):
            warnings.append(f"VERSION '{version_str}' does not conform to SemVer (X.Y.Z)")

    # 3. Check scripts/ (Exempt for micro skills)
    scripts_dir = sdir / "scripts"
    if not scripts_dir.is_dir() or not any(scripts_dir.glob("*.py")):
        if not is_micro_skill:
            warnings.append("Skill lacks deterministic helper scripts in scripts/")

    # 4. Check references/ (Exempt for micro skills)
    refs_dir = sdir / "references"
    if not refs_dir.is_dir() or not any(refs_dir.glob("*.md")):
        if not is_micro_skill:
            warnings.append("Skill lacks reference markdown guides in references/")

    passed = len(errors) == 0
    if strict and warnings:
        passed = False

    return {
        "skill": sdir.name,
        "type": "micro" if is_micro_skill else "standard",
        "version": version_str,
        "path": str(sdir),
        "passed": passed,
        "status": "PASSED" if passed else "FAILED",
        "errors": errors,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or scaffold skill directory structure.")
    parser.add_argument("path", nargs="?", default=".", help="Path to skill directory")
    parser.add_argument("--strict", action="store_true", help="Fail if warnings are present")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON")
    parser.add_argument("--micro", action="store_true", help="Validate as or scaffold a self-contained Micro Skill (single SKILL.md)")
    parser.add_argument("--init", type=str, default=None, metavar="NAME", help="Scaffold a new skill directory with the given name")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.init:
        target = Path(args.path) if args.path != "." else Path.cwd()
        created = scaffold_skill(target, args.init, micro=args.micro)
        print(f"✅ Initialized {'micro' if args.micro else 'standard'} skill at: {created}")
        return 0

    result = validate_skill_dir(Path(args.path), strict=args.strict, micro=args.micro)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        icon = "✅" if result["passed"] else "❌"
        print(f"{icon} Skill '{result['skill']}' ({result.get('type', 'standard')}) validation: {result['status']}")
        for e in result["errors"]:
            print(f"  • Error: {e}")
        for w in result["warnings"]:
            print(f"  • Warning: {w}")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
