"""RFC 5133 Commit trailer generation based on lifecycle gate state."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .evidence import validate_review_approval, validate_review_snapshot, validate_design_approval, implementation_failed, inspect_spikes, inspect_review_reports
from .gates import validate_delivery_readiness


def canonicalize_gate_name(gate_name: str) -> str:
    """Canonicalize gate name to lowercase dashed identifier."""
    return gate_name.lower().strip().replace(" ", "-")


class CommitTrailerGenerator:
    """Generates RFC 5133 Git commit trailers matching ship.json gates and ledger state."""

    def generate_trailers(self, repo_root: Path, target_change: Optional[str] = None) -> List[str]:
        """Instance method alias for generating trailers for an active or targeted change."""
        return self.generate(repo_root, change_id=target_change)

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
        if ledger is None:
            if load_ledger_fn:
                ledger = load_ledger_fn(repo_root, auto_sync=False)
            else:
                from .ledger import FileLedgerStore
                ledger = FileLedgerStore.load(repo_root, auto_sync=False)
        ledger = ledger or {}

        if config is None:
            if load_config_fn:
                config = load_config_fn(repo_root)
            else:
                from .config import ShipConfigManager
                config = ShipConfigManager.load(repo_root)
        config = config or {}

        cid = change_id or ledger.get("active_change_id") or (get_active_change_fn(repo_root) if get_active_change_fn else None)
        if not cid:
            from .ledger import FileLedgerStore
            cid = FileLedgerStore.get_active_change(repo_root)
        if not cid:
            raise ValueError("No active change; specify --change when generating trailers after archive")

        if create_empty_change_fn:
            default_entry = create_empty_change_fn(cid)
        else:
            from .ledger import create_empty_change_entry
            default_entry = create_empty_change_entry(cid)
        change_entry = ledger.get("changes", {}).get(cid, default_entry)
        evidence = change_entry.get("evidence", {})
        delivery = evidence.get("delivery", {})
        if delivery.get("status") == "ARCHIVED":
            saved = delivery.get("trailers")
            if not isinstance(saved, list) or not all(isinstance(t, str) for t in saved) or f"Ship-Change: {cid}" not in saved or "Ship-Delivery: ARCHIVED" not in saved:
                raise ValueError(f"Archived change '{cid}' has no valid saved trailer receipt")
            return list(saved)

        trailers: List[str] = []
        trailers.append(f"Ship-Change: {cid}")

        gates_cfg = config.get("gates", {})

        # 1. Gate: Design
        design_error = validate_design_approval(repo_root, cid, change_entry)
        if "design" in gates_cfg or not gates_cfg or gates_cfg.get("design") is not False:
            trailers.append("Ship-Design: " + ("BLOCKED" if design_error else "PASSED"))

        # 2. Gate: Spike
        spike_ev = evidence.get("spike", {})
        if spike_ev.get("status") and spike_ev.get("status") != "NONE":
            verdict = spike_ev.get("verdict")
            v_str = f" ({verdict})" if verdict else ""
            trailers.append(f"Ship-Spike: {spike_ev['status']}{v_str}")

        # 3. Gate: Implementation
        impl_ev = evidence.get("implementation", {})
        from .specs import OpenSpecRepository
        from .paths import resolve_change_path
        packages = OpenSpecRepository().inspect_openspec(repo_root, target_change=cid) if resolve_change_path(repo_root, cid).is_dir() else []
        package = packages[0] if packages else {"change": cid, "has_tasks": False, "total_tasks": 0, "pending_tasks": 0}
        tasks = {"total": package["total_tasks"], "completed": package.get("completed_tasks", 0), "pending": package["pending_tasks"]}
        blockers = change_entry.get("blockers", [])
        has_test_failures = implementation_failed(impl_ev) or any(b.startswith("Tests:") for b in blockers)

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
        review_ev = inspect_review_reports(repo_root, change=cid) or evidence.get("review", {})
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

        # 6. Gate: Delivery uses the same decision as inspection and archive.
        decision = validate_delivery_readiness(review_ev, package, git_info, change_entry, design_error=design_error, spikes=inspect_spikes(repo_root))
        trailers.append("Ship-Delivery: " + ("READY" if decision[1] == "DELIVERY_READY" else "BLOCKED"))

        return trailers
