#!/usr/bin/env python3
"""audit_ux.py / ux.py — Deterministic UX, Accessibility, and Design Token Scanner.

Zero external dependencies (Python 3.10+ standard library).

Rule Catalog:
- UX-001 (ERROR): Interactive non-native element (div/span) lacks keyboard interaction. Prefer native <button>.
- UX-002 (ERROR): Suppressed focus outline without replacement indicator (ring, box-shadow, border).
- UX-003 (ERROR): Icon-only button has no accessible name (missing aria-label, aria-labelledby, sr-only).
- UX-014 (ERROR): Form input/textarea/select element has no accessible name.
- UX-041 (ERROR): Modal dialog lacks accessible name (missing aria-label, aria-labelledby, or title).
- UX-005 (WARNING): Dead-end error message lacks actionable recovery CTA.
- UX-021 (WARNING): Arbitrary spacing/dimension value bypasses design tokens.
- UX-051 (WARNING): Dynamic collection rendering lacks empty state or loading skeleton handling.
- UX-031 (INFO): Icon button uses title attribute instead of preferred aria-label or sr-only text.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

TARGET_EXTENSIONS = {
    ".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".astro"
}

DEFAULT_EXCLUDES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".agentflow", ".scratch", "scratch", ".idea", ".vscode",
    "build", "dist", ".next", ".nuxt", "coverage",
}

SEVERITY_LEVELS = {
    "CRITICAL": 4,
    "ERROR": 3,
    "WARNING": 2,
    "INFO": 1,
}

DEFAULT_ALLOWED_ARBITRARY = {
    "0", "1px", "2px", "100%", "auto", "inherit", "100vh", "100vw",
    "full", "fit-content", "min-content", "max-content", "screen",
}

# Regex Patterns
CLICK_HANDLER_PATTERN = re.compile(
    r"""<(div|span|p|section|article)\b([^>]*?)(?:onClick|@click|v-on:click|onclick)=([^>]*?)>""",
    re.IGNORECASE | re.DOTALL,
)

KEYBOARD_HANDLER_PATTERN = re.compile(
    r"""\b(?:onKeyDown|onKeyUp|onKeyPress|@keydown|@keyup|v-on:keydown|v-on:keyup)\b""",
    re.IGNORECASE,
)

OUTLINE_NONE_PATTERN = re.compile(
    r"""(?:\boutline-none\b|\bfocus:outline-none\b|outline\s*:\s*(?:none|0))""",
    re.IGNORECASE,
)

FOCUS_REPLACEMENT_PATTERN = re.compile(
    r"""(?:\bfocus(?:-visible)?:(?:ring|border|shadow|outline-[a-z0-9_-]+)\b|\bring-|\bbox-shadow\b|\bvar\(--(?:focus-ring|ring)\)|\bshadow-)""",
    re.IGNORECASE,
)

BUTTON_ELEMENT_PATTERN = re.compile(
    r"""<(?:button\b|a\b[^>]*\brole\s*=\s*["']button["'])([^>]*)>(.*?)</(?:button|a)>""",
    re.IGNORECASE | re.DOTALL,
)

INPUT_PATTERN = re.compile(
    r"""<(input|textarea|select)\b([^>]*?)>""",
    re.IGNORECASE | re.DOTALL,
)

LABEL_FOR_PATTERN = re.compile(
    r"""<label\b[^>]*?(?:for|htmlFor)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)

IMG_PATTERN = re.compile(
    r"""<(?:img|Image)\b([^>]*?)>""",
    re.IGNORECASE | re.DOTALL,
)

GENERIC_ERROR_PATTERN = re.compile(
    r"""(?:["'`](?:An error occurred|Something went wrong|Error loading data|Unknown error)["'`]|>(?:\s*(?:An error occurred|Something went wrong|Error loading data|Unknown error)\s*)[<])""",
    re.IGNORECASE,
)

RECOVERY_CTA_PATTERN = re.compile(
    r"""\b(?:retry|reload|refresh|try again|contact|support|go back|return)\b""",
    re.IGNORECASE,
)

ARBITRARY_TAILWIND_PATTERN = re.compile(
    r"""(?:\b|(?<=[\s"'`]))([a-zA-Z0-9_-]*(?:p|m|px|py|pl|pr|pt|pb|mx|my|ml|mr|mt|mb|top|bottom|left|right|w|h|gap|inset)-\[([^\]]+)\])"""
)

DIALOG_PATTERN = re.compile(
    r"""<(?:dialog\b|div\b[^>]*\brole\s*=\s*["']dialog["'])([^>]*)>""",
    re.IGNORECASE | re.DOTALL,
)

MAP_COLLECTION_PATTERN = re.compile(
    r"""\b(\w+)\.map\s*\(""",
    re.IGNORECASE,
)


@dataclass
class UXViolation:
    rule_id: str
    severity: str  # CRITICAL, ERROR, WARNING, INFO
    message: str
    file_path: str
    line_number: int
    snippet: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def check_clickable_elements(content: str, file_path: str) -> List[UXViolation]:
    violations: List[UXViolation] = []
    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        for match in CLICK_HANDLER_PATTERN.finditer(line):
            tag = match.group(1).lower()
            attrs = match.group(2) + " " + match.group(3)
            has_keyboard = bool(KEYBOARD_HANDLER_PATTERN.search(attrs) or KEYBOARD_HANDLER_PATTERN.search(line))

            if not has_keyboard:
                violations.append(UXViolation(
                    rule_id="UX-001",
                    severity="ERROR",
                    message=f"Interactive-looking non-native <{tag}> lacks keyboard interaction (Enter/Space). Prefer native <button> over ARIA remediation.",
                    file_path=file_path,
                    line_number=idx,
                    snippet=line.strip()[:100],
                ))
    return violations


def check_focus_indicators(content: str, file_path: str) -> List[UXViolation]:
    violations: List[UXViolation] = []
    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        if OUTLINE_NONE_PATTERN.search(line):
            if not FOCUS_REPLACEMENT_PATTERN.search(line):
                violations.append(UXViolation(
                    rule_id="UX-002",
                    severity="ERROR",
                    message="Suppressed focus outline (outline-none) without replacement indicator (ring, box-shadow, or border).",
                    file_path=file_path,
                    line_number=idx,
                    snippet=line.strip()[:100],
                ))
    return violations


def check_icon_buttons(content: str, file_path: str) -> List[UXViolation]:
    violations: List[UXViolation] = []

    for match in BUTTON_ELEMENT_PATTERN.finditer(content):
        attrs = match.group(1)
        body = match.group(2).strip()

        stripped_body = re.sub(r"""<[^>]+>""", "", body).strip()
        has_icon_tag = bool(re.search(r"""<(?:svg|i|Icon|Lucide|Feather)\b""", body, re.IGNORECASE))

        if has_icon_tag and not stripped_body:
            has_aria_label = bool(re.search(r"""\b(?:aria-label|aria-labelledby)\s*=""", attrs, re.IGNORECASE))
            has_sr_text = bool(re.search(r"""(?:sr-only|visually-hidden)""", body, re.IGNORECASE))
            has_title = bool(re.search(r"""\btitle\s*=""", attrs, re.IGNORECASE))

            line_no = content[:match.start()].count("\n") + 1

            if not (has_aria_label or has_sr_text or has_title):
                violations.append(UXViolation(
                    rule_id="UX-003",
                    severity="ERROR",
                    message="Icon-only button has no accessible name (missing aria-label, aria-labelledby, or .sr-only text).",
                    file_path=file_path,
                    line_number=line_no,
                    snippet=match.group(0).splitlines()[0].strip()[:100],
                ))
            elif has_title and not (has_aria_label or has_sr_text):
                violations.append(UXViolation(
                    rule_id="UX-031",
                    severity="INFO",
                    message="Icon button uses title attribute rather than aria-label or visually-hidden text.",
                    file_path=file_path,
                    line_number=line_no,
                    snippet=match.group(0).splitlines()[0].strip()[:100],
                ))
    return violations


def check_form_labels(content: str, file_path: str) -> List[UXViolation]:
    violations: List[UXViolation] = []
    lines = content.splitlines()

    associated_label_ids = set(LABEL_FOR_PATTERN.findall(content))

    for idx, line in enumerate(lines, start=1):
        for match in INPUT_PATTERN.finditer(line):
            tag = match.group(1).lower()
            attrs = match.group(2)

            input_type_match = re.search(r"""type\s*=\s*["']([^"']+)["']""", attrs, re.IGNORECASE)
            if input_type_match and input_type_match.group(1).lower() in {"hidden", "submit", "button", "reset"}:
                continue

            has_aria_label = bool(re.search(r"""\b(?:aria-label|aria-labelledby)\s*=""", attrs, re.IGNORECASE))
            id_match = re.search(r"""\bid\s*=\s*["']([^"']+)["']""", attrs, re.IGNORECASE)
            has_matching_label = bool(id_match and id_match.group(1) in associated_label_ids)

            start_pos = match.start()
            preceding_chunk = content[max(0, start_pos - 300):start_pos]
            is_wrapped_in_label = ("<label" in preceding_chunk and "</label>" not in preceding_chunk)

            if not (has_aria_label or has_matching_label or is_wrapped_in_label):
                violations.append(UXViolation(
                    rule_id="UX-014",
                    severity="ERROR",
                    message=f"Form <{tag}> element has no accessible name (missing associated <label for>, aria-label, or aria-labelledby).",
                    file_path=file_path,
                    line_number=idx,
                    snippet=line.strip()[:100],
                ))
    return violations


def check_arbitrary_tokens(content: str, file_path: str, allowed_tokens: Set[str]) -> List[UXViolation]:
    violations: List[UXViolation] = []
    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        for match in ARBITRARY_TAILWIND_PATTERN.finditer(line):
            full_class = match.group(1)
            raw_val = match.group(2).strip().lower()

            if raw_val not in allowed_tokens:
                violations.append(UXViolation(
                    rule_id="UX-021",
                    severity="WARNING",
                    message=f"Arbitrary value: '{full_class}'. Avoid arbitrary values when existing tokens satisfy; permit when justified.",
                    file_path=file_path,
                    line_number=idx,
                    snippet=line.strip()[:100],
                ))
    return violations


def check_dead_end_errors(content: str, file_path: str) -> List[UXViolation]:
    violations: List[UXViolation] = []
    lines = content.splitlines()

    for idx, line in enumerate(lines, start=1):
        if GENERIC_ERROR_PATTERN.search(line):
            start_window = max(0, idx - 5)
            end_window = min(len(lines), idx + 5)
            window_text = " ".join(lines[start_window:end_window])

            if not RECOVERY_CTA_PATTERN.search(window_text):
                violations.append(UXViolation(
                    rule_id="UX-005",
                    severity="WARNING",
                    message="Generic error message without actionable recovery action (e.g. Retry, Reload, Contact).",
                    file_path=file_path,
                    line_number=idx,
                    snippet=line.strip()[:100],
                ))
    return violations


def check_modal_dialogs(content: str, file_path: str) -> List[UXViolation]:
    violations: List[UXViolation] = []
    for match in DIALOG_PATTERN.finditer(content):
        attrs = match.group(1)
        has_aria_label = bool(re.search(r"""\b(?:aria-label|aria-labelledby)\s*=""", attrs, re.IGNORECASE))
        has_title = bool(re.search(r"""\btitle\s*=""", attrs, re.IGNORECASE))
        if not (has_aria_label or has_title):
            line_no = content[:match.start()].count("\n") + 1
            violations.append(UXViolation(
                rule_id="UX-041",
                severity="ERROR",
                message="Modal dialog lacks accessible name (missing aria-label, aria-labelledby, or title).",
                file_path=file_path,
                line_number=line_no,
                snippet=match.group(0).splitlines()[0].strip()[:100],
            ))
    return violations


def check_state_completeness(content: str, file_path: str) -> List[UXViolation]:
    violations: List[UXViolation] = []
    matches = list(MAP_COLLECTION_PATTERN.finditer(content))
    if not matches:
        return violations

    has_empty = bool(re.search(r"""(?:\.length\s*===?\s*0|!\w+\.length|\bEmpty\b|No\s+(?:items|results|data)|not\s+found)""", content, re.IGNORECASE))
    has_loading = bool(re.search(r"""(?:\bisLoading\b|\bloading\b|\bSkeleton\b|\bSpinner\b|\bpending\b)""", content, re.IGNORECASE))

    if not has_empty or not has_loading:
        first_match = matches[0]
        line_no = content[:first_match.start()].count("\n") + 1
        missing = []
        if not has_empty:
            missing.append("empty state (.length === 0 / 'No items')")
        if not has_loading:
            missing.append("loading skeleton/spinner")

        violations.append(UXViolation(
            rule_id="UX-051",
            severity="WARNING",
            message=f"Dynamic collection mapping missing: {', '.join(missing)}. Brad Frost 6-state completeness requires explicit Empty and Loading branches.",
            file_path=file_path,
            line_number=line_no,
            snippet=content[first_match.start():first_match.start() + 80].strip(),
        ))
    return violations


def audit_content(
    content: str,
    file_path: str,
    ignore_rules: Optional[Set[str]] = None,
    allowed_arbitrary: Optional[Set[str]] = None,
) -> List[UXViolation]:
    ignored = ignore_rules or set()
    allowed_tokens = allowed_arbitrary if allowed_arbitrary is not None else DEFAULT_ALLOWED_ARBITRARY
    violations: List[UXViolation] = []

    if "UX-001" not in ignored and "DIV_BUTTON" not in ignored:
        violations.extend(check_clickable_elements(content, file_path))
    if "UX-002" not in ignored and "SUPPRESSED_FOCUS" not in ignored:
        violations.extend(check_focus_indicators(content, file_path))
    if "UX-003" not in ignored and "UX-031" not in ignored and "ICON_BUTTON_LABEL" not in ignored:
        violations.extend(check_icon_buttons(content, file_path))
    if "UX-014" not in ignored and "MISSING_INPUT_LABEL" not in ignored:
        violations.extend(check_form_labels(content, file_path))
    if "UX-021" not in ignored:
        violations.extend(check_arbitrary_tokens(content, file_path, allowed_tokens))
    if "UX-005" not in ignored and "DEAD_END_ERROR" not in ignored:
        violations.extend(check_dead_end_errors(content, file_path))
    if "UX-041" not in ignored and "MODAL_DIALOG_LABEL" not in ignored:
        violations.extend(check_modal_dialogs(content, file_path))
    if "UX-051" not in ignored and "STATE_COMPLETENESS" not in ignored:
        violations.extend(check_state_completeness(content, file_path))

    return violations


def audit_file(
    file_path: Path,
    ignore_rules: Optional[Set[str]] = None,
    allowed_arbitrary: Optional[Set[str]] = None,
) -> List[UXViolation]:
    if file_path.suffix.lower() not in TARGET_EXTENSIONS:
        return []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return audit_content(content, str(file_path), ignore_rules=ignore_rules, allowed_arbitrary=allowed_arbitrary)
    except Exception as err:
        return [UXViolation(
            rule_id="UX-999",
            severity="ERROR",
            message=f"Failed to read file: {err}",
            file_path=str(file_path),
            line_number=1,
        )]


def audit_path(
    target_path: Path,
    ignore_rules: Optional[Set[str]] = None,
    allowed_arbitrary: Optional[Set[str]] = None,
) -> List[UXViolation]:
    violations: List[UXViolation] = []
    if target_path.is_file():
        return audit_file(target_path, ignore_rules=ignore_rules, allowed_arbitrary=allowed_arbitrary)

    if not target_path.is_dir():
        return []

    for root, dirs, files in os.walk(target_path):
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]
        for fname in sorted(files):
            fpath = Path(root) / fname
            if fpath.suffix.lower() in TARGET_EXTENSIONS:
                violations.extend(audit_file(fpath, ignore_rules=ignore_rules, allowed_arbitrary=allowed_arbitrary))

    return violations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audit_ux.py",
        description="Audit UI codebases for UX anti-patterns, WCAG violations, and state omissions.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to scan (default: current directory).",
    )
    parser.add_argument(
        "--fail-on",
        type=str,
        choices=["critical", "error", "warning", "info"],
        default="error",
        help="Minimum severity level that triggers a non-zero exit code (default: error).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Alias for --fail-on warning.",
    )
    parser.add_argument(
        "--allow-arbitrary",
        type=str,
        default="",
        help="Comma-separated allowed arbitrary tokens (e.g. '17px,100%%,1px').",
    )
    parser.add_argument(
        "--ignore-rules",
        type=str,
        default="",
        help="Comma-separated rule IDs to ignore (e.g. 'UX-021,UX-031').",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output results in JSON format.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Quiet mode: suppress human-readable progress banners.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    fail_level_str = "warning" if args.strict else args.fail_on
    fail_threshold = SEVERITY_LEVELS.get(fail_level_str.upper(), 3)

    ignore_rules = {r.strip().upper() for r in args.ignore_rules.split(",") if r.strip()}

    allowed_arbitrary = set(DEFAULT_ALLOWED_ARBITRARY)
    if args.allow_arbitrary:
        allowed_arbitrary.update(t.strip().lower() for t in args.allow_arbitrary.split(",") if t.strip())

    all_violations: List[UXViolation] = []
    for p_str in args.paths:
        p = Path(p_str)
        all_violations.extend(audit_path(p, ignore_rules=ignore_rules, allowed_arbitrary=allowed_arbitrary))

    counts = {
        "CRITICAL": len([v for v in all_violations if v.severity == "CRITICAL"]),
        "ERROR": len([v for v in all_violations if v.severity == "ERROR"]),
        "WARNING": len([v for v in all_violations if v.severity == "WARNING"]),
        "INFO": len([v for v in all_violations if v.severity == "INFO"]),
    }

    if args.json_output:
        res = {
            "total_violations": len(all_violations),
            "counts": counts,
            "violations": [v.to_dict() for v in all_violations],
        }
        print(json.dumps(res, indent=2))
    else:
        if not args.quiet:
            print("🎨 UX & Accessibility Audit Scanner")
            print("=" * 55)

        if not all_violations:
            if not args.quiet:
                print("✅ 0 UX / Accessibility violations found.")
            return 0

        severity_icons = {
            "CRITICAL": "🛑",
            "ERROR": "❌",
            "WARNING": "⚠️",
            "INFO": "ℹ️",
        }

        for v in all_violations:
            icon = severity_icons.get(v.severity, "•")
            print(f"{icon} {v.rule_id} {v.severity}: {v.file_path}:{v.line_number} — {v.message}")
            if v.snippet:
                print(f"   Snippet: {v.snippet}")

        print("-" * 55)
        print(f"Summary: {counts['CRITICAL']} critical, {counts['ERROR']} error(s), {counts['WARNING']} warning(s), {counts['INFO']} info.")

    max_severity_in_results = max(
        (SEVERITY_LEVELS.get(v.severity, 0) for v in all_violations),
        default=0,
    )

    if max_severity_in_results >= fail_threshold:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
