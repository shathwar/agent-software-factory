#!/usr/bin/env python3
"""validate_design.py / design.py — Deterministic Systems Design & Architecture Validator.

Zero external dependencies (Python 3.10+ standard library).

Validates:
1. Architecture Decision Records (ADRs) against adr_template.md contract.
2. OpenSpec change packages (proposal.md, specs/*.md, design.md, tasks.md).
3. Design interview rounds and frontier anti-cheat constraints.
4. Capability closure matrices and confirmation gate discipline.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# ADR Required Structure
ADR_TITLE_PATTERN = re.compile(r"^#\s+ADR-(\d{1,5}):\s+(.+)$", re.MULTILINE)
ADR_STATUS_PATTERN = re.compile(
    r"-\s+\*\*Status\*\*:\s*\[?(PROPOSED|ACCEPTED|SUPERSEDED|REJECTED)\]?",
    re.IGNORECASE,
)
ADR_DATE_PATTERN = re.compile(
    r"-\s+\*\*Date\*\*:\s*\[?(\d{4}-\d{2}-\d{2})\]?",
    re.IGNORECASE,
)

# OpenSpec RFC 2119 keyword pattern
RFC2119_PATTERN = re.compile(r"\b(SHALL|MUST|REQUIRED|SHALL NOT|MUST NOT)\b")
GHERKIN_WHEN_THEN = re.compile(r"\b(GIVEN|WHEN|THEN)\b", re.IGNORECASE)

# Frontier Round Anti-Cheat
ROUND_HEADER_PATTERN = re.compile(r"^###\s+🏛️\s*Round\s+(\d+)\s*—\s*Design\s+Frontier", re.IGNORECASE | re.MULTILINE)
QUESTION_PATTERN = re.compile(r"❓\s*\*\*Q(\d+)\*\*\s*-\s*\*\*([^*]+)\*\*:", re.IGNORECASE)
RECOMMENDED_STANCE_PATTERN = re.compile(
    r"➡️\s*\*\*Recommended\s+Stance\*\*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

VACUOUS_STANCE_KEYWORDS = [
    "whatever you prefer",
    "choose what you want",
    "up to you",
    "up to the team",
    "no recommendation",
    "developer preference",
    "tbd",
    "any option is fine",
]


@dataclass
class Finding:
    rule_id: str
    severity: str  # ERROR, WARNING, INFO
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None


@dataclass
class ValidationResult:
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "ERROR"]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "WARNING"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [asdict(f) for f in self.findings],
            "metrics": self.metrics,
        }


def validate_adr_content(content: str, filename: str = "ADR.md") -> ValidationResult:
    """Validate an Architecture Decision Record (ADR) content against the canonical template."""
    findings: List[Finding] = []
    lines = content.splitlines()

    # 1. Title
    title_match = ADR_TITLE_PATTERN.search(content)
    if not title_match:
        findings.append(Finding(
            rule_id="DES-ADR-001",
            severity="ERROR",
            message="Missing or invalid ADR title. Expected format: '# ADR-[NNNN]: [Short Title]'",
            file_path=filename,
            line_number=1,
        ))

    # 2. Metadata: Status, Date, Target Components
    status_match = ADR_STATUS_PATTERN.search(content)
    if not status_match:
        findings.append(Finding(
            rule_id="DES-ADR-002",
            severity="ERROR",
            message="Missing or invalid '- **Status**: [PROPOSED / ACCEPTED / SUPERSEDED / REJECTED]'",
            file_path=filename,
        ))

    date_match = ADR_DATE_PATTERN.search(content)
    if not date_match:
        findings.append(Finding(
            rule_id="DES-ADR-003",
            severity="ERROR",
            message="Missing or invalid '- **Date**: [YYYY-MM-DD]'",
            file_path=filename,
        ))

    if "- **Target Components**:" not in content and "**Target Components**" not in content:
        findings.append(Finding(
            rule_id="DES-ADR-004",
            severity="WARNING",
            message="Missing '- **Target Components**: [e.g. ServiceA, DB, Broker]'",
            file_path=filename,
        ))

    # 3. Section 1: Context & Problem Statement
    if not re.search(r"^##\s+1\.\s+Context\s+&\s+Problem\s+Statement", content, re.MULTILINE):
        findings.append(Finding(
            rule_id="DES-ADR-005",
            severity="ERROR",
            message="Missing required section: '## 1. Context & Problem Statement'",
            file_path=filename,
        ))

    # 4. Section 2: Decision Drivers
    drivers_match = re.search(r"^##\s+2\.\s+Decision\s+Drivers", content, re.MULTILINE)
    if not drivers_match:
        findings.append(Finding(
            rule_id="DES-ADR-006",
            severity="ERROR",
            message="Missing required section: '## 2. Decision Drivers'",
            file_path=filename,
        ))
    else:
        # Check that at least 2 drivers are present
        driver_items = re.findall(r"^-\s+(?:Driver\s+\d+:|.+)", content[drivers_match.end():], re.MULTILINE)
        if len(driver_items) < 2:
            findings.append(Finding(
                rule_id="DES-ADR-007",
                severity="WARNING",
                message="Decision Drivers section should define at least 2 concrete technical drivers / constraints",
                file_path=filename,
            ))

    # 5. Section 3: Considered Options
    options_match = re.search(r"^##\s+3\.\s+Considered\s+Options", content, re.MULTILINE)
    if not options_match:
        findings.append(Finding(
            rule_id="DES-ADR-008",
            severity="ERROR",
            message="Missing required section: '## 3. Considered Options'",
            file_path=filename,
        ))
    else:
        # Check for at least 2 options and one marked chosen
        has_option_a = bool(re.search(r"###\s+Option\s+A\b", content, re.IGNORECASE))
        has_option_b = bool(re.search(r"###\s+Option\s+B\b", content, re.IGNORECASE))
        has_chosen_flag = bool(re.search(r"\(Chosen\)|Chosen:|Selected:", content, re.IGNORECASE))

        if not (has_option_a and has_option_b):
            findings.append(Finding(
                rule_id="DES-ADR-009",
                severity="ERROR",
                message="Considered Options must explore at least Option A and Option B alternatives",
                file_path=filename,
            ))
        if not has_chosen_flag:
            findings.append(Finding(
                rule_id="DES-ADR-010",
                severity="WARNING",
                message="Considered Options should explicitly designate which option was chosen, e.g. '### Option B: ... *(Chosen)*'",
                file_path=filename,
            ))

    # 6. Section 4: Decision Outcome & Invariants
    outcome_match = re.search(r"^##\s+4\.\s+Decision\s+Outcome", content, re.MULTILINE)
    if not outcome_match:
        findings.append(Finding(
            rule_id="DES-ADR-011",
            severity="ERROR",
            message="Missing required section: '## 4. Decision Outcome & Architecture Specification'",
            file_path=filename,
        ))
    else:
        # Check 4.2 Invariants & Guarantees
        invariants_match = re.search(r"###\s+4\.2\.?\s+Invariants\s+&\s+Guarantees", content, re.IGNORECASE)
        if not invariants_match:
            findings.append(Finding(
                rule_id="DES-ADR-012",
                severity="ERROR",
                message="Missing subsection: '### 4.2. Invariants & Guarantees'",
                file_path=filename,
            ))
        else:
            invariants_text = content[invariants_match.end():invariants_match.end() + 1500]
            required_invariant_domains = [
                ("State & Consistency", "DES-ADR-013"),
                ("Concurrency", "DES-ADR-014"),
                ("Resilience", "DES-ADR-015"),
                ("Data & Migration", "DES-ADR-016"),
                ("Blast Radius", "DES-ADR-017"),
            ]
            for domain_label, rule_code in required_invariant_domains:
                if domain_label.lower() not in invariants_text.lower():
                    findings.append(Finding(
                        rule_id=rule_code,
                        severity="WARNING",
                        message=f"Invariants & Guarantees should address Systems Inquiry domain: '{domain_label}'",
                        file_path=filename,
                    ))

    # 7. Section 5: Consequences & Trade-offs
    consequences_match = re.search(r"^##\s+5\.\s+Consequences\s+&\s+Trade-offs", content, re.MULTILINE)
    if not consequences_match:
        findings.append(Finding(
            rule_id="DES-ADR-018",
            severity="ERROR",
            message="Missing required section: '## 5. Consequences & Trade-offs'",
            file_path=filename,
        ))
    else:
        if "Positive" not in content[consequences_match.start():consequences_match.start() + 800]:
            findings.append(Finding(
                rule_id="DES-ADR-019",
                severity="WARNING",
                message="Consequences section should explicitly document Positive Consequences",
                file_path=filename,
            ))
        if "Negative" not in content[consequences_match.start():consequences_match.start() + 800] and "Technical Debt" not in content:
            findings.append(Finding(
                rule_id="DES-ADR-020",
                severity="WARNING",
                message="Consequences section should explicitly document Negative Consequences / Accepted Technical Debt",
                file_path=filename,
            ))

    # 8. Section 6: Downstream Verification Criteria
    criteria_match = re.search(r"^##\s+6\.\s+Downstream\s+Verification\s+Criteria", content, re.MULTILINE)
    if not criteria_match:
        findings.append(Finding(
            rule_id="DES-ADR-021",
            severity="ERROR",
            message="Missing required section: '## 6. Downstream Verification Criteria (For review)'",
            file_path=filename,
        ))
    else:
        checklist_items = re.findall(r"^-\s+\[[ x]\]\s+.+", content[criteria_match.end():], re.MULTILINE)
        if not checklist_items:
            findings.append(Finding(
                rule_id="DES-ADR-022",
                severity="ERROR",
                message="Downstream Verification Criteria must include actionable checklist items: '- [ ] Criterion'",
                file_path=filename,
            ))

    errors = [f for f in findings if f.severity == "ERROR"]
    passed = len(errors) == 0

    return ValidationResult(
        passed=passed,
        findings=findings,
        metrics={
            "line_count": len(lines),
            "findings_count": len(findings),
            "errors": len(errors),
            "warnings": len([f for f in findings if f.severity == "WARNING"]),
        },
    )


def validate_openspec_dir(change_dir: Path) -> ValidationResult:
    """Validate an OpenSpec change directory (proposal.md, specs/*.md, design.md, tasks.md)."""
    findings: List[Finding] = []
    change_dir = change_dir.resolve()

    if not change_dir.is_dir():
        return ValidationResult(
            passed=False,
            findings=[Finding(
                rule_id="DES-SPEC-000",
                severity="ERROR",
                message=f"Change directory does not exist: {change_dir}",
                file_path=str(change_dir),
            )],
        )

    # 1. proposal.md
    proposal_path = change_dir / "proposal.md"
    if not proposal_path.is_file():
        findings.append(Finding(
            rule_id="DES-SPEC-001",
            severity="ERROR",
            message="Missing required OpenSpec file: proposal.md",
            file_path=str(change_dir),
        ))
    else:
        content = proposal_path.read_text(encoding="utf-8")
        if "Problem Statement" not in content:
            findings.append(Finding(
                rule_id="DES-SPEC-002",
                severity="ERROR",
                message="proposal.md missing 'Problem Statement'",
                file_path=str(proposal_path),
            ))
        if "Proposed Changes" not in content:
            findings.append(Finding(
                rule_id="DES-SPEC-003",
                severity="ERROR",
                message="proposal.md missing 'Proposed Changes'",
                file_path=str(proposal_path),
            ))
        if "Capabilities" not in content:
            findings.append(Finding(
                rule_id="DES-SPEC-004",
                severity="WARNING",
                message="proposal.md missing 'Capabilities' section (Added/Modified/Removed)",
                file_path=str(proposal_path),
            ))
        if "Non-Goals" not in content and "Out of Scope" not in content:
            findings.append(Finding(
                rule_id="DES-SPEC-005",
                severity="WARNING",
                message="proposal.md should define 'Non-Goals / Out of Scope' to prevent scope creep",
                file_path=str(proposal_path),
            ))

    # 2. specs/ directory
    specs_dir = change_dir / "specs"
    if not specs_dir.is_dir():
        findings.append(Finding(
            rule_id="DES-SPEC-010",
            severity="ERROR",
            message="Missing required specs/ directory in OpenSpec change package",
            file_path=str(change_dir),
        ))
    else:
        spec_files = list(specs_dir.glob("*.md"))
        if not spec_files:
            findings.append(Finding(
                rule_id="DES-SPEC-011",
                severity="ERROR",
                message="specs/ directory must contain at least one specification markdown file",
                file_path=str(specs_dir),
            ))
        else:
            for spec_file in spec_files:
                spec_content = spec_file.read_text(encoding="utf-8")
                # RFC 2119 check
                if not RFC2119_PATTERN.search(spec_content):
                    findings.append(Finding(
                        rule_id="DES-SPEC-012",
                        severity="ERROR",
                        message=f"{spec_file.name}: Requirements must use RFC 2119 keywords (SHALL, MUST)",
                        file_path=str(spec_file),
                    ))
                # Gherkin scenario check
                if not GHERKIN_WHEN_THEN.search(spec_content):
                    findings.append(Finding(
                        rule_id="DES-SPEC-013",
                        severity="WARNING",
                        message=f"{spec_file.name}: Specifications should include Gherkin scenarios (GIVEN/WHEN/THEN)",
                        file_path=str(spec_file),
                    ))
                # Capability Closure / Access Matrix check
                if "Role Access Matrix" not in spec_content and "Capability Closure" not in spec_content:
                    findings.append(Finding(
                        rule_id="DES-SPEC-014",
                        severity="WARNING",
                        message=f"{spec_file.name}: Specification should include Capability Closure (Role Access Matrix or Expectation Sweep)",
                        file_path=str(spec_file),
                    ))

    # 3. design.md
    design_path = change_dir / "design.md"
    if not design_path.is_file():
        findings.append(Finding(
            rule_id="DES-SPEC-020",
            severity="WARNING",
            message="Missing design.md in OpenSpec change directory",
            file_path=str(change_dir),
        ))
    else:
        content = design_path.read_text(encoding="utf-8")
        if "Invariants" not in content and "Guarantees" not in content:
            findings.append(Finding(
                rule_id="DES-SPEC-021",
                severity="WARNING",
                message="design.md should document critical system Invariants & Guarantees",
                file_path=str(design_path),
            ))

    # 4. tasks.md
    tasks_path = change_dir / "tasks.md"
    if not tasks_path.is_file():
        findings.append(Finding(
            rule_id="DES-SPEC-030",
            severity="ERROR",
            message="Missing required tasks.md in OpenSpec change directory",
            file_path=str(change_dir),
        ))
    else:
        tasks_content = tasks_path.read_text(encoding="utf-8")
        task_items = re.findall(r"^-\s+\[[ x]\]\s+.+", tasks_content, re.MULTILINE)
        if not task_items:
            findings.append(Finding(
                rule_id="DES-SPEC-031",
                severity="ERROR",
                message="tasks.md must contain actionable checklist items matching '- [ ] Task'",
                file_path=str(tasks_path),
            ))

    errors = [f for f in findings if f.severity == "ERROR"]
    passed = len(errors) == 0

    return ValidationResult(
        passed=passed,
        findings=findings,
        metrics={
            "change_name": change_dir.name,
            "findings_count": len(findings),
            "errors": len(errors),
            "warnings": len([f for f in findings if f.severity == "WARNING"]),
        },
    )


def validate_interview_round(round_text: str) -> ValidationResult:
    """Validate an interview round block for frontier batching, questions, and non-vacuous recommended stances."""
    findings: List[Finding] = []

    # 1. Header
    header_match = ROUND_HEADER_PATTERN.search(round_text)
    if not header_match:
        findings.append(Finding(
            rule_id="DES-FNT-001",
            severity="ERROR",
            message="Missing Frontier Round header. Expected: '### 🏛️ Round [N] — Design Frontier'",
        ))

    # 2. Questions
    questions = QUESTION_PATTERN.findall(round_text)
    if not questions:
        findings.append(Finding(
            rule_id="DES-FNT-002",
            severity="ERROR",
            message="Frontier Round must include at least one numbered question: '❓ **Q1** - **<Title>**:'",
        ))

    # 3. Recommended Stance per question
    stances = RECOMMENDED_STANCE_PATTERN.findall(round_text)
    if len(stances) < len(questions):
        findings.append(Finding(
            rule_id="DES-FNT-003",
            severity="ERROR",
            message=f"Missing Recommended Stance for questions: found {len(questions)} questions but only {len(stances)} stance(s)",
        ))

    # 4. Anti-Cheat: Reject vacuous stances
    for idx, stance in enumerate(stances, 1):
        stance_clean = stance.strip().lower()
        if len(stance_clean) < 15:
            findings.append(Finding(
                rule_id="DES-FNT-004",
                severity="ERROR",
                message=f"Q{idx} Recommended Stance is too brief/vacuous ('{stance}'). Must provide concrete architectural rationale.",
            ))
        for keyword in VACUOUS_STANCE_KEYWORDS:
            if keyword in stance_clean:
                findings.append(Finding(
                    rule_id="DES-FNT-005",
                    severity="ERROR",
                    message=f"Q{idx} Recommended Stance uses evasive language ('{keyword}'). Must adopt a definitive Principal Architect stance.",
                ))
                break

    errors = [f for f in findings if f.severity == "ERROR"]
    return ValidationResult(
        passed=len(errors) == 0,
        findings=findings,
        metrics={
            "round_number": header_match.group(1) if header_match else None,
            "question_count": len(questions),
            "stance_count": len(stances),
        },
    )


def validate_confirmation_gate(turn_output: str, files_created_or_modified: Sequence[str]) -> ValidationResult:
    """Enforce the Confirmation Gate rule: when presenting confirmation summary, agent MUST NOT mutate repo specs."""
    findings: List[Finding] = []
    is_gate_prompt = bool(re.search(
        r"capture our shared architectural understanding|confirm this design frontier|explicitly confirm this architecture",
        turn_output,
        re.IGNORECASE,
    ))

    if is_gate_prompt:
        mutated_spec_files = [
            f for f in files_created_or_modified
            if "docs/adr" in f or "openspec/" in f
        ]
        if mutated_spec_files:
            findings.append(Finding(
                rule_id="DES-GATE-001",
                severity="ERROR",
                message=f"Confirmation Gate violated! Mutated {len(mutated_spec_files)} spec file(s) before user confirmation: {mutated_spec_files}",
            ))

    errors = [f for f in findings if f.severity == "ERROR"]
    return ValidationResult(
        passed=len(errors) == 0,
        findings=findings,
        metrics={
            "is_confirmation_gate": is_gate_prompt,
            "mutated_files_count": len(files_created_or_modified),
        },
    )


class FrontierDAG:
    """Dependency graph manager for architectural decisions and frontier calculation."""

    def __init__(self) -> None:
        self.decisions: Dict[str, Dict[str, Any]] = {}
        self.resolved: Dict[str, str] = {}

    def add_decision(self, decision_id: str, title: str, dependencies: Optional[List[str]] = None) -> None:
        self.decisions[decision_id] = {
            "id": decision_id,
            "title": title,
            "dependencies": dependencies or [],
        }

    def get_frontier(self) -> List[Dict[str, Any]]:
        """Return all decisions whose prerequisites are completely settled."""
        frontier: List[Dict[str, Any]] = []
        for dec_id, data in self.decisions.items():
            if dec_id in self.resolved:
                continue
            deps_met = all(dep in self.resolved for dep in data["dependencies"])
            if deps_met:
                frontier.append(data)
        return frontier

    def resolve(self, decision_id: str, choice: str) -> None:
        if decision_id not in self.decisions:
            raise KeyError(f"Unknown decision: {decision_id}")
        self.resolved[decision_id] = choice

    def is_complete(self) -> bool:
        return len(self.resolved) == len(self.decisions) and len(self.decisions) > 0


def validate_repository(
    repo_root: Path,
    adr_path: Optional[Path] = None,
    change_name: Optional[str] = None,
) -> ValidationResult:
    """Validate all ADRs and OpenSpec packages in the target repository."""
    repo_root = repo_root.resolve()
    all_findings: List[Finding] = []
    adrs_checked = 0
    specs_checked = 0

    # 1. ADR validation
    if adr_path:
        adrs = [adr_path] if adr_path.is_file() else []
    else:
        adrs_dir = repo_root / "docs" / "adr"
        adrs = list(adrs_dir.glob("ADR-*.md")) if adrs_dir.is_dir() else []

    for adr_file in sorted(adrs):
        adrs_checked += 1
        res = validate_adr_content(adr_file.read_text(encoding="utf-8"), filename=str(adr_file.relative_to(repo_root)))
        all_findings.extend(res.findings)

    # 2. OpenSpec validation
    changes_dir = repo_root / "openspec" / "changes"
    if change_name:
        target_changes = [changes_dir / change_name] if (changes_dir / change_name).is_dir() else []
    elif changes_dir.is_dir():
        target_changes = [d for d in changes_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    else:
        target_changes = []

    for c_dir in sorted(target_changes):
        specs_checked += 1
        res = validate_openspec_dir(c_dir)
        all_findings.extend(res.findings)

    errors = [f for f in all_findings if f.severity == "ERROR"]
    return ValidationResult(
        passed=len(errors) == 0,
        findings=all_findings,
        metrics={
            "adrs_checked": adrs_checked,
            "specs_checked": specs_checked,
            "error_count": len(errors),
            "warning_count": len([f for f in all_findings if f.severity == "WARNING"]),
        },
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic Systems Design & Architecture Validator (validate_design.py)",
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Path to repository root or directory containing docs/adr/ and openspec/ (default: .)",
    )
    parser.add_argument(
        "--adr",
        help="Path to specific ADR markdown file to validate.",
    )
    parser.add_argument(
        "--change",
        help="Name of specific OpenSpec change under openspec/changes/<change> to validate.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run validation checks idempotently without modifying any files.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output validation results as structured JSON.",
    )
    parser.add_argument(
        "--fail-on",
        choices=["error", "warning"],
        default="error",
        help="Fail threshold: 'error' (default) fails only on ERROR; 'warning' fails on WARNING or ERROR.",
    )

    args = parser.parse_args(argv)
    root = Path(args.path).resolve()
    adr_file = Path(args.adr).resolve() if args.adr else None

    result = validate_repository(root, adr_path=adr_file, change_name=args.change)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"Systems Design Validation: {'PASSED' if result.passed else 'FAILED'}")
        print(f"ADRs Checked: {result.metrics.get('adrs_checked', 0)}, OpenSpec Changes Checked: {result.metrics.get('specs_checked', 0)}")
        print(f"Errors: {result.metrics.get('error_count', 0)}, Warnings: {result.metrics.get('warning_count', 0)}")
        if result.findings:
            print("\nFindings:")
            for f in result.findings:
                loc = f" [{f.file_path}:{f.line_number}]" if f.file_path else ""
                print(f"  • [{f.severity}] {f.rule_id}{loc}: {f.message}")

    if args.fail_on == "warning":
        return 0 if (result.passed and len(result.warnings) == 0) else 1
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
