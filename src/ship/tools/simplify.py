#!/usr/bin/env python3
"""Scan codebases for simplify: technical debt markers and validate syntax.

Zero external dependencies (Python 3.10+ standard library).

Valid Syntax:
    // simplify: <Shortcut>. Ceiling: <Threshold/Limit>. Upgrade: <Next Architecture>.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tokenize
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_EXCLUDES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
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
        help="Exit with non-zero status if any invalid debt markers are found.",
    )

    args = parser.parse_args(argv)
    markers = scan_paths(args.paths)

    if args.format == "json":
        print(json.dumps(markers, indent=2))
    else:
        print(format_table(markers, markdown=(args.format == "markdown")))

    if args.strict and any(not m["is_valid"] for m in markers):
        sys.stderr.write(f"\nError: Found {sum(1 for m in markers if not m['is_valid'])} invalid debt marker(s).\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
