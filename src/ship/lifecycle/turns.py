"""Turn contract planning, execution boundaries, and provenance formatting."""

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import TurnContract, TurnRecord


def get_next_turn_contract(
    repo_eval: Dict[str, Any],
    execution_mode: Optional[str] = None,
) -> TurnContract:
    """Derive the deterministic Turn Contract for the next required specialist activity."""
    state_key = repo_eval.get("state_key", "INITIAL_PROPOSAL")
    gate = repo_eval.get("gate", "design")
    target_change = (
        repo_eval.get("target_change")
        or (repo_eval.get("active_change") or {}).get("change_id")
        or "default"
    )
    git_info = repo_eval.get("git", {})
    tree_fp = git_info.get("commit", "unknown")
    cfg = repo_eval.get("config", {})
    t_cmd = cfg.get("gates", {}).get("implementation", {}).get("test") or "autodetect"

    # Default execution mode from evaluation config if not explicitly overridden
    exec_mode = execution_mode or cfg.get("workflow", {}).get("execution", "sequential")
    if exec_mode == "auto":
        exec_mode = "sequential"

    active_change = repo_eval.get("active_change") or {}
    blockers = active_change.get("blockers", [])
    pkgs = repo_eval.get("openspec_packages", [])
    matched_pkg = next((p for p in pkgs if p.get("change") == target_change), None)
    next_task = (matched_pkg.get("next_task") if matched_pkg else None) or active_change.get("task_status", {}).get("next")

    if state_key in {"INITIAL_PROPOSAL", "FRONTIER_ROUNDS"}:
        return TurnContract(
            change_id=target_change,
            phase=state_key,
            skill="design",
            role="Senior Principal Systems Architect",
            execution_mode="sequential",
            inputs={
                "change_id": target_change,
                "tree_fingerprint": tree_fp,
                "existing_adrs": [a.get("name") for a in repo_eval.get("adrs", [])],
                "next_action": repo_eval.get("next_action"),
            },
            hard_constraints=[
                "Facts vs. Decisions Law: NEVER ask questions answerable from code or schemas. Inspect autonomously.",
                "Frontier Batching: NEVER drip questions one-by-one. Batch entire frontier into numbered rounds with recommended stances.",
                "Zero Code Edits: NEVER write production code in src/ during design phase.",
                "Detect Ungrillable: If empirical questions arise (latency/throughput), branch to spike.",
            ],
            exit_criteria=[
                "Design tree frontier settled with user.",
                "ADR compiled to docs/adr/ADR-<NNNN>-<change>.md.",
                "OpenSpec package compiled to openspec/changes/<change>/ (proposal.md, specs/, tasks.md).",
                f"Design digest computed via inspect_lifecycle.py --change {target_change} --design-fingerprint.",
                f"Checkpoint recorded via inspect_lifecycle.py --change {target_change} --checkpoint design.",
            ],
            output_evidence="ADR + OpenSpec package + design checkpoint in .scratch/checkpoints/",
            action_prompt=f"Execute design turn for change '{target_change}'. Discover facts, batch frontier rounds, compile ADR/OpenSpec, and checkpoint specification.",
            suggested_command=f"ship checkpoint design --change {target_change}",
            suggested_mcp_tool="ship_checkpoint",
            suggested_mcp_args={"gate": "design", "change": target_change},
        )

    if state_key in {"SPEC_CONFIRMED", "DESIGN_APPROVAL_REQUIRED"}:
        return TurnContract(
            change_id=target_change,
            phase=state_key,
            skill="design",
            role="Principal Systems Architect / Delivery Orchestrator",
            execution_mode="sequential",
            inputs={
                "change_id": target_change,
                "blockers": blockers,
                "specs_dir": f"openspec/changes/{target_change}/",
                "next_action": repo_eval.get("next_action"),
            },
            hard_constraints=[
                "Confirmation Gate: NEVER proceed to implementation without explicit user confirmation of the specification package.",
                "Digest Integrity: Recorded approval digest must strictly match current design files.",
            ],
            exit_criteria=[
                "Explicit confirmation obtained from user ('Proceed' / approval).",
                f"Approval recorded via inspect_lifecycle.py --change {target_change} --approve-design <digest> --approved-by <identity>.",
            ],
            output_evidence=f"Design approval recorded in .ship/state.json for change '{target_change}'",
            action_prompt=f"Present design package for '{target_change}' to user. On confirmation, record approval in ledger using exact design digest.",
            suggested_command=f"ship approve {target_change} <digest> --approved-by <identity>",
            suggested_mcp_tool="ship_approve_design",
            suggested_mcp_args={"change": target_change, "fingerprint": "<digest>", "approved_by": "<identity>"},
        )

    if state_key == "SPIKE_ACTIVE":
        spikes = repo_eval.get("active_spikes", [])
        return TurnContract(
            change_id=target_change,
            phase=state_key,
            skill="spike",
            role="Empirical Prototyper",
            execution_mode="sequential",
            inputs={
                "change_id": target_change,
                "active_spikes": spikes,
                "sandbox_dir": str(spikes[0]) if (spikes and str(spikes[0]).startswith(".scratch")) else (f".scratch/{spikes[0]}" if spikes else ".scratch/spike/"),
            },
            hard_constraints=[
                "Sandbox Isolation: NEVER write prototype code to production paths (src/, lib/). Work strictly in .scratch/.",
                "Falsifiable SLI: Define explicit numerical hypothesis before measuring.",
                "Teardown Mandate: ALL ephemeral containers and processes must be torn down upon completion.",
            ],
            exit_criteria=[
                "Statistical benchmark executed via run_spike.py.",
                "Concrete empirical verdict (latency, throughput, behavior) settled.",
                "Verdict and SLI table synced to active ADR or OpenSpec package.",
            ],
            output_evidence="Empirical benchmark report and verdict bridged to design specification",
            action_prompt=f"Execute spike in .scratch/ to answer empirical blocker for '{target_change}'. Settle design question and bridge verdict.",
            suggested_command="ship spike '<benchmark_command>'",
            suggested_mcp_tool="ship_spike_run",
            suggested_mcp_args={"command": "<benchmark_command>"},
        )

    if state_key == "TDD_ACTIVE":
        return TurnContract(
            change_id=target_change,
            phase=state_key,
            skill="tdd",
            role="Disciplined TDD Craftsperson",
            execution_mode="sequential",
            inputs={
                "change_id": target_change,
                "current_task": next_task or "Next pending task",
                "tasks_file": f"openspec/changes/{target_change}/tasks.md",
                "test_command": t_cmd,
                "blockers": blockers,
            },
            hard_constraints=[
                "Iron Law of Test-First: Writing new production logic without a failing test is FORBIDDEN.",
                "Terminal Receipts: Capture raw terminal output showing assertion failure (Red) and runner zero-exit-code summary (Green).",
                "Dual-Speed Testing: Use real ephemeral DB instances for persistence/wire logic; never mock DB clients/engines.",
                "Minimum Viable Green: Write only the bare minimum code to make the test pass.",
            ],
            exit_criteria=[
                "Red phase: Verified behavioral test failure with AssertionError.",
                "Green phase: Minimal production code written and test suite passes cleanly.",
                "Refactor phase: Code cleaned up under green test protection (YAGNI / simplify).",
                f"Task marked completed (- [x]) in openspec/changes/{target_change}/tasks.md.",
                f"Test run recorded via inspect_lifecycle.py --change {target_change} --record-tests pass.",
            ],
            output_evidence="Passing test suite terminal receipt and updated tasks.md checkbox",
            action_prompt=f"Execute TDD turn on task '{next_task}'. Red (failing test) -> Green (minimal code) -> Refactor -> Record tests.",
            suggested_command="ship tdd --strict",
            suggested_mcp_tool="ship_tdd_verify",
            suggested_mcp_args={"strict": True},
        )

    if state_key == "REVIEW_ACTIVE":
        review_mode = "parallel" if exec_mode == "parallel" else "sequential"
        return TurnContract(
            change_id=target_change,
            phase=state_key,
            skill="review",
            role="Principal Reviewer & Evidence-Based Judge",
            execution_mode=review_mode,
            inputs={
                "change_id": target_change,
                "base_branch": "main",
                "inspect_script": "$SKILLS_DIR/review/scripts/inspect_changes.sh",
                "blockers": blockers,
                "tree_fingerprint": tree_fp,
            },
            hard_constraints=[
                "Facts vs. Decisions Law: Autonomously inspect code and git diff; never ask questions answerable from code.",
                "Judge Adjudication: Reject hallucinations; all findings must be evidenced against actual code.",
                "Schema Compliance: Every reported finding must strictly adhere to the 12-field schema contract.",
                "Repair Ceiling: In review-loop, never exceed 3 repair iterations.",
                "Rollback Guard: If an ADR architectural invariant is broken, trigger rollback to design.",
            ],
            exit_criteria=[
                "10-stage review executed across active perspectives (Correctness, Concurrency, Failure Resilience, Craftsmanship).",
                "Candidate findings adjudicated by Evidence-Based Judge.",
                "Delivery Evidence Envelope or review_report.json generated with PASS/FAIL verdict.",
                f"Review report recorded via inspect_lifecycle.py --change {target_change} --record-review <report_path>.",
            ],
            output_evidence="Judge-approved review_report.json with PASS verdict and verified test evidence",
            action_prompt=f"Execute adversarial code review on working tree diff for '{target_change}'. Run perspectives, adjudicate via Judge, and record report.",
            suggested_command=f"ship review validate .scratch/{target_change}/review_report.json",
            suggested_mcp_tool="ship_review_validate",
            suggested_mcp_args={"report_path": f".scratch/{target_change}/review_report.json"},
        )

    if state_key == "DELIVERY_READY":
        return TurnContract(
            change_id=target_change,
            phase=state_key,
            skill="delivery",
            role="Delivery Orchestrator & Release Engineer",
            execution_mode="sequential",
            inputs={
                "change_id": target_change,
                "status_check": "READY (Exit code 0)",
                "review_verdict": "PASS",
                "living_specs_dir": "openspec/specs/",
                "orchestrator_skill": "ship",
            },
            hard_constraints=[
                "Review Clearance: Delivery requires an explicit PASS report from the review Judge and zero open CRITICAL/HIGH defects.",
                "Living Truth: Delta specs must be cleanly merged into openspec/specs/.",
            ],
            exit_criteria=[
                f"Verify ready status via inspect_lifecycle.py --change {target_change} --status-check.",
                f"Archive change package via inspect_lifecycle.py --archive {target_change}.",
                f"Generate RFC 5133 commit trailers via inspect_lifecycle.py --change {target_change} --generate-trailers.",
                "Present Delivery Walkthrough to user.",
            ],
            output_evidence=f"OpenSpec package archived to openspec/archive/ and commit trailers generated",
            action_prompt=f"Execute delivery sign-off for '{target_change}' via ship orchestrator. Archive OpenSpec package, generate commit trailers, and compile Delivery Walkthrough.",
            suggested_command=f"ship archive {target_change}",
            suggested_mcp_tool="ship_archive",
            suggested_mcp_args={"change": target_change},
        )

    # Fallback / ARCHIVED
    return TurnContract(
        change_id=target_change,
        phase=state_key,
        skill="ship",
        role="Principal Tech Lead & Delivery Orchestrator",
        execution_mode="sequential",
        inputs={"change_id": target_change, "phase": state_key},
        hard_constraints=["Inspect lifecycle state before initiating new proposals."],
        exit_criteria=["Lifecycle clean and ready for next proposal."],
        output_evidence="Lifecycle ready state",
        action_prompt="Lifecycle is clean. Ready to receive new proposal via /ship <idea>.",
        suggested_command="ship status",
        suggested_mcp_tool="ship_status",
        suggested_mcp_args={"change": target_change},
    )


def format_turn_contract(contract: TurnContract) -> str:
    """Format a TurnContract into a clear, agent-readable GitHub markdown block."""
    lines = [
        "═════════════════════════════════════════════════════════════════════",
        f" 🎯 TURN CONTRACT: {contract.skill.upper()} ({contract.role})",
        "═════════════════════════════════════════════════════════════════════",
        f"• Target Change  : {contract.change_id}",
        f"• Lifecycle Phase: {contract.phase}",
        f"• Execution Mode : {contract.execution_mode}",
        "",
        "📋 DECLARED INPUTS:",
    ]
    for k, v in contract.inputs.items():
        if isinstance(v, list):
            v_str = ", ".join(str(x) for x in v) if v else "none"
        else:
            v_str = str(v)
        lines.append(f"  • {k:<15}: {v_str}")

    lines.append("")
    lines.append("🔒 HARD CONSTRAINTS:")
    for hc in contract.hard_constraints:
        lines.append(f"  • {hc}")

    lines.append("")
    lines.append("✅ EXIT VERIFICATION CHECKLIST:")
    for ec in contract.exit_criteria:
        lines.append(f"  [ ] {ec}")

    lines.append("")
    lines.append("📦 OUTPUT EVIDENCE:")
    lines.append(f"  {contract.output_evidence}")

    lines.append("")
    lines.append("👉 ACTION INSTRUCTION:")
    lines.append(f"   {contract.action_prompt}")

    if contract.suggested_command or contract.suggested_mcp_tool:
        lines.append("")
        lines.append("⚡ SUGGESTED INVOCATION:")
        if contract.suggested_command:
            lines.append(f"  • CLI     : {contract.suggested_command}")
        if contract.suggested_mcp_tool:
            args_str = json.dumps(contract.suggested_mcp_args or {})
            lines.append(f"  • MCP Tool: {contract.suggested_mcp_tool}({args_str})")
    lines.append("═════════════════════════════════════════════════════════════════════")
    return "\n".join(lines)


def format_turns_log(turns: List[Dict[str, Any]], change_id: Optional[str] = None) -> str:
    """Format turn-level provenance audit trail."""
    cid_str = f" FOR '{change_id}'" if change_id else ""
    lines = [
        "═════════════════════════════════════════════════════════════════════",
        f" 📜 TURN PROVENANCE AUDIT TRAIL{cid_str}",
        "═════════════════════════════════════════════════════════════════════",
    ]
    if not turns:
        lines.append("• No turns recorded yet in lifecycle ledger.")
    else:
        for idx, t in enumerate(turns, 1):
            tid = t.get("turn_id", f"turn-{idx:03d}")
            skill = t.get("skill", "unknown")
            harness = t.get("harness", "generic")
            mode = t.get("execution_mode", "sequential")
            ts = t.get("timestamp", "unknown")
            lines.append(f"[{tid}] {ts} | Skill: {skill.upper()} | Harness: {harness} ({mode})")
            inputs = t.get("inputs", {})
            if inputs:
                in_summary = ", ".join(f"{k}={v}" for k, v in list(inputs.items())[:3])
                lines.append(f"  └─ Inputs   : {in_summary}")
            evidence = t.get("evidence", {})
            if evidence:
                ev_summary = ", ".join(f"{k}={v}" for k, v in list(evidence.items())[:3])
                lines.append(f"  └─ Evidence : {ev_summary}")
            delta = t.get("state_delta", {})
            if delta:
                delta_summary = ", ".join(f"{k}={v}" for k, v in list(delta.items())[:3])
                lines.append(f"  └─ Delta    : {delta_summary}")
            lines.append("─────────────────────────────────────────────────────────────────────")
    lines.append("═════════════════════════════════════════════════════════════════════")
    return "\n".join(lines)


def resolve_skill_name(skill: str) -> str:
    """Map lifecycle gate activity to installed skill directory name."""
    if skill == "delivery":
        return "ship"
    return skill

