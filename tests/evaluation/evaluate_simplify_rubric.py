#!/usr/bin/env python3
"""evaluate_simplify_rubric.py — L5 Outcome Quality Rubric Evaluator for Code Simplification.

Zero external dependencies (Python 3.10+ standard library).

Evaluates whether simplified code achieves true engineering minimalism:
- Deep module design (narrow interface, substantive implementation)
- Elimination of speculative abstractions and shallow wrappers
- Stdlib and native platform utilization (Laziness Ladder)
- Clean error definition (natural no-ops vs defensive spaghetti)
- High-fidelity technical debt markers with falsifiable ceilings

Rubric Dimensions (0.0 - 1.0 each):
1. Complexity Reduction: Cognitive simplicity, absence of gratuitous indirection.
2. Deep Module Leverage: High implementation-to-interface ratio; zero pass-through classes.
3. Stdlib & Platform First: Native primitives used; zero redundant 3rd-party packages.
4. Error Definition: Boundaries handled as natural no-ops rather than defensive sprawl.
5. Debt Marker Rigor: Falsifiable numeric ceilings and explicit upgrade actions.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional


@dataclass
class SimplifyRubricScore:
    name: str
    weight: float
    score: float
    feedback: List[str] = field(default_factory=list)


@dataclass
class SimplifyRubricReport:
    target_name: str
    overall_score: float
    passed: bool
    status: str  # PASS, CONDITIONAL, FAIL
    domain_scores: Dict[str, SimplifyRubricScore] = field(default_factory=dict)
    summary_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_name": self.target_name,
            "overall_score": round(self.overall_score, 3),
            "passed": self.passed,
            "status": self.status,
            "domain_scores": {
                k: {
                    "name": v.name,
                    "weight": v.weight,
                    "score": round(v.score, 3),
                    "feedback": v.feedback,
                }
                for k, v in self.domain_scores.items()
            },
            "summary_notes": self.summary_notes,
        }


class SimplifyRubricEvaluator:
    """Evaluates source code against principal minimalist engineering and Ousterhout standards."""

    FORBIDDEN_REDUNDANT_DEPS = [
        "uuid", "lodash.clonedeep", "lodash.get", "rimraf", "mkdirp",
        "node-fetch", "pytz", "left-pad", "is-odd"
    ]

    def __init__(self, passing_threshold: float = 0.80) -> None:
        self.passing_threshold = passing_threshold

    def evaluate_code(self, code_text: str, target_name: str = "SourceFile") -> SimplifyRubricReport:
        domain_scores: Dict[str, SimplifyRubricScore] = {}

        # 1. Complexity Reduction (weight: 0.25)
        comp_feedback = []
        comp_pts = 0.0
        # Check for excessive layers / factory patterns
        factory_matches = re.findall(r"class\s+\w*Factory\b", code_text)
        if factory_matches:
            comp_feedback.append(f"Speculative factory classes detected: {', '.join(factory_matches)}.")
            comp_pts += 0.20
        else:
            comp_pts += 0.50

        # Check for excessive indentation or deep nesting
        max_indent = 0
        for line in code_text.splitlines():
            indent = len(line) - len(line.lstrip(" "))
            if line.strip() and indent > max_indent:
                max_indent = indent

        if max_indent > 16:
            comp_feedback.append(f"High nesting depth observed (max indent {max_indent} spaces).")
            comp_pts += 0.20
        else:
            comp_pts += 0.50

        domain_scores["complexity_reduction"] = SimplifyRubricScore(
            name="Complexity Reduction",
            weight=0.25,
            score=min(1.0, comp_pts),
            feedback=comp_feedback,
        )

        # 2. Deep Module Leverage (weight: 0.25)
        deep_feedback = []
        deep_pts = 0.0
        # Check for 1-line forwarding methods
        shallow_forwarders = re.findall(r"def\s+\w+\([^)]*\):\s*(?:return\s+self\._?\w+\.\w+\([^)]*\))", code_text)
        if shallow_forwarders:
            deep_feedback.append(f"Detected shallow forwarding method(s) that delegate without logic: {len(shallow_forwarders)}.")
            deep_pts = 0.30
        else:
            deep_pts = 0.60

        # Check for substantive implementation
        loc = len([line for line in code_text.splitlines() if line.strip() and not line.strip().startswith(("#", "//", "/*"))])
        if loc >= 5 and not shallow_forwarders:
            deep_pts += 0.40
        else:
            deep_pts += 0.20

        domain_scores["deep_module_design"] = SimplifyRubricScore(
            name="Deep Module Leverage",
            weight=0.25,
            score=min(1.0, deep_pts),
            feedback=deep_feedback,
        )

        # 3. Stdlib & Platform First (weight: 0.20)
        stdlib_feedback = []
        stdlib_pts = 0.0
        has_redundant_dep = False
        for dep in self.FORBIDDEN_REDUNDANT_DEPS:
            if re.search(rf"['\"]{re.escape(dep)}['\"]|\bimport\s+{re.escape(dep)}\b", code_text):
                has_redundant_dep = True
                stdlib_feedback.append(f"Redundant 3rd-party dependency '{dep}' imported when native standard library exists.")

        if has_redundant_dep:
            stdlib_pts = 0.20
        else:
            stdlib_pts = 0.70
            # Bonus for modern stdlib adoption
            if re.search(r"crypto\.randomUUID|structuredClone|pathlib|zoneinfo|dataclass", code_text):
                stdlib_pts += 0.30

        domain_scores["stdlib_first"] = SimplifyRubricScore(
            name="Stdlib & Platform First",
            weight=0.20,
            score=min(1.0, stdlib_pts),
            feedback=stdlib_feedback,
        )

        # 4. Error Definition Quality (weight: 0.15)
        err_feedback = []
        err_pts = 0.0
        # Check for defining errors out of existence: safe gets, no-ops on empty
        has_defensive_overkill = len(re.findall(r"if\s+\w+\s*==\s*null|if\s+\w+\s*is\s+None", code_text)) >= 6
        if has_defensive_overkill:
            err_feedback.append("Repeated defensive null checks at multiple callsites; fix at root entrypoint.")
            err_pts += 0.40
        else:
            err_pts += 0.70

        if re.search(r"\.get\(|\?\.|or\s+\[\]|or\s+\{\}|default=", code_text):
            err_pts += 0.30

        domain_scores["error_definition"] = SimplifyRubricScore(
            name="Error Definition Quality",
            weight=0.15,
            score=min(1.0, err_pts),
            feedback=err_feedback,
        )

        # 5. Debt Marker Rigor (weight: 0.15)
        debt_feedback = []
        debt_pts = 0.0
        debt_markers = re.findall(r"simplify:\s*(.+)$", code_text, re.MULTILINE | re.IGNORECASE)
        if not debt_markers:
            # Clean code without shortcuts gets full marks
            debt_pts = 1.0
        else:
            valid_count = 0
            for marker in debt_markers:
                has_ceiling = bool(re.search(r"Ceiling:\s*(?!none|n/a|tbd|todo)[^.|;\n]+", marker, re.IGNORECASE))
                has_upgrade = bool(re.search(r"Upgrade:\s*(?!none|n/a|tbd|todo)[^.|;\n]+", marker, re.IGNORECASE))
                if has_ceiling and has_upgrade:
                    valid_count += 1
                else:
                    debt_feedback.append(f"Incomplete/vague debt marker: '{marker[:60]}...'")

            if valid_count == len(debt_markers):
                debt_pts = 1.0
            else:
                debt_pts = valid_count / len(debt_markers)

        domain_scores["debt_marker_rigor"] = SimplifyRubricScore(
            name="Debt Marker Rigor",
            weight=0.15,
            score=min(1.0, debt_pts),
            feedback=debt_feedback,
        )

        # Overall score computation
        overall = sum(dim.score * dim.weight for dim in domain_scores.values())
        passed = overall >= self.passing_threshold and not has_redundant_dep

        if passed:
            status = "PASS"
        elif overall >= 0.60:
            status = "CONDITIONAL"
        else:
            status = "FAIL"

        notes = []
        if has_redundant_dep:
            notes.append("REJECTED: Redundant external package detected where standard library suffices.")
        if factory_matches:
            notes.append(f"WARNING: Speculative factories detected: {', '.join(factory_matches)}.")
        if not notes:
            notes.append(f"Simplify Rubric Assessment completed with score {round(overall, 3)} ({status}).")

        return SimplifyRubricReport(
            target_name=target_name,
            overall_score=overall,
            passed=passed,
            status=status,
            domain_scores=domain_scores,
            summary_notes=notes,
        )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: evaluate_simplify_rubric.py <file_path> [--threshold <float>] [--json]")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"Error: File {file_path} does not exist.")
        sys.exit(1)

    threshold = 0.80
    output_json = "--json" in sys.argv
    if "--threshold" in sys.argv:
        t_idx = sys.argv.index("--threshold")
        if t_idx + 1 < len(sys.argv):
            threshold = float(sys.argv[t_idx + 1])

    evaluator = SimplifyRubricEvaluator(passing_threshold=threshold)
    report = evaluator.evaluate_code(file_path.read_text(encoding="utf-8"), target_name=file_path.name)

    if output_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"=== Simplify Outcome Quality Rubric: {report.target_name} ===")
        print(f"Status: {report.status} (Score: {report.overall_score:.2f} / Threshold: {threshold:.2f})")
        print("\nDomain Breakdown:")
        for k, v in report.domain_scores.items():
            status_icon = "✓" if v.score >= 0.80 else ("~" if v.score >= 0.50 else "✗")
            print(f"  [{status_icon}] {v.name:30s} {v.score:.2f} (weight: {v.weight:.2f})")
            for fb in v.feedback:
                print(f"      - {fb}")
        print("\nSummary Notes:")
        for note in report.summary_notes:
            print(f"  • {note}")

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
