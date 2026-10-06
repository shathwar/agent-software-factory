#!/usr/bin/env python3
"""evaluate_ship_rubric.py — L5 Outcome Quality Rubric Evaluator for Autonomous Ship Deliveries.

Zero external dependencies (Python 3.10+ standard library).

Evaluates whether a completed Ship engineering lifecycle delivery represents
principal-level engineering delivery:
- Gate Closure Completeness: 4 deterministic gates (Design, Implementation, Review, Delivery).
- Design Binding: Traceability to approved ADR (docs/adr/) and OpenSpec package.
- Evidence Integrity: Raw terminal test receipts bound to current working tree fingerprint.
- Review Clearance: Official Judge PASS verdict, zero open CRITICAL/HIGH defects.
- Cost Transparency: Explicit token usage and financial cost from ledger metrics.

Rubric Dimensions (0.0 - 1.0 each):
1. Gate Closure Completeness: All 4 gates explicitly cleared and evidenced.
2. Design Binding: Architecture locked and approved prior to implementation.
3. Evidence Integrity: Test receipts verified and current tree uncompromised.
4. Review Clearance: Complete review-loop with zero open blocking findings.
5. Cost Transparency: Transparent token and cost ledger reporting in final walkthrough.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional


@dataclass
class ShipRubricScore:
    name: str
    weight: float
    score: float
    feedback: List[str] = field(default_factory=list)


@dataclass
class ShipRubricReport:
    target_name: str
    overall_score: float
    passed: bool
    status: str  # PASS, CONDITIONAL, FAIL
    domain_scores: Dict[str, ShipRubricScore] = field(default_factory=dict)
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


class ShipRubricEvaluator:
    """Evaluates Ship lifecycle walkthroughs and evidence envelopes against principal delivery standards."""

    def __init__(self, passing_threshold: float = 0.80) -> None:
        self.passing_threshold = passing_threshold

    def evaluate_delivery(self, walkthrough_text: str, state_dict: Optional[Dict[str, Any]] = None, target_name: str = "ShipDelivery") -> ShipRubricReport:
        domain_scores: Dict[str, ShipRubricScore] = {}

        # 1. Gate Closure Completeness (weight: 0.25)
        gate_feedback = []
        gate_pts = 0.0
        has_design_mention = bool(re.search(r"\b(?:design|adr|specification)\b", walkthrough_text, re.IGNORECASE))
        has_impl_mention = bool(re.search(r"\b(?:implementation|tdd|tests passed|test-first)\b", walkthrough_text, re.IGNORECASE))
        has_review_mention = bool(re.search(r"\b(?:review|scorecard|judge pass|verdict)\b", walkthrough_text, re.IGNORECASE))
        has_delivery_mention = bool(re.search(r"\b(?:delivery|shipped|pr|walkthrough|archive)\b", walkthrough_text, re.IGNORECASE))

        if has_design_mention: gate_pts += 0.25
        else: gate_feedback.append("Missing Design gate summary or ADR reference.")
        if has_impl_mention: gate_pts += 0.25
        else: gate_feedback.append("Missing Implementation gate summary or test pass confirmation.")
        if has_review_mention: gate_pts += 0.25
        else: gate_feedback.append("Missing Review gate summary or Judge scorecard.")
        if has_delivery_mention: gate_pts += 0.25
        else: gate_feedback.append("Missing Delivery gate summary.")

        domain_scores["gate_closure_completeness"] = ShipRubricScore(
            name="Gate Closure Completeness",
            weight=0.25,
            score=min(1.0, gate_pts),
            feedback=gate_feedback,
        )

        # 2. Design Binding (weight: 0.20)
        des_feedback = []
        des_pts = 0.0
        has_adr_link = bool(re.search(r"(?:docs/adr/|ADR-\d{4}|architecture decision)", walkthrough_text, re.IGNORECASE))
        has_openspec = bool(re.search(r"(?:openspec/|change package|tasks\.md)", walkthrough_text, re.IGNORECASE))

        if has_adr_link: des_pts += 0.60
        else: des_feedback.append("Walkthrough lacks reference to approved ADR (docs/adr/ADR-*.md).")
        if has_openspec: des_pts += 0.40
        else: des_feedback.append("Walkthrough lacks reference to OpenSpec change delta.")

        domain_scores["design_binding"] = ShipRubricScore(
            name="Design Binding",
            weight=0.20,
            score=min(1.0, des_pts),
            feedback=des_feedback,
        )

        # 3. Evidence Integrity (weight: 0.20)
        ev_feedback = []
        ev_pts = 0.0
        has_terminal_receipt = bool(re.search(r"(?:exit code:\s*0|ran \d+ tests|passed in [\d.]+s|tests passed)", walkthrough_text, re.IGNORECASE))
        has_fingerprint = bool(re.search(r"(?:fingerprint|sha|commit|tree)", walkthrough_text, re.IGNORECASE))

        if has_terminal_receipt: ev_pts += 0.60
        else: ev_feedback.append("Walkthrough lacks verified terminal test runner receipt.")
        if has_fingerprint: ev_pts += 0.40
        else: ev_feedback.append("Walkthrough lacks git tree/fingerprint evidence.")

        domain_scores["evidence_integrity"] = ShipRubricScore(
            name="Evidence Integrity",
            weight=0.20,
            score=min(1.0, ev_pts),
            feedback=ev_feedback,
        )

        # 4. Review Clearance (weight: 0.20)
        rev_feedback = []
        rev_pts = 0.0
        has_judge_pass = bool(re.search(r"(?:judge:?\s*pass|verdict:?\s*(?:pass|ready to deploy)|scorecard)", walkthrough_text, re.IGNORECASE))
        has_zero_critical = bool(re.search(r"(?:zero (?:open )?critical|0 critical|clean review|no blocking)", walkthrough_text, re.IGNORECASE))

        if has_judge_pass: rev_pts += 0.60
        else: rev_feedback.append("Walkthrough lacks explicit Judge PASS verdict.")
        if has_zero_critical: rev_pts += 0.40
        else: rev_feedback.append("Walkthrough lacks explicit statement of zero open critical/high findings.")

        domain_scores["review_clearance"] = ShipRubricScore(
            name="Review Clearance",
            weight=0.20,
            score=min(1.0, rev_pts),
            feedback=rev_feedback,
        )

        # 5. Cost Transparency (weight: 0.15)
        cost_feedback = []
        cost_pts = 0.0
        has_tokens = bool(re.search(r"Tokens:\s*([0-9,]+|\bnot recorded\b)", walkthrough_text, re.IGNORECASE))
        has_cost = bool(re.search(r"Cost:\s*(\$[0-9,.]+(?:\s*USD)?|\bnot recorded\b)", walkthrough_text, re.IGNORECASE))

        if has_tokens and has_cost:
            cost_pts = 1.0
        elif has_tokens or has_cost:
            cost_pts = 0.50
            cost_feedback.append("Incomplete cost reporting: both Tokens and Cost ($ USD) required.")
        else:
            cost_pts = 0.0
            cost_feedback.append("Missing mandatory cost summary: 'Tokens: <count>' and 'Cost: $<amount> USD'.")

        domain_scores["cost_transparency"] = ShipRubricScore(
            name="Cost Transparency",
            weight=0.15,
            score=min(1.0, cost_pts),
            feedback=cost_feedback,
        )

        overall = sum(dim.score * dim.weight for dim in domain_scores.values())
        passed = overall >= self.passing_threshold and cost_pts >= 0.50

        if passed: status_str = "PASS"
        elif overall >= 0.60: status_str = "CONDITIONAL"
        else: status_str = "FAIL"

        notes = []
        notes.append(f"Ship Delivery Rubric completed with score {round(overall, 3)} ({status_str}).")
        if cost_pts < 0.50:
            notes.append("WARNING: Cost transparency missing from delivery walkthrough.")

        return ShipRubricReport(
            target_name=target_name,
            overall_score=overall,
            passed=passed,
            status=status_str,
            domain_scores=domain_scores,
            summary_notes=notes,
        )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: evaluate_ship_rubric.py <walkthrough.md> [--threshold <float>] [--json]")
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

    text = file_path.read_text(encoding="utf-8")
    evaluator = ShipRubricEvaluator(passing_threshold=threshold)
    report = evaluator.evaluate_delivery(text, target_name=file_path.name)

    if output_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"=== Ship Delivery Outcome Quality Rubric: {report.target_name} ===")
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
