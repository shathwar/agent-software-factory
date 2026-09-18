"""Phase Gate Evaluators for the Ship Lifecycle Engine."""

from typing import Any, Dict, List, Optional, Tuple, Set

from .evidence import validate_review_approval, implementation_failed


def validate_delivery_readiness(
    review_report: Optional[Dict[str, Any]],
    active_pkg: Dict[str, Any],
    git_info: Dict[str, Any],
    active_change: Optional[Dict[str, Any]],
    design_error: Optional[str] = None,
    package_spec_names: Optional[Set[str]] = None,
    spikes: Optional[List[str]] = None,
) -> Tuple[str, str, str]:
    """Validate that review and ledger requirements are met before advancing to delivery."""
    def review_blocked(reason: str) -> Tuple[str, str, str]:
        return ("review", "REVIEW_ACTIVE", reason)

    if spikes:
        return ("spike", "SPIKE_ACTIVE", f"Complete empirical spike in '{spikes[0]}'.")

    pkg_change = active_pkg.get("change", "")
    if not active_pkg.get("has_tasks", True):
        return ("design", "SPEC_UNFINISHED", "tasks.md does not exist. Compile tasks.md and specs/ before implementation.")
    if active_pkg.get("total_tasks", 0) == 0:
        return ("design", "SPEC_UNFINISHED", "tasks.md contains no tasks. Compile tasks.md and specs/ before implementation.")
    design_blockers = [b for b in (active_change or {}).get("blockers", []) if b.startswith("Design:")]
    if design_error or design_blockers:
        return ("design", "DESIGN_APPROVAL_REQUIRED", design_error or design_blockers[0])
    if active_pkg.get("pending_tasks", 0) > 0:
        return ("implementation", "TDD_ACTIVE", f"Implement pending tasks ({active_pkg['completed_tasks']}/{active_pkg['total_tasks']} tasks complete): pending tasks in tasks.md. Next: '{active_pkg.get('next_task')}'. Run Red-Green-Refactor.")

    if active_change:
        blockers = active_change.get("blockers", [])
        if blockers:
            test_b = [b for b in blockers if b.startswith("Tests:")]
            if test_b:
                return ("implementation", "TDD_ACTIVE", f"Blocked by test failure in ledger: {test_b[0]}. Run Red-Green-Refactor.")
            return review_blocked(f"Blocked by active ledger blockers: {'; '.join(blockers)}. Remediate findings before shipping.")
        impl_ev = active_change.get("evidence", {}).get("implementation", {})
        if implementation_failed(impl_ev):
            return ("implementation", "TDD_ACTIVE", "Blocked by failing test evidence in ledger. Run Red-Green-Refactor.")
        review_ev = active_change.get("evidence", {}).get("review", {})
        if review_ev.get("verdict") in {"FAIL", "FAILED", "REJECTED"}:
            return review_blocked(f"Review verdict recorded in ledger is '{review_ev.get('verdict')}'. Remediate findings or re-run review.")
        if review_ev.get("critical_or_high_count", 0) > 0:
            return review_blocked(f"Ledger records {review_ev['critical_or_high_count']} unresolved CRITICAL/HIGH finding(s). Remediate defects before shipping.")

    if not review_report:
        return review_blocked("no passing review report found. Run 'review' in review-loop mode against base branch.")
    err = validate_review_approval(review_report, pkg_change, git_info, package_spec_names=package_spec_names)
    if err:
        return review_blocked(err)

    return (
        "delivery",
        "DELIVERY_READY",
        f"All tasks complete, tests verified green, and Judge review PASSED. Ready to deliver Delivery Walkthrough. Run the installed inspect_lifecycle.py with --archive to sync living specs and archive '{pkg_change}'.",
    )


def determine_lifecycle_state(
    git_info: Dict[str, Any],
    adrs: List[Dict[str, Any]],
    openspec_packages: List[Dict[str, Any]],
    spikes: List[str],
    review_report: Optional[Dict[str, Any]],
    active_change: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, str]:
    """Determine active gate, status label, and recommended action."""
    if spikes:
        spike_name = spikes[0]
        return (
            "spike",
            "SPIKE_ACTIVE",
            f"Complete empirical spike in '{spike_name}'. Deliver verdict to settle design frontier.",
        )

    if active_change and active_change.get("evidence", {}).get("delivery", {}).get("status") == "ARCHIVED":
        cid = active_change.get("change_id", "active")
        arch_path = active_change.get("evidence", {}).get("delivery", {}).get("archived_path")
        path_str = f" in '{arch_path}'" if arch_path else ""
        return (
            "delivery",
            "ARCHIVED",
            f"Change '{cid}' has been delivered and archived{path_str}.",
        )

    if not openspec_packages and not adrs:
        return (
            "design",
            "INITIAL_PROPOSAL",
            "Run '/design' or '/ship <change>'. Explore workspace facts and present Frontier Rounds.",
        )

    if openspec_packages:
        return validate_delivery_readiness(review_report, openspec_packages[0], git_info, active_change)

    has_accepted = any(a.get("status") in {"ACCEPTED", "APPROVED"} for a in adrs)
    if has_accepted:
        return (
            "design",
            "ADR_ACCEPTED",
            "ADR accepted. Compile OpenSpec change package (specs/ and tasks.md) or confirm with user to begin TDD.",
        )
    return (
        "design",
        "ADR_PROPOSED",
        "ADR proposed. Grill design frontier and seek user acceptance before compiling OpenSpec or beginning TDD.",
    )
