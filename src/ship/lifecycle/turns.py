"""Turn contract planning, execution boundaries, and provenance formatting."""

import json
from typing import Any, Dict, List, Optional

from .models import TurnContract


def get_next_turn_contract(
    repo_eval: Dict[str, Any],
    execution_mode: Optional[str] = None,
) -> TurnContract:
    """Derive the deterministic Turn Contract for the next required specialist activity."""
    state_key = repo_eval.get("state_key", "INITIAL_PROPOSAL")
    target_change = (
        repo_eval.get("target_change")
        or (repo_eval.get("active_change") or {}).get("change_id")
        or "default"
    )
    git_info = repo_eval.get("git", {})
    tree_fp = git_info.get("working_tree_fingerprint")
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

    design_actions = {
        "INITIAL_PROPOSAL": "Discover facts, settle the design frontier, and compile ADR/OpenSpec.",
        "FRONTIER_ROUNDS": "Continue the unresolved design frontier and compile ADR/OpenSpec.",
        "ADR_PROPOSED": "Review the proposed ADR with the user and resolve outstanding design decisions.",
        "ADR_ACCEPTED": "Preserve the accepted ADR decisions and compile the OpenSpec package and tasks.",
        "SPEC_UNFINISHED": "Complete the existing specification package and its executable task breakdown.",
    }
    if state_key in design_actions:
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
            output_evidence="ADR + OpenSpec package + design checkpoint in .agentflow/checkpoints/",
            action_prompt=f"Execute design turn for change '{target_change}'. {design_actions[state_key]} Obtain approval of the completed package before implementation.",
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
            output_evidence=f"Design approval recorded in .agentflow/state.json for change '{target_change}'",
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
                "sandbox_dir": str(spikes[0]) if spikes else ".agentflow/spikes/",
            },
            hard_constraints=[
                "Sandbox Isolation: NEVER write prototype code to production paths (src/, lib/). Work strictly in .agentflow/spikes/.",
                "Falsifiable SLI: Define explicit numerical hypothesis before measuring.",
                "Teardown Mandate: ALL ephemeral containers and processes must be torn down upon completion.",
            ],
            exit_criteria=[
                "Statistical benchmark executed via run_spike.py.",
                "Concrete empirical verdict (latency, throughput, behavior) settled.",
                "Verdict and SLI table synced to active ADR or OpenSpec package.",
            ],
            output_evidence="Empirical benchmark report and verdict bridged to design specification",
            action_prompt=f"Execute spike in .agentflow/spikes/ to answer empirical blocker for '{target_change}'. Settle design question and bridge verdict.",
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
        review_cfg = cfg.get("gates", {}).get("review", {})
        reviewers = review_cfg.get("reviewers", ["correctness", "concurrency", "design", "judge"])
        max_iterations = review_cfg.get("max_iterations", 3)
        review_mode = "parallel" if exec_mode == "parallel" else "sequential"
        return TurnContract(
            change_id=target_change,
            phase=state_key,
            skill="review",
            role="Principal Reviewer & Evidence-Based Judge",
            execution_mode=review_mode,
            inputs={
                "change_id": target_change,
                "base_branch": review_cfg.get("base_branch", "main"),
                "reviewers": reviewers,
                "max_iterations": max_iterations,
                "critical_paths": review_cfg.get("critical_paths", []),
                "inspect_script": "$SKILLS_DIR/review/scripts/inspect_changes.sh",
                "blockers": blockers,
                "tree_fingerprint": tree_fp,
            },
            hard_constraints=[
                "Facts vs. Decisions Law: Autonomously inspect code and git diff; never ask questions answerable from code.",
                "Judge Adjudication: Reject hallucinations; all findings must be evidenced against actual code.",
                "Schema Compliance: Every reported finding must strictly adhere to the 12-field schema contract.",
                f"Repair Ceiling: In review-loop, never exceed {max_iterations} repair iterations.",
                "Rollback Guard: If an ADR architectural invariant is broken, trigger rollback to design.",
            ],
            exit_criteria=[
                f"Applicable review stages executed using configured perspectives: {', '.join(reviewers)}.",
                "Candidate findings adjudicated by Evidence-Based Judge.",
                "Delivery Evidence Envelope or review_report.json generated with PASS/FAIL verdict.",
                f"Review report recorded via inspect_lifecycle.py --change {target_change} --record-review <report_path>.",
            ],
            output_evidence="Judge-approved review_report.json with PASS verdict and verified test evidence",
            action_prompt=f"Execute adversarial code review on working tree diff for '{target_change}'. Run perspectives, adjudicate via Judge, and record report.",
            suggested_command=f"ship review validate .agentflow/reviews/{target_change}/review_report.json",
            suggested_mcp_tool="ship_review_validate",
            suggested_mcp_args={"report_path": f".agentflow/reviews/{target_change}/review_report.json"},
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
            output_evidence="OpenSpec package archived to openspec/archive/ and commit trailers generated",
            action_prompt=f"Execute delivery sign-off for '{target_change}' via ship orchestrator. Archive OpenSpec package, generate commit trailers, and compile Delivery Walkthrough.",
            suggested_command=f"ship archive {target_change}",
            suggested_mcp_tool="ship_archive",
            suggested_mcp_args={"change": target_change},
        )

    if state_key == "VERIFICATION_FAILED":
        verif_ev = active_change.get("verification", {})
        failed_tiers = [t for t, v in verif_ev.items() if isinstance(v, dict) and v.get("verdict") == "NOT_VERIFIED"]
        verify_option = "--all" if any(t != "execution" for t in failed_tiers) else "--tier execution"
        skill_target = "tdd" if ("execution" in failed_tiers or "mutation" in failed_tiers) else "review"
        return TurnContract(
            change_id=target_change,
            phase=state_key,
            skill=skill_target,
            role="Verification Remediation Craftsperson",
            execution_mode="sequential",
            inputs={
                "change_id": target_change,
                "failed_tiers": failed_tiers,
                "blockers": blockers,
                "verification_details": verif_ev,
            },
            hard_constraints=[
                "Evidence Verification Mandate: Never self-attest success when independent verification failed.",
                "Root Cause Remediation: Fix failing assertions, code logic, or ungrounded claims in source.",
                "Re-run Verification: Execute 'agentflow verify' to obtain an independent VERIFIED verdict.",
            ],
            exit_criteria=[
                "Identified root cause of verification failure resolved.",
                f"Independent verification re-run via 'agentflow verify {target_change} {verify_option}'.",
                "Execution verification reports VERIFIED; resolve any other recorded verification failures.",
            ],
            output_evidence=f"Clean verification records in .agentflow/state.json for '{target_change}'",
            action_prompt=f"Remediate verification failure ({', '.join(failed_tiers) if failed_tiers else 'unverified claims'}) for '{target_change}'. Fix root cause and re-verify via 'agentflow verify {target_change} {verify_option}'.",
            suggested_command=f"agentflow verify {target_change} {verify_option}",
            suggested_mcp_tool="ship_verify",
            suggested_mcp_args={"change": target_change, "tiers": sorted(set(failed_tiers) | {"execution"})},
        )

    if state_key == "AUTONOMY_HALTED":
        next_act = repo_eval.get("next_action", "")
        halt_reason = next_act.replace("Autonomy halted: NON_CONVERGING_REMEDIATION: ", "").strip()
        if not halt_reason and blockers:
            halt_b = [b for b in blockers if b.startswith("Halt:")]
            if halt_b:
                halt_reason = halt_b[0].replace("Halt:", "").strip()
        if not halt_reason:
            halt_reason = "Non-converging remediation detected"
        return TurnContract(
            change_id=target_change,
            phase=state_key,
            skill="human",
            role="Human Systems Lead & Escalation Arbiter",
            execution_mode="sequential",
            inputs={
                "change_id": target_change,
                "halt_reason": halt_reason,
                "blockers": blockers,
                "turn_history_count": len(active_change.get("turns", [])),
            },
            hard_constraints=[
                "AUTONOMY HALTED: Automated remediation has ceased due to non-converging cycles or budget exhaustion.",
                "DO NOT attempt automated self-remediation without human supervisor direction.",
                "Review the turn provenance history via 'agentflow turns' to inspect the failure trajectory.",
                "Once contradictory constraints or code bugs are manually resolved, execute 'agentflow resume' to clear the halt.",
            ],
            exit_criteria=[
                "Human supervisor manually intervenes and diagnoses non-convergence.",
                f"State unlocked via 'agentflow resume {target_change}' or rolled back via 'agentflow rollback <gate>'.",
            ],
            output_evidence="Human supervision clearance recorded in ledger",
            action_prompt=f"Autonomy is halted for '{target_change}': {halt_reason}. A human supervisor must review the failure trajectory and resume via 'agentflow resume {target_change}' or rollback via 'agentflow rollback <gate>'.",
            suggested_command=f"agentflow resume {target_change}",
            suggested_mcp_tool="agentflow_resume",
            suggested_mcp_args={"change": target_change},
        )

    if state_key != "ARCHIVED":
        raise ValueError(f"Unsupported lifecycle state: {state_key!r}; cannot derive a safe next turn")

    # Only an archived change is complete.
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


def validate_turn_record(record: Any) -> None:
    """Validate provenance at ingestion without interpreting claimed evidence as approval."""
    if not isinstance(record, dict):
        raise ValueError("Turn record must be a JSON object")
    for field in ("turn_id", "timestamp", "skill", "harness", "execution_mode", "change_id"):
        if field in record and (not isinstance(record[field], str) or not record[field].strip()):
            raise ValueError(f"Turn record {field} must be a nonempty string")
    for field in ("inputs", "evidence", "state_delta"):
        if field in record and not isinstance(record[field], dict):
            raise ValueError(f"Turn record {field} must be a JSON object")
    if record.get("execution_mode", "sequential") not in ("sequential", "parallel"):
        raise ValueError("Turn execution_mode must be sequential or parallel")


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
            try:
                validate_turn_record(t)
            except ValueError as exc:
                lines.append(f"[record-{idx}] INVALID: {exc}; preserved, export with --format json")
                continue
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
    if skill in ("delivery", "convergence", "human"):
        return "ship"
    if skill == "verification":
        return "review"
    return skill

