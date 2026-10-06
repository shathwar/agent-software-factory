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
import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Sequence

# Production file extensions that require test coverage
CODE_EXTENSIONS = {
    ".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".cs",
    ".cpp", ".c", ".cc", ".cxx", ".h", ".hpp", ".hxx", ".swift", ".scala", ".dart", ".php", ".mjs", ".cjs"
}

# Patterns identifying test files
TEST_FILE_PATTERNS = [
    re.compile(r"(?:^|[\\/])(?:test|tests|spec|specs)[\\/]"),
    re.compile(r"[_.-](?:test|spec)\.[a-zA-Z0-9]+$"),
    re.compile(r"(?:^|[\\/])test_[a-zA-Z0-9_]+\.[a-zA-Z0-9]+$"),
]

# Exclusion patterns for non-production logic
EXCLUDE_PATH_PATTERNS = [
    re.compile(r"(?:^|[\\/])(?:\.git|\.agentflow|\.scratch|scratch|\.github|docs|dist|build|node_modules|venv|\.venv)[\\/]"),
    re.compile(r"\.(?:md|json|yml|yaml|toml|ini|cfg|txt|sql|html|css|scss|svg|png|jpg)$"),
]

# Patterns identifying pure type / interface / data definitions exempted from 1:1 behavioral unit tests
TYPE_DEFINITION_PATTERNS = [
    re.compile(r"\.d\.ts$"),
    re.compile(r"(?:^|[\\/])(?:types|interfaces|dtos)[\\/].*\.(?:ts|js|py|go|rs|cs|java|kt)$"),
    re.compile(r"(?:^|[\\/])(?:types|interfaces|enums|dtos)\.(?:ts|js|py|go|rs|cs|java|kt)$"),
    re.compile(r"\.(?:types|dto|interface|schema)\.[a-zA-Z0-9]+$"),
    re.compile(r"(?:^|[\\/])(?:schema\.prisma|\.graphqls?|\.proto)$"),
]


class GitDiscoveryError(RuntimeError):
    """Raised when git diff or file discovery fails."""
    pass


@dataclass
class Finding:
    category: str
    file: str
    line: int
    message: str
    severity: str  # "ERROR" or "WARNING"
    rule_id: str = ""



@dataclass
class TDDCheckResult:
    passed: bool
    production_files: list[str]
    test_files: list[str]
    untested_files: list[str]
    findings: list[Finding]
    error: str | None = None


def is_test_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(p.search(normalized) for p in TEST_FILE_PATTERNS)


def is_excluded(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(p.search(normalized) for p in EXCLUDE_PATH_PATTERNS)


def is_type_definition(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(p.search(normalized) for p in TYPE_DEFINITION_PATTERNS)


def is_production_code(path: str) -> bool:
    if is_excluded(path) or is_test_file(path) or is_type_definition(path):
        return False
    suffix = Path(path).suffix.lower()
    return suffix in CODE_EXTENSIONS


def get_changed_files(ref_range: str | None = None, repo_root: Path | None = None) -> list[str]:
    """Retrieve changed files from git."""
    root = repo_root or Path.cwd()
    try:
        files: list[str] = []
        if ref_range:
            cmd = ["git", "diff", "--name-only", ref_range]
            result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=True)
            files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        else:
            has_head = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=root, capture_output=True, text=True
            ).returncode == 0

            if has_head:
                cmd = ["git", "diff", "--name-only", "HEAD"]
                result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=True)
                files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            else:
                staged = subprocess.run(
                    ["git", "diff", "--name-only", "--cached"],
                    cwd=root, capture_output=True, text=True, check=True
                )
                unstaged = subprocess.run(
                    ["git", "diff", "--name-only"],
                    cwd=root, capture_output=True, text=True, check=True
                )
                for line in staged.stdout.splitlines() + unstaged.stdout.splitlines():
                    p = line.strip()
                    if p and p not in files:
                        files.append(p)

        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, text=True, check=True
        )
        for line in untracked.stdout.splitlines():
            if line.strip() and line.strip() not in files:
                files.append(line.strip())
        return files
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.strip() if e.stderr else f"git command failed with exit code {e.returncode}"
        raise GitDiscoveryError(f"Could not inspect changes: {err_msg}") from e
    except FileNotFoundError as e:
        raise GitDiscoveryError("Could not inspect changes: 'git' executable not found") from e


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
        r"(?:\bassert(?:_|\b)|\.assert|self\.assert|expect\s*\(|\.toBe|\.toEqual|\.toThrow|\.toHave|pytest\.(?:raises|warns)|t\.Error|t\.Fatal|require\.)"
    )
    test_def_pattern = re.compile(
        r"^\s*(?:(?:async\s+)?def\s+(test_[a-zA-Z0-9_]+)|func\s+(Test[a-zA-Z0-9_]+)|(?:async\s+)?fn\s+(test_[a-zA-Z0-9_]+)|(?:it|test)(?:\.[a-zA-Z0-9_]+)?\s*\(\s*[`'\"]([^`'\"]+)[`'\"])"
    )
    private_access_pattern = re.compile(r"\b[a-zA-Z0-9_]+\._[a-zA-Z0-9][a-zA-Z0-9_]*\b")
    mock_pattern = re.compile(
        r"(?:\b|_)(?:mock\w*|patch\w*|magicmock|spyon|sinon|gomock)\b",
        re.IGNORECASE
    )

    is_py = file_path.suffix == ".py"
    ast_checked = False
    if is_py:
        try:
            tree = ast.parse(content, filename=str(file_path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                    has_assert = False
                    for child in ast.walk(node):
                        if isinstance(child, ast.Assert):
                            has_assert = True
                            break
                        if isinstance(child, ast.Call):
                            call_name = ""
                            if isinstance(child.func, ast.Name):
                                call_name = child.func.id
                            elif isinstance(child.func, ast.Attribute):
                                call_name = child.func.attr
                            if call_name.startswith("assert") or call_name in {"raises", "warns", "fail"}:
                                has_assert = True
                                break
                    if not has_assert:
                        findings.append(Finding(
                            category="assertless_test",
                            file=str(file_path),
                            line=node.lineno,
                            message=f"Test '{node.name}' contains no detectable assertion. Tests must verify observable behavior.",
                            severity="ERROR",
                            rule_id="TDD-ASRT-001",
                        ))
                    # Tautological assertion detection
                    for child in ast.walk(node):
                        if isinstance(child, ast.Assert) and isinstance(child.test, ast.Constant) and child.test.value is True:
                            findings.append(Finding(
                                category="tautological_assertion",
                                file=str(file_path),
                                line=child.lineno,
                                message="Tautological assertion ('assert True') detected. Tests must assert actual observable behavior.",
                                severity="ERROR",
                                rule_id="TDD-TAUT-001",
                            ))
                        if isinstance(child, ast.Call):
                            call_attr = getattr(child.func, "attr", "")
                            if call_attr in {"assertTrue", "assert_true"} and child.args and isinstance(child.args[0], ast.Constant) and child.args[0].value is True:
                                findings.append(Finding(
                                    category="tautological_assertion",
                                    file=str(file_path),
                                    line=child.lineno,
                                    message="Tautological assertion ('assertTrue(True)') detected. Tests must assert actual observable behavior.",
                                    severity="ERROR",
                                    rule_id="TDD-TAUT-001",
                                ))
            ast_checked = True
        except SyntaxError:
            ast_checked = False

    db_mock_pattern = re.compile(
        r"(?:patch|mock)\w*\(.*(?:psycopg|sqlite3|mysql|pg_client|postgres|redis|ioredis|prisma|sqlalchemy|cursor)",
        re.IGNORECASE,
    )
    tautological_pattern = re.compile(
        r"\bassert\s+True\b|\bassertTrue\(\s*True\s*\)|\bexpect\(\s*true\s*\)\.toBe\(\s*true\s*\)",
        re.IGNORECASE,
    )

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("#", "//", "/*", "*")):
            continue

        if db_mock_pattern.search(line):
            findings.append(Finding(
                category="mocked_database",
                file=str(file_path),
                line=i,
                message="Mocking of database engine/client detected. Violates Tier 2 Dual-Speed Rule: use ephemeral SQLite/containers.",
                severity="ERROR",
                rule_id="TDD-MOCK-DB-001",
            ))

        if not ast_checked and tautological_pattern.search(line):
            findings.append(Finding(
                category="tautological_assertion",
                file=str(file_path),
                line=i,
                message="Tautological assertion detected. Tests must assert actual observable behavior.",
                severity="ERROR",
                rule_id="TDD-TAUT-001",
            ))

        if private_matches := private_access_pattern.findall(line):
            legit = [
                m for m in private_matches
                if not m.startswith("self._") and not (m.endswith("__") and ".__" in m)
            ]
            if legit:
                findings.append(Finding(
                    category="whitebox_spy",
                    file=str(file_path),
                    line=i,
                    message=f"Test directly inspects private member(s) ({', '.join(legit)}). Assert on observable public outcomes instead.",
                    severity="WARNING",
                    rule_id="TDD-SPY-001",
                ))

        if mock_pattern.search(line):
            mock_count += 1

        if not ast_checked:
            if m := test_def_pattern.search(line):
                if in_test_func and not func_has_assertion:
                    findings.append(Finding(
                        category="assertless_test",
                        file=str(file_path),
                        line=current_func_line,
                        message=f"Test '{current_func_name}' contains no detectable assertion. Tests must verify observable behavior.",
                        severity="ERROR",
                        rule_id="TDD-ASRT-001",
                    ))
                in_test_func = True
                current_func_name = next(filter(None, m.groups()), "unknown_test")
                current_func_line = i
                func_has_assertion = False

            if in_test_func and assertion_pattern.search(line):
                func_has_assertion = True

    if not ast_checked and in_test_func and not func_has_assertion:
        findings.append(Finding(
            category="assertless_test",
            file=str(file_path),
            line=current_func_line,
            message=f"Test '{current_func_name}' contains no detectable assertion. Tests must verify observable behavior.",
            severity="ERROR",
            rule_id="TDD-ASRT-001",
        ))

    if mock_count > 8:
        findings.append(Finding(
            category="hollow_mock",
            file=str(file_path),
            line=1,
            message=f"Test file contains {mock_count} mock/spy references. High risk of testing mock setup rather than domain behavior. Prefer in-memory fakes or ephemeral databases.",
            severity="WARNING",
            rule_id="TDD-MOCK-001",
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
                severity="ERROR",
                rule_id="TDD-PAR-001",
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

    failure_markers = re.compile(r"(?:\b(?:FAIL|FAILED|ERROR|AssertionError|panic)\b|\bException:)", re.IGNORECASE)
    summary_markers = re.compile(r"(?:passed|failed|skipped|total|Ran \d+ tests|Tests:|ok\b)", re.IGNORECASE)

    for line in lines:
        if summary_markers.search(line):
            summary_lines.append(line)
            capture_failure = False
        elif failure_markers.search(line):
            capture_failure = True
            failure_lines.append(line)
            if len(failure_lines) >= 25:
                capture_failure = False
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


def verify_tdd(ref_range: str | None = None, files: list[str] | None = None, repo_root: Path | None = None, strict: bool = False) -> TDDCheckResult:
    """Convenience function to run TDD parity and anti-pattern audit on changed or specified files."""
    try:
        files_to_check = files if files else get_changed_files(ref_range, repo_root=repo_root)
        return audit_tdd(files_to_check, repo_root=repo_root, strict=strict)
    except GitDiscoveryError as e:
        return TDDCheckResult(
            passed=False,
            production_files=[],
            test_files=[],
            untested_files=[],
            findings=[
                Finding(
                    category="git_discovery",
                    file="git",
                    line=1,
                    message=str(e),
                    severity="ERROR",
                    rule_id="TDD-GIT-001",
                )
            ],
            error=str(e),
        )


def audit_test_diff(diff_text: str) -> list[Finding]:
    """Audit a git diff to detect test weakening or deletion of assertions."""
    findings: list[Finding] = []
    lines = diff_text.splitlines()

    current_file = ""
    in_test_file = False
    deleted_asserts = 0
    added_asserts = 0

    assert_kw = re.compile(r"(?:\bassert(?:_|\b)|\.assert|self\.assert|expect\(|\.toBe|\.toEqual)", re.IGNORECASE)

    for line in lines:
        if line.startswith("diff --git"):
            if in_test_file and deleted_asserts > added_asserts:
                findings.append(Finding(
                    category="test_weakening",
                    file=current_file,
                    line=1,
                    message=f"Test weakening detected in '{current_file}': {deleted_asserts} assertion(s) removed but only {added_asserts} added. Do not weaken tests to pass faulty implementations.",
                    severity="ERROR",
                    rule_id="TDD-WEAK-001",
                ))
            deleted_asserts = 0
            added_asserts = 0
            parts = line.split()
            current_file = parts[-1].lstrip("b/") if len(parts) >= 4 else "unknown"
            in_test_file = is_test_file(current_file)
        elif in_test_file:
            if line.startswith("-") and not line.startswith("---"):
                if assert_kw.search(line):
                    deleted_asserts += 1
            elif line.startswith("+") and not line.startswith("+++"):
                if assert_kw.search(line):
                    added_asserts += 1

    if in_test_file and deleted_asserts > added_asserts:
        findings.append(Finding(
            category="test_weakening",
            file=current_file,
            line=1,
            message=f"Test weakening detected in '{current_file}': {deleted_asserts} assertion(s) removed but only {added_asserts} added. Do not weaken tests to pass faulty implementations.",
            severity="ERROR",
            rule_id="TDD-WEAK-001",
        ))


    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic TDD Verification & Anti-Pattern Auditor")
    parser.add_argument("--ref-range", help="Git revision range (e.g. main...HEAD or HEAD~1)")
    parser.add_argument("--files", nargs="*", help="Specific files to audit instead of git diff")
    parser.add_argument("--strict", action="store_true", help="Fail with exit code 1 on any ERROR finding")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--trim-receipt", help="Path to raw test runner output to trim (or '-' for stdin)")
    parser.add_argument("--audit-diff", help="Path to git diff file (or '-' for stdin) to audit for test weakening")

    args = parser.parse_args(argv)

    if args.trim_receipt:
        if args.trim_receipt == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(args.trim_receipt).read_text(encoding="utf-8", errors="replace")
        print(trim_test_receipt(raw))
        return 0

    if args.audit_diff:
        if args.audit_diff == "-":
            raw_diff = sys.stdin.read()
        else:
            raw_diff = Path(args.audit_diff).read_text(encoding="utf-8", errors="replace")
        diff_findings = audit_test_diff(raw_diff)
        if args.json:
            print(json.dumps([asdict(f) for f in diff_findings], indent=2))
        else:
            print(f"Test Diff Weakening Audit: {'PASSED' if not diff_findings else 'FAILED'}")
            for f in diff_findings:
                print(f"  • [{f.severity}] {f.file}: {f.message}")
        return 1 if diff_findings else 0

    try:
        files_to_check = args.files if args.files else get_changed_files(args.ref_range)
        result = audit_tdd(files_to_check, strict=args.strict)
    except GitDiscoveryError as e:
        result = TDDCheckResult(
            passed=False,
            production_files=[],
            test_files=[],
            untested_files=[],
            findings=[
                Finding(
                    category="git_discovery",
                    file="git",
                    line=1,
                    message=str(e),
                    severity="ERROR",
                )
            ],
            error=str(e),
        )

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
