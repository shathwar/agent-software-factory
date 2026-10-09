#!/usr/bin/env python3
"""Scan codebases for simplify: technical debt markers and validate syntax.

Zero external dependencies (Python 3.10+ standard library).

Valid Syntax:
    // simplify: <Shortcut>. Ceiling: <Threshold/Limit>. Upgrade: <Next Architecture>.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys
import tokenize
from typing import Any, Dict, List, Optional, Sequence, Tuple

REDUNDANT_DEPENDENCIES: Dict[str, str] = {
    "uuid": "Use native crypto.randomUUID()",
    "lodash.clonedeep": "Use native structuredClone()",
    "rimraf": "Use fs.promises.rm(dir, { recursive: true, force: true })",
    "mkdirp": "Use fs.promises.mkdir(dir, { recursive: true })",
    "node-fetch": "Use native global fetch()",
    "pytz": "Use standard library zoneinfo.ZoneInfo (Python 3.9+)",
    "mock": "Use standard library unittest.mock (Python 3.3+)",
    "six": "Remove dead Python 2 compatibility layer",
    "simplejson": "Use standard library json",
    "pathlib2": "Use standard library pathlib (Python 3.4+)",
    "axios": "Use native global fetch() in Node 18+ or standard library",
    "dotenv": "Use Node 20+ native flag (--env-file=.env) or standard library os.environ",
    "chalk": "Use native ANSI escape codes or Node util.styleText()",
}


DEFAULT_EXCLUDES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".agentflow",
    ".scratch",
    "scratch",
    ".idea",
    ".vscode",
    "build",
    "dist",
}

IGNORE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf",
    ".zip", ".tar", ".gz", ".lock", ".lockb", ".woff", ".woff2", ".ttf", ".eot",
}

# Regex to find simplify: marker comment line
MARKER_PATTERN = re.compile(
    r"(?:^\s*(?://|#|/\*|\*|--|<!--|;|%)?|(?<=[\s;])(?://|#|/\*|\*|--|<!--|;|%))\s*simplify:\s*(.+)$",
    re.IGNORECASE,
)

# Field extractors: stop at next delimiter token or end of line
CEILING_PATTERN = re.compile(
    r"Ceiling:\s*(.+?)(?=(?:\s*[|;.]\s*Upgrade:|\s+Upgrade:|\s*$))",
    re.IGNORECASE,
)
UPGRADE_PATTERN = re.compile(
    r"Upgrade:\s*(.+?)(?=(?:\s*[|;.]\s*Ceiling:|\s+Ceiling:|\s*$))",
    re.IGNORECASE,
)


def parse_debt_marker(raw_text: str, file_path: str, line_number: int) -> Dict[str, Any]:
    """Parse and validate a single simplify debt marker line."""
    match = MARKER_PATTERN.search(raw_text)
    if not match:
        return {}

    body = match.group(1).strip()

    # Strip any trailing comment closing tokens (*/, -->, etc.)
    body = re.sub(r"(\*/|-->|\?>)$", "", body).strip()

    ceiling_match = CEILING_PATTERN.search(body)
    upgrade_match = UPGRADE_PATTERN.search(body)

    ceiling: Optional[str] = None
    upgrade: Optional[str] = None
    shortcut: str = ""
    errors: List[str] = []

    if ceiling_match:
        extracted_ceiling = ceiling_match.group(1).strip().strip(".|; ")
        if extracted_ceiling:
            ceiling = extracted_ceiling
        else:
            errors.append("Empty 'Ceiling:' threshold")
    else:
        errors.append("Missing 'Ceiling:' threshold")

    if upgrade_match:
        extracted_upgrade = upgrade_match.group(1).strip().strip(".|; ")
        if extracted_upgrade:
            upgrade = extracted_upgrade
        else:
            errors.append("Empty 'Upgrade:' path")
    else:
        errors.append("Missing 'Upgrade:' path")

    # Extract shortcut (everything before the first field)
    first_start = len(body)
    if ceiling_match:
        first_start = min(first_start, ceiling_match.start())
    if upgrade_match:
        first_start = min(first_start, upgrade_match.start())

    shortcut = body[:first_start].strip().strip(".|; ")

    if not shortcut or shortcut.lower() in {"todo", "fixme", "clean this up", "optimize", "temp"}:
        errors.append(f"Vague or missing shortcut description: '{shortcut}'")
    elif (shortcut.startswith("<") and shortcut.endswith(">")) or shortcut.strip("<>").lower() in {"shortcut", "desc", "description"}:
        errors.append(f"Unreplaced template placeholder in shortcut description: '{shortcut}'")

    if ceiling:
        if ceiling.lower() in {"none", "n/a", "tbd", "todo", "fixme"}:
            errors.append(f"Vague or placeholder 'Ceiling:' threshold: '{ceiling}'")
        elif (ceiling.startswith("<") and ceiling.endswith(">")) or ceiling.strip("<>").lower() in {"threshold/limit", "threshold", "limit", "ceiling"}:
            errors.append(f"Unreplaced template placeholder in 'Ceiling:' threshold: '{ceiling}'")

    if upgrade:
        if upgrade.lower() in {"none", "n/a", "tbd", "todo", "fixme"}:
            errors.append(f"Vague or placeholder 'Upgrade:' path: '{upgrade}'")
        elif (upgrade.startswith("<") and upgrade.endswith(">")) or upgrade.strip("<>").lower() in {"next architecture", "architecture", "upgrade", "action"}:
            errors.append(f"Unreplaced template placeholder in 'Upgrade:' path: '{upgrade}'")

    is_valid = len(errors) == 0

    return {
        "file": file_path,
        "line": line_number,
        "shortcut": shortcut,
        "ceiling": ceiling or "N/A",
        "upgrade": upgrade or "N/A",
        "is_valid": is_valid,
        "errors": errors,
        "raw": raw_text.strip(),
    }


def scan_python_file(file_path: Path, rel_path: str) -> Optional[List[Dict[str, Any]]]:
    """Scan a Python file using Python's standard-library tokenizer to identify comments and ignore string literals."""
    markers = []
    try:
        with file_path.open("rb") as f:
            tokens = tokenize.tokenize(f.readline)
            for tok in tokens:
                if tok.type == tokenize.COMMENT:
                    text = tok.string
                    if "simplify:" in text.lower():
                        parsed = parse_debt_marker(text, rel_path, tok.start[0])
                        if parsed:
                            markers.append(parsed)
        return markers
    except Exception:
        return None


def scan_file(file_path: Path, base_dir: Path) -> List[Dict[str, Any]]:
    """Scan a single text file for debt markers."""
    if file_path.suffix.lower() in IGNORE_EXTENSIONS:
        return []

    try:
        # Fast binary file detection
        with file_path.open("rb") as f:
            chunk = f.read(1024)
            if b"\0" in chunk:
                return []
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    content_lower = content.lower()
    if "simplify:" not in content_lower:
        return []

    try:
        rel_path = str(file_path.relative_to(Path.cwd().resolve()))
    except ValueError:
        rel_path = str(file_path.relative_to(base_dir))

    if file_path.suffix.lower() == ".py":
        py_markers = scan_python_file(file_path, rel_path)
        if py_markers is not None:
            return py_markers

    markers = []
    is_markdown = file_path.suffix.lower() in {".md", ".markdown"}
    in_text_fence = False

    for idx, line in enumerate(content.splitlines(), start=1):
        if is_markdown:
            stripped = line.strip()
            if stripped.startswith("```"):
                tag = stripped[3:].strip().lower()
                if not in_text_fence:
                    if tag in {"text", "txt", "plain"}:
                        in_text_fence = True
                else:
                    in_text_fence = False
                continue
            if in_text_fence:
                continue
            if re.match(r"^\s*#{1,6}\s+", line):
                continue

        if "simplify:" in line.lower():
            parsed = parse_debt_marker(line, rel_path, idx)
            if parsed:
                markers.append(parsed)

    return markers


def scan_paths(
    targets: Sequence[str | Path],
    excludes: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    """Recursively scan files and directories for debt markers."""
    if excludes is None:
        excludes = DEFAULT_EXCLUDES

    all_markers: List[Dict[str, Any]] = []

    for target in targets:
        p = Path(target).resolve()
        if p.is_file():
            base = p.parent
            all_markers.extend(scan_file(p, base))
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                # Filter directories in-place
                dirs[:] = [d for d in dirs if d not in excludes and not d.startswith(".")]
                root_path = Path(root)
                for file_name in files:
                    if file_name.startswith("."):
                        continue
                    file_path = root_path / file_name
                    all_markers.extend(scan_file(file_path, p))

    return all_markers


def format_table(markers: List[Dict[str, Any]], markdown: bool = True) -> str:
    """Format markers as a markdown table."""
    if not markers:
        return "No technical debt markers found. Codebase is clean."

    lines = []
    lines.append("| Location | Shortcut Taken | Operational Ceiling | Designated Upgrade Path | Status |")
    lines.append("|---|---|---|---|---|")
    for m in markers:
        loc = f"`{m['file']}:{m['line']}`"
        shortcut = m["shortcut"].replace("|", "\\|")
        ceiling = m["ceiling"].replace("|", "\\|")
        upgrade = m["upgrade"].replace("|", "\\|")
        status = "✅ Valid" if m["is_valid"] else f"❌ Invalid: {', '.join(m['errors'])}"
        lines.append(f"| {loc} | {shortcut} | {ceiling} | {upgrade} | {status} |")

    return "\n".join(lines)


def audit_code_simplicity(
    file_path: Path | str,
    content: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Audit source files for unrequested speculative abstractions, redundant dependencies, and shallow wrappers."""
    path = Path(file_path)
    if content is None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

    findings: List[Dict[str, Any]] = []
    lines = content.splitlines()

    # 1. Redundant dependencies (Laziness Ladder Rung 3 & 5)
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith(("#", "//", "/*", "*")):
            continue
        for dep, replacement in REDUNDANT_DEPENDENCIES.items():
            pattern = rf"""(?:import\s+.*\s+from\s+['"]{re.escape(dep)}['"]|require\s*\(\s*['"]{re.escape(dep)}['"]\s*\)|import\s+{re.escape(dep)}\b)"""
            if re.search(pattern, stripped):
                findings.append({
                    "rule_id": "SMP-DEP-001",
                    "file": str(path),
                    "line": i,
                    "severity": "ERROR",
                    "message": f"Redundant external dependency '{dep}' detected. Laziness Ladder violation: {replacement}.",
                })

    # 2. Speculative factories and shallow wrappers in Python files
    if path.suffix == ".py":
        try:
            tree = ast.parse(content, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Speculative factory check
                    if node.name.endswith("Factory") and len(node.body) <= 3:
                        findings.append({
                            "rule_id": "SMP-ABS-001",
                            "file": str(path),
                            "line": node.lineno,
                            "severity": "WARNING",
                            "message": f"Speculative factory class '{node.name}' detected with minimal implementation. Favor direct concrete instantiation.",
                        })
                    # Shallow wrapper check (class forwarding calls with 1-line return self._inner.foo())
                    methods = [m for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    non_dunder = [m for m in methods if not m.name.startswith("__")]
                    forwarding_count = 0
                    for m in non_dunder:
                        if len(m.body) == 1 and isinstance(m.body[0], ast.Return):
                            ret_val = m.body[0].value
                            if isinstance(ret_val, ast.Call) and isinstance(ret_val.func, ast.Attribute):
                                if isinstance(ret_val.func.value, ast.Attribute) and (
                                    ret_val.func.value.attr.startswith(("_", "repo", "inner", "service"))
                                    or ret_val.func.value.attr in {"inner", "repo", "service"}
                                ):
                                    forwarding_count += 1
                    if len(non_dunder) >= 1 and forwarding_count == len(non_dunder):
                        findings.append({
                            "rule_id": "SMP-WRAP-001",
                            "file": str(path),
                            "line": node.lineno,
                            "severity": "WARNING",
                            "message": f"Shallow wrapper class '{node.name}' forwards all calls without domain logic. Deepen the module or eliminate the wrapper layer.",
                        })
        except SyntaxError:
            pass

    return findings


def audit_paths_simplicity(
    targets: Sequence[str | Path],
    excludes: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    """Recursively audit paths for simplicity anti-patterns."""
    if excludes is None:
        excludes = DEFAULT_EXCLUDES

    findings: List[Dict[str, Any]] = []
    for target in targets:
        p = Path(target).resolve()
        if p.is_file():
            findings.extend(audit_code_simplicity(p))
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in excludes and not d.startswith(".")]
                for file_name in files:
                    if file_name.startswith("."):
                        continue
                    file_path = Path(root) / file_name
                    if file_path.suffix.lower() in {".py", ".ts", ".js", ".tsx", ".jsx", ".go"}:
                        findings.extend(audit_code_simplicity(file_path))
    return findings


def scan_debt(paths: Optional[Sequence[Path | str]] = None, strict: bool = False) -> Tuple[List[Dict[str, Any]], bool]:
    """Convenience function to scan paths for debt markers and return (markers, has_errors)."""
    target_paths = [Path(p) for p in paths] if paths else [Path.cwd()]
    markers = scan_paths(target_paths)
    has_errors = any(not m.get("is_valid", True) for m in markers)
    return markers, has_errors


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan codebases for simplify: technical debt markers and validate syntax."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to scan (default: current directory).",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "table", "json"],
        default="markdown",
        help="Output format (default: markdown).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero status if any invalid debt markers or simplicity errors are found.",
    )
    parser.add_argument(
        "--audit-code",
        action="store_true",
        help="Audit source code for redundant dependencies, shallow wrappers, and speculative abstractions.",
    )

    args = parser.parse_args(argv)
    markers = scan_paths(args.paths)
    code_findings: List[Dict[str, Any]] = []
    if args.audit_code:
        code_findings = audit_paths_simplicity(args.paths)

    if args.format == "json":
        output = {"markers": markers, "code_findings": code_findings} if args.audit_code else markers
        print(json.dumps(output, indent=2))
    else:
        print(format_table(markers, markdown=(args.format == "markdown")))
        if code_findings:
            print("\n### 🔍 Code Simplicity Findings:")
            for f in code_findings:
                icon = "❌" if f["severity"] == "ERROR" else "⚠️"
                print(f"  {icon} [{f['rule_id']}] `{f['file']}:{f['line']}`: {f['message']}")

    has_invalid_markers = any(not m["is_valid"] for m in markers)
    has_code_errors = any(f["severity"] == "ERROR" for f in code_findings)

    if args.strict and (has_invalid_markers or has_code_errors):
        inv_count = sum(1 for m in markers if not m["is_valid"])
        code_errs = sum(1 for f in code_findings if f["severity"] == "ERROR")
        if code_errs == 0:
            sys.stderr.write(f"\nError: Found {inv_count} invalid debt marker(s).\n")
        else:
            sys.stderr.write(f"\nError: Found {inv_count + code_errs} simplify violation(s).\n")
        return 1

    return 0



if __name__ == "__main__":
    sys.exit(main())

