"""Lifecycle state machine orchestration engine."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from .checkpoints import CheckpointManager
from .config import ShipConfigManager
from .evidence import (
    inspect_review_reports,
    inspect_spikes,
    is_spike_completed,
    is_test_evidence_passing,
    validate_judge_report_contract,
    validate_review_approval,
    validate_design_approval,
)
from .gates import determine_lifecycle_state, validate_delivery_readiness
from .ledger import FileLedgerStore
from .specs import OpenSpecRepository
from .trailers import CommitTrailerGenerator
from .vcs import GitClient


def format_summary(data: Dict[str, Any]) -> str:
    """Format evaluation data for human/agent reading."""
    lines = []
    lines.append("═════════════════════════════════════════════════════════════════════")
    lines.append(f" 🚀 LIFECYCLE STATE: {data['gate'].upper()}")
    lines.append("═════════════════════════════════════════════════════════════════════")
    lines.append(f"• Internal State : {data['state_key']}")
    workflow = data.get("config", {}).get("workflow", {})
    lines.append(f"• Workflow       : {workflow.get('profile', 'standard')} / {workflow.get('execution', 'auto')}")
    if data.get("active_change"):
        ac = data["active_change"]
        lines.append(f"• Change ID      : {ac.get('change_id')} (rev: r{ac.get('revision_counter', 0)}, phase: {ac.get('phase')})")
        if ac.get("blockers"):
            lines.append(f"  └─ Blockers    : {', '.join(ac['blockers'])}")
    elif data.get("target_change"):
        lines.append(f"• Active Change  : {data.get('target_change')}")

    git = data["git"]
    if git["is_git"]:
        status_str = "Clean" if git["is_clean"] else f"Dirty ({git['modified_count']} mod, {git['untracked_count']} untracked)"
        commit_str = f" [{git['commit'][:7]}]" if git.get("commit") else ""
        lines.append(f"• Git Branch     : {git['branch']}{commit_str} ({status_str})")
        if git.get("modified_source_files"):
            lines.append(f"  └─ Unreviewed  : {', '.join(git['modified_source_files'][:3])}")
    else:
        lines.append("• Git Branch     : Non-git workspace")

    adrs = data["adrs"]
    if adrs:
        adr_names = [f"{a['name']} ({a['status']})" for a in adrs]
        lines.append(f"• ADRs Found     : {', '.join(adr_names)}")
    else:
        lines.append("• ADRs Found     : None")

    pkgs = data["openspec_packages"]
    if pkgs:
        for p in pkgs:
            marker = " [ACTIVE]" if p.get("is_active_target") else ""
            pkg_name = p.get("change")
            lines.append(
                f"• OpenSpec '{pkg_name}'{marker} : {p['completed_tasks']}/{p['total_tasks']} tasks complete, "
                f"specs={'yes' if p['has_specs'] else 'no'}, proposal={'yes' if p['has_proposal'] else 'no'}"
            )
            if p["next_task"]:
                lines.append(f"  └─ Next Task   : {p['next_task']}")
    else:
        lines.append("• OpenSpec       : None")

    living_specs = data.get("openspec_living_specs", [])
    if living_specs:
        lines.append(f"• Living Specs   : {len(living_specs)} spec(s) in openspec/specs/")

    archived = data.get("openspec_archived", [])
    if archived:
        lines.append(f"• Archived Pkgs  : {len(archived)} package(s) in openspec/archive/")

    spikes = data["active_spikes"]
    if spikes:
        lines.append(f"• Active Spikes  : {', '.join(spikes)}")

    report = data["review_report"]
    if report:
        env_str = " [Envelope]" if report.get("is_envelope") else ""
        verdict_str = f" verdict={report.get('verdict') or report.get('status')}"
        ev_str = f" tests={'passed' if report.get('test_evidence_passed') else 'failed/missing'}"
        crit_str = f" critical/high={report.get('critical_or_high_count')}"
        lines.append(f"• Review Report   : {report['path']}{env_str} (by {report['reviewer']},{verdict_str},{ev_str},{crit_str})")

    verif = (data.get("active_change") or {}).get("verification", {})
    if verif:
        parts = []
        for tier_name, item in verif.items():
            if isinstance(item, dict):
                v_str = item.get("verdict", "UNKNOWN")
                parts.append(f"{tier_name}={v_str}")
        if parts:
            lines.append(f"• Verification    : {', '.join(parts)}")

    if data.get("config", {}).get("config_source"):
        cfg = data["config"]
        t_cmd = cfg.get("gates", {}).get("implementation", {}).get("test") or "autodetect"
        lines.append(f"• Config File    : {cfg['config_source']} (test: '{t_cmd}')")

    lines.append("─────────────────────────────────────────────────────────────────────")
    lines.append("👉 RECOMMENDED NEXT ACTION:")
    lines.append(f"   {data['next_action']}")
    lines.append("═════════════════════════════════════════════════════════════════════")
    return "\n".join(lines)


class LifecycleEngine:
    """High-level dependency-injected coordinator for repository lifecycle state evaluation."""

    def __init__(
        self,
        vcs_client: Optional[GitClient] = None,
        config_manager: Optional[ShipConfigManager] = None,
        spec_repo: Optional[OpenSpecRepository] = None,
        ledger_store: Optional[FileLedgerStore] = None,
    ):
        self.vcs = vcs_client or GitClient()
        self.config_manager = config_manager or ShipConfigManager()
        self.spec_repo = spec_repo or OpenSpecRepository()
        self.ledger = ledger_store or FileLedgerStore()
        self.checkpoints = CheckpointManager(self.vcs, self.config_manager, self.ledger)

    def evaluate_repository(
        self,
        repo_root: Path,
        target_change: Optional[str] = None,
        config_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Perform a full lifecycle evaluation of the repository."""
        with self.ledger.lock(repo_root):
            pass  # Recover interrupted archives before inspecting workspace or Git state.
        config = self.config_manager.load(repo_root, explicit_path=config_path)
        git_info = self.vcs.get_info(repo_root)
        adrs = self.spec_repo.inspect_adrs(repo_root)
        resolved_target = target_change
        openspec_packages = self.spec_repo.inspect_openspec(
            repo_root,
            target_change=resolved_target,
            get_active_fn=self.ledger.get_active_change,
            clear_active_fn=self.ledger.clear_active_change,
        )
        archived_packages = self.spec_repo.inspect_archived_openspec(repo_root)
        living_specs = self.spec_repo.inspect_living_specs(repo_root)
        spikes = inspect_spikes(repo_root)
        active_pkg_change = openspec_packages[0]["change"] if openspec_packages else None
        review_report = inspect_review_reports(repo_root, change=resolved_target or active_pkg_change)

        resolved_change = resolved_target or self.ledger.get_active_change(repo_root) or active_pkg_change
        ledger = self.ledger.load(
            repo_root,
            auto_sync=True,
            sync_fn=lambda r: self.sync_ledger(r, resolved_change),
        )
        active_change = ledger.get("changes", {}).get(resolved_change) if resolved_change else None

        if openspec_packages:
            design_error = validate_design_approval(repo_root, active_pkg_change, active_change)
            active_change = dict(active_change or {})
            active_change["blockers"] = [b for b in active_change.get("blockers", []) if not b.startswith("Design:")]
            if design_error:
                active_change["blockers"].append(f"Design: {design_error}")

        gate, state_key, next_action = determine_lifecycle_state(
            git_info, adrs, openspec_packages, spikes, review_report,
            active_change=active_change, repo_root=repo_root,
            verification_config=config.get("gates"),
        )

        return {
            "repo_root": str(repo_root),
            "target_change": resolved_change,
            "gate": gate,
            "state_key": state_key,
            "next_action": next_action,
            "git": git_info,
            "adrs": adrs,
            "openspec_packages": openspec_packages,
            "openspec_archived": archived_packages,
            "openspec_living_specs": living_specs,
            "active_spikes": spikes,
            "review_report": review_report,
            "config": config,
            "ledger": ledger,
            "active_change": active_change,
        }

    def get_next_turn_contract(
        self,
        repo_root: Path,
        target_change: Optional[str] = None,
        config_path: Optional[str] = None,
        execution_mode: Optional[str] = None,
    ) -> Any:
        """Derive the deterministic Turn Contract for the next required specialist activity."""
        eval_data = self.evaluate_repository(repo_root, target_change=target_change, config_path=config_path)
        from .turns import get_next_turn_contract
        return get_next_turn_contract(eval_data, execution_mode=execution_mode)

    def sync_ledger(self, repo_root: Path, target_change_id: Optional[str] = None) -> Dict[str, Any]:
        """Reconcile and self-heal state ledger from disk artifacts."""
        return self.ledger.sync_from_workspace(
            repo_root,
            target_change_id=target_change_id,
            inspect_openspec_fn=lambda r, target_change=None: self.spec_repo.inspect_openspec(
                r,
                target_change=target_change,
                get_active_fn=self.ledger.get_active_change,
                clear_active_fn=self.ledger.clear_active_change,
            ),
            inspect_adrs_fn=self.spec_repo.inspect_adrs,
            inspect_spikes_fn=inspect_spikes,
            inspect_review_fn=inspect_review_reports,
        )

    def archive_change(self, repo_root: Path, change: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """Promote change to living truth and archive."""
        return self.spec_repo.archive_change(
            repo_root,
            change=change,
            force=force,
            load_ledger_fn=lambda r, auto_sync=False: self.ledger.load(r, auto_sync=auto_sync),
            inspect_review_fn=inspect_review_reports,
            get_git_info_fn=self.vcs.get_info,
            clear_active_fn=self.ledger.clear_active_change,
            generate_trailers_fn=lambda r, change_id=None: CommitTrailerGenerator.generate(
                r,
                change_id=change_id,
                load_ledger_fn=lambda r2, auto_sync=False: self.ledger.load(r2, auto_sync=auto_sync),
                load_config_fn=self.config_manager.load,
                get_active_change_fn=self.ledger.get_active_change,
                get_git_info_fn=self.vcs.get_info,
            ),
            mutate_change_fn=lambda r, cid, upd, set_active=False: self.ledger.mutate_change(
                r, cid, upd, set_active=set_active
            ),
            get_active_fn=self.ledger.get_active_change,
        )

    def verify_change(
        self,
        repo_root: Path,
        change: Optional[str] = None,
        tiers: Optional[List[str]] = None,
        record_to_ledger: bool = True,
        test_command: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Perform multi-tier independent verification of a change."""
        from .verification import run_gate_verification
        from .operations import detect_test_command

        eval_data = self.evaluate_repository(repo_root, target_change=change)
        cid = change or eval_data.get("target_change") or "default"
        config = eval_data.get("config", {})
        active_pkg = eval_data["openspec_packages"][0] if eval_data.get("openspec_packages") else None
        review_report = eval_data.get("review_report")
        active_change = eval_data.get("active_change")

        cmd = test_command or config.get("gates", {}).get("implementation", {}).get("test")
        if not cmd:
            cmd = detect_test_command(repo_root)

        records = run_gate_verification(
            repo_root=repo_root,
            change=cid,
            active_pkg=active_pkg,
            review_report=review_report,
            active_change=active_change,
            config=config,
            tiers=tiers,
            test_command=cmd,
        )

        if record_to_ledger:
            self.ledger.record_verification(repo_root, records, change_id=cid)

        return records
