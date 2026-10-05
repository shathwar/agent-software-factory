#!/usr/bin/env python3
"""sync_skills.py — Synchronize and verify parity between src/ship and skills/ distributions.

Zero external dependencies (Python 3.10+ standard library).

Validates and enforces 100% byte-for-byte parity between:
1. src/ship/lifecycle/*.py <-> skills/ship/scripts/lifecycle/*.py
2. src/ship/tools/*.py    <-> skills/*/scripts/*.py
"""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path
import shutil
import sys
from typing import List, Optional, Sequence, Tuple



TOOL_MODULES = {
    "simplify": ("src/ship/tools/simplify.py", "skills/simplify/scripts/scan_debt.py"),
    "tdd": ("src/ship/tools/tdd.py", "skills/tdd/scripts/verify_tdd.py"),
    "review": ("src/ship/tools/review.py", "skills/review/scripts/validate_report.py"),
    "spike": ("src/ship/tools/spike.py", "skills/spike/scripts/run_spike.py"),
    "ux": ("src/ship/tools/ux.py", "skills/ux/scripts/audit_ux.py"),
}


def get_file_mappings(repo_root: Path) -> List[Tuple[Path, Path]]:
    """Return list of (src_path, skills_path) pairs."""
    mappings: List[Tuple[Path, Path]] = []

    # Lifecycle package
    src_lifecycle = repo_root / "src/ship/lifecycle"
    skills_lifecycle = repo_root / "skills/ship/scripts/lifecycle"
    for module in sorted(p.name for p in src_lifecycle.glob("*.py")):
        mappings.append((src_lifecycle / module, skills_lifecycle / module))

    # Specialist tools
    for tool, (src_rel, skills_rel) in TOOL_MODULES.items():
        mappings.append((repo_root / src_rel, repo_root / skills_rel))

    return mappings


def check_parity(repo_root: Path) -> Tuple[bool, List[str]]:
    """Check whether all mapped files are byte-for-byte identical.

    Returns (all_match, list_of_error_messages).
    """
    mappings = get_file_mappings(repo_root)
    divergences: List[str] = []

    for src_file, skills_file in mappings:
        if not src_file.exists():
            divergences.append(f"Missing source file: {src_file.relative_to(repo_root)}")
            continue
        if not skills_file.exists():
            divergences.append(f"Missing skills file: {skills_file.relative_to(repo_root)}")
            continue

        src_bytes = src_file.read_bytes()
        skills_bytes = skills_file.read_bytes()

        if src_bytes != skills_bytes:
            src_rel = src_file.relative_to(repo_root)
            skills_rel = skills_file.relative_to(repo_root)
            src_text = src_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
            skills_text = skills_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
            diff = list(difflib.unified_diff(src_text, skills_text, fromfile=str(src_rel), tofile=str(skills_rel), n=3))
            diff_snippet = "".join(diff[:20])
            divergences.append(
                f"Parity mismatch: {src_rel} != {skills_rel}\n{diff_snippet}"
            )

    return len(divergences) == 0, divergences


def sync_files(repo_root: Path, direction: str = "src-to-skills") -> List[Tuple[Path, Path]]:
    """Synchronize files in the specified direction.

    src-to-skills (default): copies from src/ship/ to skills/*/scripts/
    skills-to-src: copies from skills/*/scripts/ to src/ship/
    """
    mappings = get_file_mappings(repo_root)
    synced: List[Tuple[Path, Path]] = []

    for src_file, skills_file in mappings:
        if direction == "src-to-skills":
            source, destination = src_file, skills_file
        elif direction == "skills-to-src":
            source, destination = skills_file, src_file
        else:
            raise ValueError(f"Unknown direction: {direction}. Must be src-to-skills or skills-to-src.")

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        synced.append((source, destination))

    return synced


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize and verify parity between src/ship/ and skills/ distributions."
    )
    parser.add_argument(
        "--check",
        "--verify",
        action="store_true",
        help="Check parity without making changes. Exits with 0 if identical, 1 if mismatched.",
    )
    parser.add_argument(
        "--direction",
        choices=["src-to-skills", "skills-to-src"],
        default="src-to-skills",
        help="Synchronization direction (default: src-to-skills).",
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Path to repository root (default: current working directory).",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Quiet mode: suppress detailed output.",
    )

    args = parser.parse_args(argv)
    repo_root = Path(args.path).resolve()

    if args.check:
        passed, errors = check_parity(repo_root)
        if passed:
            if not args.quiet:
                print(f"✅ Parity check passed: all {len(get_file_mappings(repo_root))} files are byte-for-byte identical.")
            return 0
        else:
            sys.stderr.write(f"❌ Parity check failed: {len(errors)} divergence(s) detected.\n\n")
            for err in errors:
                sys.stderr.write(err + "\n")
            sys.stderr.write("\nRun python3 scripts/sync_skills.py to synchronize.\n")
            return 1

    # Perform synchronization
    synced = sync_files(repo_root, direction=args.direction)
    if not args.quiet:
        print(f"✅ Synchronized {len(synced)} file(s) ({args.direction}).")
        for src, dest in synced:
            print(f"   • {src.relative_to(repo_root)} -> {dest.relative_to(repo_root)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
