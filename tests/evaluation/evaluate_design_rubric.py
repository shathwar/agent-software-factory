#!/usr/bin/env python3
"""evaluate_design_rubric.py — L5 Outcome Quality & Architectural Rubric Evaluator.

Zero external dependencies (Python 3.10+ standard library).

Evaluates whether an ADR and OpenSpec change package represent sound systems
engineering across the 5 Systems Inquiry Domains + Capability Closure.

Rubric Dimensions (0.0 - 1.0 each):
1. State & Invariants: Single source of truth, ACID/eventual consistency, invariants.
2. Concurrency & Contention: Race mitigation, lock granularity, idempotency.
3. Failure Domains & Chaos: Explicit timeouts, jittered retry/backoff, fallbacks.
4. Data Evolution & Schema: Zero-downtime migrations, indexing, backward compatibility.
5. Operational Blast Radius: Kill-switch / feature flag, SLI/alert signals, rollback.
6. Capability Closure: Entity lifecycle (CRUD), role permissions, non-goals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class DomainScore:
    name: str
    weight: float
    score: float
    feedback: List[str] = field(default_factory=list)


@dataclass
class RubricEvaluationReport:
    target_name: str
    overall_score: float
    passed: bool
    status: str  # PASS, CONDITIONAL, FAIL
    domain_scores: Dict[str, DomainScore] = field(default_factory=dict)
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


class DesignRubricEvaluator:
    """Evaluates ADR text and OpenSpec files against principal engineering outcome standards."""

    def __init__(self, passing_threshold: float = 0.80) -> None:
        self.passing_threshold = passing_threshold

    def evaluate_text(self, adr_text: str, spec_text: str = "", target_name: str = "Design") -> RubricEvaluationReport:
        combined = f"{adr_text}\n\n{spec_text}".lower()
        domain_scores: Dict[str, DomainScore] = {}

        # 1. State & Invariants
        state_feedback = []
        state_pts = 0.0
        if re.search(r"single source of truth|source of truth", combined):
            state_pts += 0.35
        else:
            state_feedback.append("Missing explicit declaration of single source of truth.")
        if re.search(r"acid|transaction|atomic|eventual consist", combined):
            state_pts += 0.35
        else:
            state_feedback.append("Missing explicit consistency model (ACID vs eventual consistency).")
        if re.search(r"invariant|never break|guarantee", combined):
            state_pts += 0.30
        else:
            state_feedback.append("Missing explicit system invariant statements.")
        domain_scores["state_invariants"] = DomainScore(
            name="State & Invariants",
            weight=0.20,
            score=min(1.0, state_pts),
            feedback=state_feedback,
        )

        # 2. Concurrency & Contention
        conc_feedback = []
        conc_pts = 0.0
        if re.search(r"optimistic|pessimistic|lock|mutex|distributed lock", combined):
            conc_pts += 0.35
        else:
            conc_feedback.append("No locking strategy or concurrency control mechanism specified.")
        if re.search(r"idempotenc|dedup|deduplication|unique key|idempotent", combined):
            conc_pts += 0.35
        else:
            conc_feedback.append("No idempotency key or deduplication mechanism documented.")
        if re.search(r"race|toctou|re-entran|contention", combined):
            conc_pts += 0.30
        else:
            conc_feedback.append("No explicit analysis of race conditions or contention windows.")
        domain_scores["concurrency"] = DomainScore(
            name="Concurrency & Contention",
            weight=0.20,
            score=min(1.0, conc_pts),
            feedback=conc_feedback,
        )

        # 3. Failure Domains & Chaos
        fail_feedback = []
        fail_pts = 0.0
        if re.search(r"\b\d+ms\b|\btimeout\b", combined):
            fail_pts += 0.35
        else:
            fail_feedback.append("Missing explicit numeric connection or read timeouts.")
        if re.search(r"backoff|jitter|retry", combined):
            fail_pts += 0.35
        else:
            fail_feedback.append("Missing exponential backoff with jitter retry strategy.")
        if re.search(r"circuit breaker|fallback|graceful degradation|dead letter", combined):
            fail_pts += 0.30
        else:
            fail_feedback.append("Missing circuit breaker, fallback, or dead-letter containment.")
        domain_scores["failure_domains"] = DomainScore(
            name="Failure Domains & Chaos",
            weight=0.20,
            score=min(1.0, fail_pts),
            feedback=fail_feedback,
        )

        # 4. Data Evolution & Schema
        data_feedback = []
        data_pts = 0.0
        if re.search(r"migration|dual-write|dual-read|zero-downtime", combined):
            data_pts += 0.40
        else:
            data_feedback.append("Missing zero-downtime migration or phased rollout strategy.")
        if re.search(r"index|composite index|foreign key|query plan", combined):
            data_pts += 0.35
        else:
            data_feedback.append("Missing database index or query access pattern analysis.")
        if re.search(r"backward compat|backfill|schema evolv", combined):
            data_pts += 0.25
        else:
            data_feedback.append("Missing backward compatibility or historical backfill plan.")
        domain_scores["data_evolution"] = DomainScore(
            name="Data Evolution & Schema",
            weight=0.15,
            score=min(1.0, data_pts),
            feedback=data_feedback,
        )

        # 5. Operational Blast Radius
        blast_feedback = []
        blast_pts = 0.0
        if re.search(r"feature flag|kill-switch|kill switch|canary", combined):
            blast_pts += 0.40
        else:
            blast_feedback.append("Missing feature flag or immediate operational kill-switch.")
        if re.search(r"sli|slo|metric|alert|error rate|monitoring", combined):
            blast_pts += 0.35
        else:
            blast_feedback.append("Missing SLI metrics or monitoring alerts for silent failures.")
        if re.search(r"rollback|blast radius|containment", combined):
            blast_pts += 0.25
        else:
            blast_feedback.append("Missing rollback plan or blast radius containment.")
        domain_scores["blast_radius"] = DomainScore(
            name="Operational Blast Radius",
            weight=0.15,
            score=min(1.0, blast_pts),
            feedback=blast_feedback,
        )

        # 6. Capability Closure
        closure_feedback = []
        closure_pts = 0.0
        if re.search(r"delete|destroy|archive|tombstone|retention", combined):
            closure_pts += 0.35
        else:
            closure_feedback.append("Capability Closure: Entity deletion, archival, or retention lifecycle unaddressed.")
        if re.search(r"role|rbac|permission|admin|guest|access control", combined):
            closure_pts += 0.35
        else:
            closure_feedback.append("Capability Closure: Role access matrix or permission boundaries unaddressed.")
        if re.search(r"non-goal|out of scope|excluded", combined):
            closure_pts += 0.30
        else:
            closure_feedback.append("Capability Closure: Non-goals and out-of-scope boundaries unaddressed.")
        domain_scores["capability_closure"] = DomainScore(
            name="Capability Closure",
            weight=0.10,
            score=min(1.0, closure_pts),
            feedback=closure_feedback,
        )

        # Compute weighted overall score
        total_weight = sum(ds.weight for ds in domain_scores.values())
        overall_score = sum(ds.score * ds.weight for ds in domain_scores.values()) / total_weight

        passed = overall_score >= self.passing_threshold
        if passed:
            status = "PASS"
        elif overall_score >= 0.60:
            status = "CONDITIONAL"
        else:
            status = "FAIL"

        notes = []
        if passed:
            notes.append("Design demonstrates robust systems engineering and complete capability closure.")
        else:
            notes.append(f"Design score ({overall_score:.2f}) falls below required threshold ({self.passing_threshold:.2f}).")
            for ds in domain_scores.values():
                if ds.score < 0.70:
                    notes.append(f"Deficiency in {ds.name}: {'; '.join(ds.feedback)}")

        return RubricEvaluationReport(
            target_name=target_name,
            overall_score=overall_score,
            passed=passed,
            status=status,
            domain_scores=domain_scores,
            summary_notes=notes,
        )


def evaluate_files(adr_path: Path, spec_dir: Optional[Path] = None) -> RubricEvaluationReport:
    """Evaluate an ADR file and optional OpenSpec change directory."""
    adr_text = adr_path.read_text(encoding="utf-8") if adr_path.is_file() else ""
    spec_text = ""
    if spec_dir and spec_dir.is_dir():
        for f in spec_dir.glob("**/*.md"):
            spec_text += "\n" + f.read_text(encoding="utf-8")
    evaluator = DesignRubricEvaluator()
    return evaluator.evaluate_text(adr_text, spec_text, target_name=adr_path.name if adr_path else "Specification")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python3 evaluate_design_rubric.py <path_to_adr.md> [path_to_spec_dir]")
        return 1
    adr_file = Path(sys.argv[1])
    spec_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    report = evaluate_files(adr_file, spec_dir)
    print(f"L5 Design Quality Rubric: {report.status} (Score: {report.overall_score:.2f})")
    for k, v in report.domain_scores.items():
        print(f"  • {v.name:30} : {v.score:.2f} (weight: {v.weight:.2f})")
        for fb in v.feedback:
            print(f"      - {fb}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
