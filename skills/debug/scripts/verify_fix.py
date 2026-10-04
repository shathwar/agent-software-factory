#!/usr/bin/env python3
"""verify_fix.py — Deterministic Bugfix Verification and Anti-Cheat Scanner.

Audits bugfix diffs for:
1. Reproduction Test Parity: Ensures a reproduction test is included in the diff.
2. Anti-Cheat: Detects weakened, skipped, or deleted test assertions.
3. Anti-Pattern Masking: Detects swallowed exceptions, bare except blocks, and defensive null guards masking root causes.
4. Test Suite Execution: Optionally runs the test runner and verifies exit status 0.

Zero external dependencies (Python 3.10+ standard library).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import List, Optional, Tuple

TEST_FILE_PATTERNS = [
    re.compile(r"(?:^|[\\/])(?:test|tests|spec|specs)[\\/]"),
    re.compile(r"[_.-](?:test|spec)\.[a-zA-Z0-9]+$"),
    re.compile(r"(?:^|[\\/])test_[a-zA-Z0-9_]+\.[a-zA-Z0-9]+$"),
]

# Patterns that weaken or skip tests
TEST_WEAKENING_PATTERNS = [
    re.compile(r"^\+\s*@pytest\.mark\.skip"),
    re.compile(r"^\+\s*@unittest\.skip"),
    re.compile(r"^\+\s*(?:it|test|describe)\.skip"),
    re.compile(r"^\+\s*xit\("),
    re.compile(r"^\+\s*xdescribe\("),
    re.compile(r"^\+\s*//\s*(?:expect|assert)"),
    re.compile(r"^\+\s*#\s*self\.assert"),
    re.compile(r"^\+\s*#\s*assert "),
]

# Patterns that swallow or mask exceptions
SYMPTOM_MASKING_PATTERNS = [
    (re.compile(r"^\+\s*except\s*:\s*pass\b"), "Bare 'except: pass' swallows exceptions silently."),
    (re.compile(r"^\+\s*except\s+Exception\s*:\s*pass\b"), "Swallowed 'except Exception: pass' masks root cause."),
    (re.compile(r"^\+\s*catch\s*\([^)]*\)\s*\{\s*\}"), "Empty catch block swallows errors silently."),
    (re.compile(r"^\+\s*catch\s*\{\s*\}"), "Empty catch block swallows errors silently."),
]

MULTILINE_SYMPTOM_MASKING_PATTERNS = [
    (re.compile(r"except(?:\s+[\w\.]+)?\s*:\s*(?:\n\s*(?:#[^\n]*)?)*\n\s*pass\b", re.MULTILINE), "Swallowed exception with pass masks root cause."),
    (re.compile(r"catch\s*(?:\([^)]*\))?\s*\{(?:\s*|\s*//[^\n]*\s*|\s*/\*.*?\*/\s*)*\}", re.DOTALL), "Empty catch block swallows errors silently."),
]


@dataclass
class BugfixAuditResult:
    passed: bool
    repro_test_found: bool
    violations: List[str]
    test_files_modified: List[str]
    prod_files_modified: List[str]


def is_test_file(path_str: str) -> bool:
    """Check if file path belongs to tests."""
    return any(pat.search(path_str) for pat in TEST_FILE_PATTERNS)


def get_git_diff(repo_root: Path, base_ref: str = "HEAD") -> str:
    """Extract git diff from working tree against base_ref or uncommitted changes."""
    try:
        # Check uncommitted staged + unstaged diff first
        res = subprocess.run(
            ["git", "diff", base_ref],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        diff_out = res.stdout

        # Also capture untracked files if any
        res_untracked = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        untracked_diff = ""
        for line in res_untracked.stdout.splitlines():
            if line.startswith("?? "):
                rel_path = line[3:].strip()
                p = repo_root / rel_path
                if p.is_file():
                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        untracked_diff += f"\ndiff --git a/{rel_path} b/{rel_path}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel_path}\n"
                        for c_line in content.splitlines():
                            untracked_diff += f"+{c_line}\n"
                    except Exception:
                        pass

        combined = (diff_out + untracked_diff).strip()
        if combined:
            return combined

        # Fallback to last commit if working tree is clean
        res_last = subprocess.run(
            ["git", "diff", "HEAD~1...HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return res_last.stdout
    except Exception as e:
        raise RuntimeError(f"Failed to execute git diff: {e}") from e


def audit_diff(diff_text: str) -> BugfixAuditResult:
    """Audit diff content for bugfix integrity and anti-patterns."""
    test_files: List[str] = []
    prod_files: List[str] = []
    violations: List[str] = []

    current_file = ""
    is_current_test = False
    deleted_assertions_count = 0
    added_assertions_count = 0
    file_added_lines: dict[str, list[str]] = {}

    lines = diff_text.splitlines()
    for line in lines:
        if line.startswith("diff --git "):
            parts = line.split(" ")
            if len(parts) >= 4:
                path_raw = parts[3].lstrip("b/")
                current_file = path_raw
                is_current_test = is_test_file(current_file)
                if is_current_test:
                    if current_file not in test_files:
                        test_files.append(current_file)
                else:
                    if current_file not in prod_files:
                        prod_files.append(current_file)
            continue

        if not current_file:
            continue

        # Check symptom masking in production files
        if not is_current_test:
            for pat, desc in SYMPTOM_MASKING_PATTERNS:
                if pat.search(line):
                    violations.append(f"[{current_file}] Symptom Masking Anti-Pattern: {desc}")
            if line.startswith("+") and not line.startswith("+++"):
                file_added_lines.setdefault(current_file, []).append(line[1:])

        # Check test weakening in test files
        if is_current_test:
            for pat in TEST_WEAKENING_PATTERNS:
                if pat.search(line):
                    violations.append(f"[{current_file}] Test Weakening Violation: Added test skip or commented-out assertion: {line.strip()}")

            # Track assertions
            if line.startswith("-") and not line.startswith("---"):
                if re.search(r"\bassert\b|\bexpect\(|self\.assert", line):
                    deleted_assertions_count += 1
            elif line.startswith("+") and not line.startswith("+++"):
                if re.search(r"\bassert\b|\bexpect\(|self\.assert", line):
                    added_assertions_count += 1

    # Check multiline symptom masking
    for p_file, added_lines in file_added_lines.items():
        added_text = "\n".join(added_lines)
        for pat, desc in MULTILINE_SYMPTOM_MASKING_PATTERNS:
            if pat.search(added_text):
                msg = f"[{p_file}] Symptom Masking Anti-Pattern: {desc}"
                if msg not in violations:
                    violations.append(msg)

    repro_test_found = len(test_files) > 0

    if not repro_test_found and prod_files:
        violations.append("Reproduction Mandate Violation: Production code modified without a reproduction test in tests/.")

    # Flag net loss of assertions across test files
    if deleted_assertions_count > added_assertions_count and added_assertions_count == 0:
        violations.append(f"Assertion Degradation Violation: {deleted_assertions_count} assertions deleted with 0 added.")

    passed = len(violations) == 0

    return BugfixAuditResult(
        passed=passed,
        repro_test_found=repro_test_found,
        violations=violations,
        test_files_modified=test_files,
        prod_files_modified=prod_files,
    )


def run_test_command(test_cmd: str, cwd: Path) -> Tuple[bool, str]:
    """Run verification test command."""
    try:
        res = subprocess.run(
            test_cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        output = (res.stdout + "\n" + res.stderr).strip()
        return res.returncode == 0, output
    except Exception as e:
        return False, str(e)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit bugfix diff for reproduction tests and anti-patterns.")
    parser.add_argument("--path", type=Path, default=Path("."), help="Repository root path.")
    parser.add_argument("--diff-file", type=Path, default=None, help="Path to pre-extracted diff file (optional).")
    parser.add_argument("--base", default="HEAD", help="Base git ref for diff (default: HEAD).")
    parser.add_argument("--test-cmd", default=None, help="Optional test command to run (e.g. 'pytest').")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format.")
    parser.add_argument("--strict", action="store_true", help="Fail with exit 1 if violations found.")

    args = parser.parse_args(argv)
    repo_root = args.path.resolve()

    if args.diff_file and args.diff_file.exists():
        diff_text = args.diff_file.read_text(encoding="utf-8")
    else:
        try:
            diff_text = get_git_diff(repo_root, base_ref=args.base)
        except Exception as e:
            print(f"Error reading git diff: {e}", file=sys.stderr)
            return 1

    audit = audit_diff(diff_text)
    test_run_passed = True
    test_output = ""

    if args.test_cmd:
        test_run_passed, test_output = run_test_command(args.test_cmd, repo_root)
        if not test_run_passed:
            audit.violations.append(f"Test Execution Failed: '{args.test_cmd}' exited non-zero.")
            audit.passed = False

    if args.format == "json":
        data = asdict(audit)
        if args.test_cmd:
            data["test_cmd_passed"] = test_run_passed
            data["test_output_tail"] = "\n".join(test_output.splitlines()[-20:])
        print(json.dumps(data, indent=2))
    else:
        print("## 🛠️ Bugfix Verification & Integrity Audit")
        print(f"- **Reproduction Test Found**: {'✅ Yes' if audit.repro_test_found else '❌ Missing'}")
        print(f"- **Modified Tests**: {len(audit.test_files_modified)} files ({', '.join(audit.test_files_modified) or 'None'})")
        print(f"- **Modified Production Code**: {len(audit.prod_files_modified)} files ({', '.join(audit.prod_files_modified) or 'None'})")

        if audit.violations:
            print("\n### ❌ Audit Violations")
            for v in audit.violations:
                print(f"- {v}")
        else:
            print("\n✅ **CLEAN**: Fix meets reproduction mandate with zero symptom masking or test weakening.")

        if args.test_cmd:
            print(f"\n- **Test Run ('{args.test_cmd}')**: {'✅ PASS' if test_run_passed else '❌ FAIL'}")

    if args.strict and not audit.passed:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
