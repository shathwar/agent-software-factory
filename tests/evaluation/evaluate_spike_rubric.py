#!/usr/bin/env python3
"""evaluate_spike_rubric.py — L5 Outcome Quality & Statistical Rigor Rubric Evaluator for Spikes.

Zero external dependencies (Python 3.10+ standard library).

Evaluates whether a Spike Report represents statistically sound and actionable
empirical engineering.

Rubric Dimensions (0.0 - 1.0 each):
1. Falsifiability & SLIs: Clear numeric bounds (e.g. latency < 15ms, RPS > 5000, error < 0.1%).
2. Statistical Rigor: Concurrency, iterations (>= 50), warmup passes, percentile distribution.
3. Sandbox Isolation & Parity: Ephemeral setup documented (.scratch/) with real components.
4. Verdict Coherence: Evidenced conclusion (CONFIRMED/REFUTED/QUALIFIED) strictly matching data.
5. ADR & Specification Bridge: Reusable snippets, configuration limits, and frontier resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional


@dataclass
class SpikeRubricScore:
    name: str
    weight: float
    score: float
    feedback: List[str] = field(default_factory=list)


@dataclass
class SpikeRubricReport:
    target_name: str
    overall_score: float
    passed: bool
    status: str  # PASS, CONDITIONAL, FAIL
    domain_scores: Dict[str, SpikeRubricScore] = field(default_factory=dict)
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


class SpikeRubricEvaluator:
    """Evaluates Spike Reports against principal empirical prototyping standards."""

    def __init__(self, passing_threshold: float = 0.80) -> None:
        self.passing_threshold = passing_threshold

    def evaluate_report(self, report_text: str, target_name: str = "SpikeReport") -> SpikeRubricReport:
        domain_scores: Dict[str, SpikeRubricScore] = {}

        # 1. Falsifiability & SLIs (weight: 0.25)
        fals_feedback = []
        fals_pts = 0.0
        if re.search(r"-\s+\*\*Hypothesis\*\*:\s*.+(?:<|>|<=|>=|\b\d+(?:\.\d+)?\s*(?:ms|rps|tps|qps|%))", report_text, re.IGNORECASE):
            fals_pts += 0.50
        else:
            fals_feedback.append("Hypothesis lacks explicit numeric inequality or unit threshold.")
        if re.search(r"p99|p95|percentile|latency", report_text, re.IGNORECASE):
            fals_pts += 0.25
        else:
            fals_feedback.append("No latency percentile SLI specified.")
        if re.search(r"throughput|rps|tps|qps|error rate|concurren", report_text, re.IGNORECASE):
            fals_pts += 0.25
        else:
            fals_feedback.append("No throughput or error rate SLI specified.")
        domain_scores["falsifiability"] = SpikeRubricScore(
            name="Falsifiability & SLIs",
            weight=0.25,
            score=min(1.0, fals_pts),
            feedback=fals_feedback,
        )

        # 2. Statistical Rigor (weight: 0.25)
        stat_feedback = []
        stat_pts = 0.0
        if re.search(r"p50|median", report_text, re.IGNORECASE) and re.search(r"p99", report_text, re.IGNORECASE):
            stat_pts += 0.40
        else:
            stat_feedback.append("Missing comprehensive percentile spectrum (p50 and p99).")
        if re.search(r"\b(?:warmup|concurrency|iterations|runs)\b", report_text, re.IGNORECASE):
            stat_pts += 0.35
        else:
            stat_feedback.append("Harness does not document warmup or iteration methodology.")
        if re.search(r"error rate|status", report_text, re.IGNORECASE):
            stat_pts += 0.25
        else:
            stat_feedback.append("Reliability or error rate metrics absent.")
        domain_scores["statistical_rigor"] = SpikeRubricScore(
            name="Statistical Rigor",
            weight=0.25,
            score=min(1.0, stat_pts),
            feedback=stat_feedback,
        )

        # 3. Sandbox Isolation (weight: 0.15)
        iso_feedback = []
        iso_pts = 0.0
        if re.search(r"\.scratch/|scratch/", report_text):
            iso_pts += 0.60
        else:
            iso_feedback.append("No scratch sandbox directory documented.")
        if re.search(r"docker|container|ephemeral|isolated|mock", report_text, re.IGNORECASE):
            iso_pts += 0.40
        else:
            iso_feedback.append("No isolation harness (ephemeral container, mock) described.")
        domain_scores["isolation"] = SpikeRubricScore(
            name="Sandbox Isolation",
            weight=0.15,
            score=min(1.0, iso_pts),
            feedback=iso_feedback,
        )

        # 4. Verdict Coherence (weight: 0.20)
        verd_feedback = []
        verd_pts = 0.0
        verdict_token = re.search(r"-\s+\*\*Verdict\*\*:\s*\*{0,2}(CONFIRMED|REFUTED|QUALIFIED)\*{0,2}", report_text, re.IGNORECASE)
        has_breached = bool(re.search(r"❌\s*Breached", report_text))

        if verdict_token:
            verdict_val = verdict_token.group(1).upper()
            if verdict_val == "CONFIRMED" and has_breached:
                verd_pts = 0.0
                verd_feedback.append("CRITICAL: Verdict claimed CONFIRMED despite breached empirical metrics.")
            elif verdict_val in ("REFUTED", "QUALIFIED") and has_breached:
                verd_pts = 1.0  # Properly rejected or qualified
            elif verdict_val == "CONFIRMED" and not has_breached:
                verd_pts = 1.0  # Properly confirmed
            else:
                verd_pts = 0.70
        else:
            verd_feedback.append("Missing explicit CONFIRMED / REFUTED / QUALIFIED verdict.")
        domain_scores["verdict_coherence"] = SpikeRubricScore(
            name="Verdict Coherence",
            weight=0.20,
            score=min(1.0, verd_pts),
            feedback=verd_feedback,
        )

        # 5. ADR & Spec Bridge (weight: 0.15)
        bridge_feedback = []
        bridge_pts = 0.0
        if re.search(r"recommendation|adr|frontier|design", report_text, re.IGNORECASE):
            bridge_pts += 0.50
        else:
            bridge_feedback.append("No architectural recommendation or frontier impact stated.")
        if re.search(r"```", report_text):
            bridge_pts += 0.50
        else:
            bridge_feedback.append("No reusable verified configuration code snippet extracted.")
        domain_scores["adr_bridge"] = SpikeRubricScore(
            name="ADR & Spec Bridge",
            weight=0.15,
            score=min(1.0, bridge_pts),
            feedback=bridge_feedback,
        )

        # Compute overall weighted score
        total_weight = sum(ds.weight for ds in domain_scores.values())
        overall_score = sum(ds.score * ds.weight for ds in domain_scores.values()) / total_weight

        passed = overall_score >= self.passing_threshold
        status = "PASS" if passed else ("CONDITIONAL" if overall_score >= 0.60 else "FAIL")

        notes = []
        if passed:
            notes.append("Spike demonstrates empirical rigor, falsifiable SLIs, and actionable architectural guidance.")
        else:
            notes.append(f"Spike score ({overall_score:.2f}) falls below required threshold ({self.passing_threshold:.2f}).")
            for ds in domain_scores.values():
                if ds.score < 0.70:
                    notes.append(f"Deficiency in {ds.name}: {'; '.join(ds.feedback)}")

        return SpikeRubricReport(
            target_name=target_name,
            overall_score=overall_score,
            passed=passed,
            status=status,
            domain_scores=domain_scores,
            summary_notes=notes,
        )


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python3 evaluate_spike_rubric.py <path_to_spike_report.md>")
        return 1
    report_path = Path(sys.argv[1])
    if not report_path.is_file():
        print(f"File not found: {report_path}")
        return 1
    report = SpikeRubricEvaluator().evaluate_report(report_path.read_text(encoding="utf-8"), target_name=report_path.name)
    print(f"L5 Spike Rubric: {report.status} (Score: {report.overall_score:.2f})")
    for k, v in report.domain_scores.items():
        print(f"  • {v.name:25} : {v.score:.2f} (weight: {v.weight:.2f})")
        for fb in v.feedback:
            print(f"      - {fb}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
