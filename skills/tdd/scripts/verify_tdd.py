#!/usr/bin/env python3
"""
verify_tdd.py — Deterministic TDD Verification and Anti-Pattern Scanner
Zero external dependencies (Python 3.10+ standard library).

Validates:
1. Test-to-Production Parity: Ensures production code changes have corresponding test changes.
2. TDD Anti-Patterns: Detects assertless tests, excessive mocking, and private member inspection.
3. Test Receipt Trimmer: Extracts clean, token-efficient failure stack traces and summaries.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
import sys

# Production file extensions that require test coverage
CODE_EXTENSIONS = {
    ".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".cs", ".cpp", ".c"
}

# Patterns identifying test files
TEST_FILE_PATTERNS = [
    re.compile(r"(?:^|[\\/])(?:test|tests|spec|specs)[\\/]"),
    re.compile(r"[_.-](?:test|spec)\.[a-zA-Z0-9]+$"),
    re.compile(r"(?:^|[\\/])test_[a-zA-Z0-9_]+\.[a-zA-Z0-9]+$"),
]

# Exclusion patterns for non-production logic
EXCLUDE_PATH_PATTERNS = [
    re.compile(r"(?:^|[\\/])(?:\.git|\.scratch|scratch|\.github|docs|dist|build|node_modules|venv|\.venv)[\\/]"),
    re.compile(r"\.(?:md|json|yml|yaml|toml|ini|cfg|txt|sql|html|css|scss|svg|png|jpg)$"),
]


@dataclass
class Finding:
    category: str
    file: str
    line: int
    message: str
    severity: str  # "ERROR" or "WARNING"


@dataclass
class TDDCheckResult:
    passed: bool
    production_files: list[str]
    test_files: list[str]
    untested_files: list[str]
    findings: list[Finding]


def is_test_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(p.search(normalized) for p in TEST_FILE_PATTERNS)


def is_excluded(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(p.search(normalized) for p in EXCLUDE_PATH_PATTERNS)


def is_production_code(path: str) -> bool:
    if is_excluded(path) or is_test_file(path):
        return False
    suffix = Path(path).suffix.lower()
    return suffix in CODE_EXTENSIONS


def get_changed_files(ref_range: str | None = None, repo_root: Path | None = None) -> list[str]:
    """Retrieve changed files from git."""
    root = repo_root or Path.cwd()
    cmd = ["git", "diff", "--name-only"]
    if ref_range:
        cmd.append(ref_range)
    else:
        cmd.append("HEAD")

    try:
        result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=True)
        files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, text=True, check=True
        )
        for line in untracked.stdout.splitlines():
            if line.strip() and line.strip() not in files:
                files.append(line.strip())
        return files
    except subprocess.CalledProcessError:
        return []


def check_anti_patterns(file_path: Path) -> list[Finding]:
    """Audit a test file for common TDD anti-patterns."""
    findings: list[Finding] = []
    if not file_path.is_file():
        return findings

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return findings

    lines = content.splitlines()

    in_test_func = False
    current_func_name = ""
    current_func_line = 0
    func_has_assertion = False
    mock_count = 0

    assertion_pattern = re.compile(
        r"(?:\bassert(?:_|\b)|\.assert|self\.assert|expect\(|\.toBe|\.toEqual|\.toThrow|\.toHave|pytest\.raises|t\.Error|t\.Fatal|require\.)"
    )
    test_def_pattern = re.compile(
        r"^\s*(?:def\s+(test_[a-zA-Z0-9_]+)|func\s+(Test[a-zA-Z0-9_]+)|(?:it|test)\s*\(\s*['\"]([^'\"]+)['\"])"
    )
    private_access_pattern = re.compile(r"\b[a-zA-Z0-9_]+\._[a-zA-Z0-9][a-zA-Z0-9_]*\b")
    mock_pattern = re.compile(
        r"(?:\b|_)(?:mock\w*|patch\w*|magicmock|spyon|sinon|gomock)\b",
        re.IGNORECASE
    )

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("#", "//", "/*", "*")):
            continue

        if private_matches := private_access_pattern.findall(line):
            legit = [m for m in private_matches if not m.startswith("self._")]
            if legit:
                findings.append(Finding(
                    category="whitebox_spy",
                    file=str(file_path),
                    line=i,
                    message=f"Test directly inspects private member(s) ({', '.join(legit)}). Assert on observable public outcomes instead.",
                    severity="WARNING"
                ))

        if mock_pattern.search(line):
            mock_count += 1

        if m := test_def_pattern.search(line):
            if in_test_func and not func_has_assertion:
                findings.append(Finding(
                    category="assertless_test",
                    file=str(file_path),
                    line=current_func_line,
                    message=f"Test '{current_func_name}' contains no detectable assertion. Tests must verify observable behavior.",
                    severity="ERROR"
                ))
            in_test_func = True
            current_func_name = next(filter(None, m.groups()), "unknown_test")
            current_func_line = i
            func_has_assertion = False

        if in_test_func and assertion_pattern.search(line):
            func_has_assertion = True

    if in_test_func and not func_has_assertion:
        findings.append(Finding(
            category="assertless_test",
            file=str(file_path),
            line=current_func_line,
            message=f"Test '{current_func_name}' contains no detectable assertion. Tests must verify observable behavior.",
            severity="ERROR"
        ))

    if mock_count > 8:
        findings.append(Finding(
            category="hollow_mock",
            file=str(file_path),
            line=1,
            message=f"Test file contains {mock_count} mock/spy references. High risk of testing mock setup rather than domain behavior. Prefer in-memory fakes or ephemeral databases.",
            severity="WARNING"
        ))

    return findings


def audit_tdd(files: list[str], repo_root: Path | None = None, strict: bool = False) -> TDDCheckResult:
    """Run full TDD audit across changed files."""
    root = repo_root or Path.cwd()
    prod_files: list[str] = []
    test_files: list[str] = []
    findings: list[Finding] = []

    for f in files:
        if is_production_code(f):
            prod_files.append(f)
        elif is_test_file(f):
            test_files.append(f)

    untested_files: list[str] = []
    if prod_files and not test_files:
        for p in prod_files:
            untested_files.append(p)
            findings.append(Finding(
                category="test_parity",
                file=p,
                line=1,
                message="Production logic modified with ZERO test changes in the changeset. Enforce the Iron Law of Test-First.",
                severity="ERROR"
            ))

    for t in test_files:
        p = root / t if not Path(t).is_absolute() else Path(t)
        findings.extend(check_anti_patterns(p))

    has_errors = any(f.severity == "ERROR" for f in findings)
    passed = not has_errors if strict else True

    return TDDCheckResult(
        passed=passed,
        production_files=prod_files,
        test_files=test_files,
        untested_files=untested_files,
        findings=findings
    )


def trim_test_receipt(raw_output: str, max_lines: int = 40) -> str:
    """
    Trims noisy test runner output (hundreds of compile/download lines)
    down to the failing assertion stack trace and the final summary.
    """
    lines = raw_output.splitlines()
    if len(lines) <= max_lines:
        return raw_output

    failure_lines: list[str] = []
    summary_lines: list[str] = []
    capture_failure = False

    failure_markers = re.compile(r"(?:FAIL|FAILED|ERROR|AssertionError|panic:|Exception:)", re.IGNORECASE)
    summary_markers = re.compile(r"(?:passed|failed|skipped|total|Ran \d+ tests|Tests:|ok\b)", re.IGNORECASE)

    for line in lines:
        if failure_markers.search(line):
            capture_failure = True
        if summary_markers.search(line):
            summary_lines.append(line)
        elif capture_failure:
            failure_lines.append(line)
            if len(failure_lines) >= 25:
                capture_failure = False

    trimmed: list[str] = [
        "--- [TDD Receipt Trimmer: Compact Output] ---",
        f"Original log: {len(lines)} lines -> Trimmed to key failure points & summary:",
        ""
    ]
    if failure_lines:
        trimmed.append("### 🔴 Failure Trace:")
        trimmed.extend(failure_lines[:25])
        trimmed.append("")
    if summary_lines:
        trimmed.append("### 📊 Test Suite Summary:")
        trimmed.extend(summary_lines[-5:])
    else:
        trimmed.extend(lines[-10:])

    return "\n".join(trimmed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic TDD Verification & Anti-Pattern Auditor")
    parser.add_argument("--ref-range", help="Git revision range (e.g. main...HEAD or HEAD~1)")
    parser.add_argument("--files", nargs="*", help="Specific files to audit instead of git diff")
    parser.add_argument("--strict", action="store_true", help="Fail with exit code 1 on any ERROR finding")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--trim-receipt", help="Path to raw test runner output to trim (or '-' for stdin)")

    args = parser.parse_args()

    if args.trim_receipt:
        if args.trim_receipt == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(args.trim_receipt).read_text(encoding="utf-8", errors="replace")
        print(trim_test_receipt(raw))
        return 0

    files_to_check = args.files if args.files else get_changed_files(args.ref_range)
    result = audit_tdd(files_to_check, strict=args.strict)

    if args.json:
        out_dict = asdict(result)
        print(json.dumps(out_dict, indent=2))
        return 0 if result.passed else 1

    print("==================================================")
    print("  TDD Audit & Verification Report")
    print("==================================================")
    print(f"Production files changed : {len(result.production_files)}")
    print(f"Test files changed       : {len(result.test_files)}")
    print(f"Untested production files: {len(result.untested_files)}")
    print("--------------------------------------------------")

    if not result.findings:
        print("✅ PASS: Clean TDD parity. No anti-patterns detected.")
        return 0

    for f in result.findings:
        icon = "❌" if f.severity == "ERROR" else "⚠️"
        print(f"{icon} [{f.severity}] {f.file}:{f.line} ({f.category})")
        print(f"   {f.message}")

    print("--------------------------------------------------")
    if not result.passed:
        print("❌ FAILED: Strict TDD violations detected. Fix errors before advancing.")
        return 1
    else:
        print("⚠️ COMPLETED with warnings. Review findings before advancing.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
