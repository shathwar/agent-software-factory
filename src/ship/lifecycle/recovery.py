"""Deterministic crash recovery, reconciliation, and resumption engine for AgentFlow."""

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import List, Optional

from .checkpoints import get_checkpoints_dir
from .gates import validate_delivery_readiness
from .ledger import FileLedgerStore, validate_change_id
from .models import RecoveryDecision, RecoveryStrategy
from .transactions import recover_archive
from .vcs import GitClient


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class RecoveryManager:
    """Manages deterministic crash recovery, state reconciliation, and safe forward resumption."""

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)

    def reconcile_and_recover(
        self,
        change_id: Optional[str] = None,
        force: bool = False,
        intervened_by: Optional[str] = None,
        notes: str = "",
    ) -> RecoveryDecision:
        """Deterministically reconcile divergence, recover from crashes, and resume workflow.

        Execution Pipeline:
        1. Write-Ahead Journal recovery (WAL rollback/commit).
        2. Orphan checkpoint detection & cleanup.
        3. Stale lease reaping & task markdown sync.
        4. Working tree & review evidence drift reconciliation.
        5. Halt blocker clearance & human audit logging.
        6. State machine phase re-evaluation.
        """
        now_iso = _now_iso()
        reconciled: List[str] = []
        strategy = RecoveryStrategy.RESUME.value

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            cid = change_id or FileLedgerStore.get_active_change(self.repo_root) or "default"
            validate_change_id(cid)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})

            # -------------------------------------------------------------
            # 1. Recover In-flight Archive Transactions (WAL)
            # -------------------------------------------------------------
            try:
                from .ledger import _tls
                wal_status = getattr(_tls, "last_archive_recovery", None) or recover_archive(self.repo_root)
                if wal_status == "committed":
                    reconciled.append("Archive transaction finalized and committed from journal")
                    strategy = RecoveryStrategy.RESUME.value
                elif wal_status == "rolled_back":
                    reconciled.append("Interrupted archive rolled back to clean state from journal")
                    strategy = RecoveryStrategy.ROLLBACK.value
            except Exception as exc:
                # If WAL recovery raises, mark as ABORT needing human intervention
                return RecoveryDecision(
                    strategy=RecoveryStrategy.ABORT.value,
                    change_id=cid,
                    reconciled_items=reconciled,
                    restored_phase="ABORTED",
                    next_step="Human intervention required to repair corrupted archive journal",
                    details={"error": str(exc)},
                    timestamp=now_iso,
                )

            # -------------------------------------------------------------
            # 2. Reconcile Checkpoints (Prune Orphan Receipts / Disagreeing Refs)
            # -------------------------------------------------------------
            chk_dir = get_checkpoints_dir(self.repo_root)
            if chk_dir.is_dir():
                known_checkpoints = change.get("checkpoints", {})
                for chk_file in chk_dir.glob(f"{cid}_*.json"):
                    gate_tag = chk_file.stem.replace(f"{cid}_", "")
                    if gate_tag not in known_checkpoints:
                        # Orphan receipt created on disk before state write committed
                        try:
                            chk_file.unlink()
                            reconciled.append(f"Pruned uncommitted orphan checkpoint receipt: {chk_file.name}")
                            strategy = RecoveryStrategy.ROLLBACK.value
                        except Exception:
                            pass

            # -------------------------------------------------------------
            # 3. Reconcile Coordination & Task Leases
            # -------------------------------------------------------------
            coord = change.setdefault("coordination", {})
            leases = coord.setdefault("leases", {})
            now_dt = datetime.now(timezone.utc)

            for tid, l_data in list(leases.items()):
                exp_str = l_data.get("expires_at", "")
                if exp_str:
                    try:
                        exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                        if now_dt > exp_dt and l_data.get("status") in ("ACQUIRED", "RENEWED"):
                            l_data["status"] = "EXPIRED"
                            reconciled.append(f"Reaped expired task lease for task '{tid}' (holder: {l_data.get('owner_id')})")
                            strategy = RecoveryStrategy.RECONCILE.value
                    except Exception:
                        pass

            # -------------------------------------------------------------
            # 4. Reconcile Markdown tasks.md vs Ledger task_status
            # -------------------------------------------------------------
            tasks_md_path = self.repo_root / "openspec" / "changes" / cid / "tasks.md"
            if tasks_md_path.is_file():
                try:
                    content = tasks_md_path.read_text(encoding="utf-8")
                    total_tasks = 0
                    completed_tasks = 0
                    for line in content.splitlines():
                        s = line.strip()
                        if s.startswith("- [x]") or s.startswith("* [x]"):
                            total_tasks += 1
                            completed_tasks += 1
                        elif s.startswith("- [ ]") or s.startswith("* [ ]"):
                            total_tasks += 1

                    task_status = change.setdefault("task_status", {})
                    old_completed = task_status.get("completed", 0)
                    old_total = task_status.get("total", 0)

                    if total_tasks > 0 and (old_completed != completed_tasks or old_total != total_tasks):
                        task_status["total"] = total_tasks
                        task_status["completed"] = completed_tasks
                        task_status["pending"] = total_tasks - completed_tasks
                        reconciled.append(f"Synchronized task_status with tasks.md ({completed_tasks}/{total_tasks} complete)")
                        strategy = RecoveryStrategy.RECONCILE.value
                except Exception:
                    pass

            # -------------------------------------------------------------
            # 5. Reconcile Working Tree & Review Evidence Drift
            # -------------------------------------------------------------
            try:
                curr_fingerprint = GitClient().compute_working_tree_fingerprint(self.repo_root)
                review_ev = change.get("evidence", {}).get("review", {})
                recorded_fp = review_ev.get("working_tree_fingerprint")
                if recorded_fp and recorded_fp != curr_fingerprint:
                    # Files modified after review: review is STALE
                    reconciled.append("Detected file modifications post-review: marked review STALE")
                    if review_ev.get("verdict") == "PASS":
                        review_ev["verdict"] = "STALE"
                    strategy = RecoveryStrategy.RECONCILE.value
            except Exception:
                pass

            # -------------------------------------------------------------
            # 6. Clear Halt Blockers & Record Human Supervisor Recovery Turn
            # -------------------------------------------------------------
            old_blockers = list(change.get("blockers", []))
            halt_blockers = [b for b in old_blockers if b.startswith("Halt:")]
            change["blockers"] = [b for b in old_blockers if not b.startswith("Halt:")]

            if halt_blockers:
                reconciled.append(f"Cleared halt blockers: {', '.join(halt_blockers)}")
                if strategy != RecoveryStrategy.ROLLBACK.value:
                    strategy = RecoveryStrategy.RESUME.value

            # Re-evaluate phase
            pkg = {
                "change": cid,
                "has_tasks": tasks_md_path.is_file(),
                "total_tasks": change.get("task_status", {}).get("total", 1),
                "completed_tasks": change.get("task_status", {}).get("completed", 0),
                "pending_tasks": change.get("task_status", {}).get("pending", 0),
            }
            try:
                eval_phase, reason_code, message = validate_delivery_readiness(
                    review_report={"status": "pass"} if change.get("evidence", {}).get("review", {}).get("verdict") == "PASS" else None,
                    active_pkg=pkg,
                    git_info={},
                    active_change=change,
                )
            except Exception:
                eval_phase = change.get("phase", "implementation")
                reason_code = "ACTIVE"
                message = "Workflow active"

            change["phase"] = eval_phase

            # Record immutable recovery turn
            turns = change.setdefault("turns", [])
            turn_idx = len(turns) + 1
            turns.append({
                "turn_id": f"turn-{turn_idx:03d}",
                "timestamp": now_iso,
                "skill": "human",
                "harness": "human-supervisor",
                "execution_mode": "manual",
                "inputs": {
                    "action": "resume",
                    "cleared_halt": True,
                    "strategy": strategy,
                    "intervened_by": intervened_by or "supervisor",
                    "notes": notes,
                },
                "evidence": {
                    "resumed": True,
                    "reconciled_items": reconciled,
                    "strategy": strategy,
                },
                "state_delta": {
                    "phase": eval_phase,
                    "halt_cleared": bool(halt_blockers or True),
                    "reconciled_count": len(reconciled),
                },
            })

            FileLedgerStore.save(self.repo_root, ledger)

            try:
                from .events import EventLogger
                from .models import EventType
                EventLogger(self.repo_root).emit(
                    event_type=EventType.RESUME_TRIGGERED,
                    change_id=cid,
                    agent_id=intervened_by or "supervisor",
                    target=cid,
                    payload={
                        "strategy": strategy,
                        "restored_phase": eval_phase,
                        "reconciled_items": reconciled,
                        "cleared_halt_blockers": halt_blockers,
                        "notes": notes,
                    },
                )
            except Exception:
                pass

            return RecoveryDecision(
                strategy=strategy,
                change_id=cid,
                reconciled_items=reconciled,
                restored_phase=eval_phase,
                next_step=f"Phase '{eval_phase}' active ({reason_code}: {message})",
                details={
                    "reconciled_count": len(reconciled),
                    "cleared_halt_blockers": halt_blockers,
                    "phase": eval_phase,
                },
                timestamp=now_iso,
            )
