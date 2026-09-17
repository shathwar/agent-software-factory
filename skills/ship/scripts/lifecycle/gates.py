"""Phase Gate Evaluators for the Ship Lifecycle Engine."""

from typing import Any, Dict, List, Optional, Tuple

from .evidence import validate_review_approval, implementation_failed
from .models import GateResult, GateStatus


def validate_delivery_readiness(
    review_report: Dict[str, Any],
    active_pkg: Dict[str, Any],
    git_info: Dict[str, Any],
    active_change: Optional[Dict[str, Any]],
) -> Tuple[str, str, str]:
    """Validate that review and ledger requirements are met before advancing to delivery."""
    def review_blocked(reason: str) -> Tuple[str, str, str]:
        return ("review", "REVIEW_ACTIVE", reason)

    pkg_change = active_pkg.get("change", "")
    err = validate_review_approval(review_report, pkg_change, git_info)
    if err:
        return review_blocked(err)

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

    return (
        "delivery",
        "DELIVERY_READY",
        f"All tasks complete, tests verified green, and Judge review PASSED. Ready to deliver Delivery Walkthrough. Run 'python3 skills/ship/scripts/inspect_lifecycle.py --archive' to sync living specs and archive '{pkg_change}'.",
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
        active_pkg = openspec_packages[0]
        pkg_change_name = active_pkg.get("change")
        if not active_pkg["has_tasks"] or active_pkg["total_tasks"] == 0:
            return (
                "design",
                "SPEC_UNFINISHED",
                f"Compile tasks.md and specs/ for '{pkg_change_name}'. Seek user confirmation to proceed.",
            )

        design_blockers = [b for b in (active_change or {}).get("blockers", []) if b.startswith("Design:")]
        if design_blockers:
            return ("design", "DESIGN_APPROVAL_REQUIRED", design_blockers[0])

        if active_pkg["pending_tasks"] > 0:
            next_task_str = f" Next: '{active_pkg['next_task']}'." if active_pkg["next_task"] else ""
            return (
                "implementation",
                "TDD_ACTIVE",
                f"Implement pending tasks ({active_pkg['completed_tasks']}/{active_pkg['total_tasks']} tasks complete).{next_task_str} Run Red-Green-Refactor.",
            )

        if active_pkg["pending_tasks"] == 0 and active_pkg["total_tasks"] > 0:
            if active_change:
                impl_ev = active_change.get("evidence", {}).get("implementation", {})
                blockers = active_change.get("blockers", [])
                test_blockers = [b for b in blockers if b.startswith("Tests:")]
                if implementation_failed(impl_ev) or test_blockers:
                    reason = test_blockers[0] if test_blockers else f"{impl_ev.get('failed_count', 1)} test(s) failing"
                    return (
                        "implementation",
                        "TDD_ACTIVE",
                        f"Blocked by failing tests recorded in ledger ({reason}). Run Red-Green-Refactor to fix failing tests before advancing.",
                    )

            if not review_report:
                return (
                    "review",
                    "REVIEW_ACTIVE",
                    "All implementation tasks marked complete. Run 'review' in review-loop mode against base branch.",
                )

            return validate_delivery_readiness(review_report, active_pkg, git_info, active_change)

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
