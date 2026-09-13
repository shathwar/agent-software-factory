"""RFC 5133 Commit trailer generation based on lifecycle gate state."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .evidence import validate_review_approval, validate_review_snapshot


def canonicalize_gate_name(gate_name: str) -> str:
    """Canonicalize gate name to lowercase dashed identifier."""
    return gate_name.lower().strip().replace(" ", "-")


class CommitTrailerGenerator:
    """Generates RFC 5133 Git commit trailers matching ship.json gates and ledger state."""

    @classmethod
    def generate(
        cls,
        repo_root: Path,
        change_id: Optional[str] = None,
        ledger: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        load_ledger_fn: Optional[Callable[..., Dict[str, Any]]] = None,
        load_config_fn: Optional[Callable[..., Dict[str, Any]]] = None,
        get_active_change_fn: Optional[Callable[[Path], Optional[str]]] = None,
        create_empty_change_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
        get_git_info_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
    ) -> List[str]:
        if ledger is None and load_ledger_fn:
            ledger = load_ledger_fn(repo_root, auto_sync=False)
        ledger = ledger or {}

        if config is None and load_config_fn:
            config = load_config_fn(repo_root)
        config = config or {}

        cid = change_id or ledger.get("active_change_id") or (get_active_change_fn(repo_root) if get_active_change_fn else None) or "default"
        
        if create_empty_change_fn:
            default_entry = create_empty_change_fn(cid)
        else:
            default_entry = {"change_id": cid, "evidence": {}}
        change_entry = ledger.get("changes", {}).get(cid, default_entry)
        evidence = change_entry.get("evidence", {})

        trailers: List[str] = []
        trailers.append(f"Ship-Change: {cid}")

        gates_cfg = config.get("gates", {})

        # 1. Gate: Design
        design_ev = evidence.get("design", {})
        if design_ev.get("adr"):
            adr_name = Path(design_ev["adr"]).stem
            status = design_ev.get("status", "ACCEPTED")
            trailers.append(f"Ship-Design: {adr_name} ({status})")
        elif "design" in gates_cfg:
            cur_phase = change_entry.get("phase", "design")
            if cur_phase in {"implementation", "review", "delivery"}:
                trailers.append("Ship-Design: PASSED")
            elif cur_phase == "spike":
                trailers.append("Ship-Design: SPIKE")
            else:
                trailers.append("Ship-Design: IN_PROGRESS")

        # 2. Gate: Spike
        spike_ev = evidence.get("spike", {})
        if spike_ev.get("status") and spike_ev.get("status") != "NONE":
            verdict = spike_ev.get("verdict")
            v_str = f" ({verdict})" if verdict else ""
            trailers.append(f"Ship-Spike: {spike_ev['status']}{v_str}")

        # 3. Gate: Implementation
        impl_ev = evidence.get("implementation", {})
        tasks = change_entry.get("task_status", {})
        blockers = change_entry.get("blockers", [])
        has_test_failures = (
            impl_ev.get("tests_passed") is False
            or impl_ev.get("status") == "FAILED"
            or any(b.startswith("Tests:") for b in blockers)
        )

        if tasks.get("total", 0) > 0:
            if has_test_failures:
                trailers.append(f"Ship-Implementation: FAILED ({tasks['completed']}/{tasks['total']} tasks)")
            elif tasks.get("pending", 0) == 0:
                trailers.append(f"Ship-Implementation: PASSED ({tasks['completed']}/{tasks['total']} tasks)")
            else:
                trailers.append(f"Ship-Implementation: IN_PROGRESS ({tasks['completed']}/{tasks['total']} tasks)")
        elif has_test_failures:
            trailers.append("Ship-Implementation: FAILED")
        elif impl_ev.get("status") and impl_ev.get("status") != "PENDING":
            trailers.append(f"Ship-Implementation: {impl_ev['status']}")

        # 4. Gate: Simplify
        simp_ev = evidence.get("simplify", {})
        debt_cnt = simp_ev.get("debt_count", 0)
        trailers.append(f"Ship-Simplify: DEBT-{debt_cnt}")

        # 5. Gate: Review
        review_ev = evidence.get("review", {})
        verdict = review_ev.get("verdict")
        reviewer = review_ev.get("reviewer") or "judge"

        git_info: Dict[str, Any] = {}
        if get_git_info_fn:
            try:
                git_info = get_git_info_fn(repo_root) or {}
            except Exception:
                git_info = {}
        elif (repo_root / ".git").exists():
            try:
                from .vcs import GitClient
                git_info = GitClient().get_info(repo_root) or {}
            except Exception:
                git_info = {}

        approval_error = validate_review_approval(review_ev, cid, git_info)
        is_review_stale = bool(validate_review_snapshot(review_ev, git_info))

        if verdict:
            if is_review_stale and verdict in {"PASS", "APPROVED"}:
                trailers.append(f"Ship-Review: STALE (modified since review by {reviewer})")
            elif approval_error and verdict in {"PASS", "APPROVED"}:
                trailers.append(f"Ship-Review: BLOCKED (by {reviewer})")
            else:
                trailers.append(f"Ship-Review: {verdict} (by {reviewer})")
        else:
            trailers.append("Ship-Review: PENDING")

        # 6. Gate: Delivery
        deliv_ev = evidence.get("delivery", {})
        deliv_status = deliv_ev.get("status", "PENDING")
        if has_test_failures or blockers or approval_error:
            if deliv_status == "ARCHIVED":
                trailers.append("Ship-Delivery: ARCHIVED")
            elif change_entry.get("phase") == "delivery" or deliv_status == "READY" or approval_error:
                trailers.append("Ship-Delivery: BLOCKED")
        elif change_entry.get("phase") == "delivery" or deliv_status in {"READY", "ARCHIVED"}:
            trailers.append(f"Ship-Delivery: {deliv_status if deliv_status != 'PENDING' else 'READY'}")

        return trailers
