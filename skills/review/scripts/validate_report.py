#!/usr/bin/env python3
"""Validate the report contract, not the truth or completeness of its findings."""

import argparse
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Optional, Sequence

TOP_REQUIRED = {"reviewer", "status", "findings", "coverage", "questions", "routing_notes"}
REVIEWERS = {"correctness", "concurrency", "design", "judge"}
STATUSES = {"complete", "incomplete", "skipped"}
FINDING_REQUIRED = {
    "id", "severity", "category", "file", "line", "title",
    "problem", "evidence", "impact", "recommendation", "confidence", "fixability"
}
SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
CATEGORIES = {
    "SpecAlignment", "Correctness", "Concurrency", "Failure/Resilience",
    "Simplicity", "Maintainability", "Reuse", "Performance", "SOLID",
    "Patterns", "ProductionRisk"
}
FIXABILITIES = {"autonomous", "requires-human"}
ID_REGEX = re.compile(r"^FINDING-[0-9]{3,}$")
LINE_REGEX = re.compile(r"^L[1-9][0-9]*(-L[1-9][0-9]*)?$")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def parse_report(text):
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n(.*)\n```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)


def validate_report(report):
    if not isinstance(report, dict):
        return ["Report must be a JSON object"]

    errors = []
    missing_top = TOP_REQUIRED - report.keys()
    if missing_top:
        for k in sorted(missing_top):
            errors.append(f"$.{k}: field is required")
    extra_top = report.keys() - TOP_REQUIRED
    if extra_top:
        for k in sorted(extra_top):
            errors.append(f"$.{k}: unexpected property")

    if errors:
        return errors

    if not isinstance(report["reviewer"], str) or report["reviewer"] not in REVIEWERS:
        errors.append(f"$.reviewer: must be one of {sorted(REVIEWERS)}")
    if not isinstance(report["status"], str) or report["status"] not in STATUSES:
        errors.append(f"$.status: must be one of {sorted(STATUSES)}")

    for list_field in ("coverage", "questions", "routing_notes"):
        val = report[list_field]
        if not isinstance(val, list):
            errors.append(f"$.{list_field}: must be an array")
        elif any(not isinstance(item, str) for item in val):
            errors.append(f"$.{list_field}: all items must be strings")

    findings = report["findings"]
    if not isinstance(findings, list):
        errors.append("$.findings: must be an array")
        return errors

    seen_ids = set()
    for idx, finding in enumerate(findings):
        prefix = f"$.findings[{idx}]"
        if not isinstance(finding, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        missing_finding = FINDING_REQUIRED - finding.keys()
        if missing_finding:
            for k in sorted(missing_finding):
                errors.append(f"{prefix}.{k}: field is required")
        extra_finding = finding.keys() - FINDING_REQUIRED
        if extra_finding:
            for k in sorted(extra_finding):
                errors.append(f"{prefix}.{k}: unexpected property")

        if missing_finding:
            continue

        fid = finding["id"]
        if not isinstance(fid, str) or not ID_REGEX.match(fid):
            errors.append(f"{prefix}.id: must match pattern ^FINDING-[0-9]{{3,}}$")
        else:
            if fid in seen_ids:
                errors.append(f"Duplicate finding ID: {fid}")
            seen_ids.add(fid)

        if not isinstance(finding["severity"], str) or finding["severity"] not in SEVERITIES:
            errors.append(f"{prefix}.severity: must be one of {sorted(SEVERITIES)}")
        if not isinstance(finding["category"], str) or finding["category"] not in CATEGORIES:
            errors.append(f"{prefix}.category: must be one of {sorted(CATEGORIES)}")
        if not isinstance(finding["fixability"], str) or finding["fixability"] not in FIXABILITIES:
            errors.append(f"{prefix}.fixability: must be one of {sorted(FIXABILITIES)}")

        for str_field in ("title", "problem", "evidence", "impact", "recommendation"):
            val = finding[str_field]
            if not isinstance(val, str) or len(val.strip()) < 1:
                errors.append(f"{prefix}.{str_field}: must be a non-empty string")

        conf = finding["confidence"]
        if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(conf) or conf < 0.0 or conf > 1.0:
            errors.append(f"{prefix}.confidence: must be a finite number between 0.0 and 1.0")

        path = finding["file"]
        if not isinstance(path, str) or len(path.strip()) < 1:
            errors.append(f"{prefix}.file: must be a non-empty string")
        elif (PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts
                or "\\" in path or re.match(r"^[A-Za-z]:", path) or path == "."):
            errors.append(f"{fid}: file must be a repository-relative path")

        line = finding["line"]
        if not isinstance(line, str) or not LINE_REGEX.match(line):
            errors.append(f"{prefix}.line: must match pattern ^L[1-9][0-9]*(-L[1-9][0-9]*)?$")
        else:
            start, _, end = line.partition("-L")
            if end and int(end) < int(start[1:]):
                errors.append(f"{fid}: line range ends before it starts")

    return errors


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="JSON report file, or - for stdin")
    args = parser.parse_args(argv)
    try:
        text = (sys.stdin.read() if args.report == "-"
                else Path(args.report).read_text(encoding="utf-8"))
        errors = validate_report(parse_report(text))
    except (OSError, ValueError) as error:
        errors = [str(error)]
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Report structure is valid; source evidence and review coverage still require adjudication.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
