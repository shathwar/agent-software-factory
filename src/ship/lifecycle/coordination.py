"""Multi-Agent Coordination Engine for AgentFlow.

Provides distributed task leases, agent ownership, lease expiration,
stale-agent reclamation, structured Maker-Checker handoffs, and resource/file conflict detection.
Zero external runtime dependencies: relies exclusively on standard library primitives.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from .models import (
    ActionProvenance,
    AgentRole,
    CoordinationConflictType,
    LeaseStatus,
    TaskHandoff,
    TaskLease,
)
from .ledger import FileLedgerStore
from .paths import repository_path


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(iso_str: str) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        norm = iso_str.replace("Z", "+00:00")
        return datetime.fromisoformat(norm)
    except Exception:
        return None


def is_lease_expired(lease: Union[TaskLease, str, Dict[str, Any], None], now: Optional[datetime] = None) -> bool:
    """Evaluate whether a task lease (or expiration ISO timestamp) has exceeded its expiration deadline."""
    if not lease:
        return False
    if isinstance(lease, str):
        exp_dt = _parse_iso(lease)
        if not exp_dt:
            return True
        check_now = now or _now_utc()
        return check_now > exp_dt
    if isinstance(lease, dict):
        lease = TaskLease.from_dict(lease)

    st = lease.status.value if hasattr(lease.status, "value") else str(lease.status)
    if st in (LeaseStatus.RELEASED.value, LeaseStatus.EXPIRED.value, LeaseStatus.HANDED_OFF.value):
        return True
    exp_dt = _parse_iso(lease.expires_at)
    if not exp_dt:
        return True
    check_now = now or _now_utc()
    return check_now > exp_dt


@dataclass
class CoordinationConfig:
    default_lease_ttl_seconds: int = 600
    heartbeat_interval_seconds: int = 120
    allow_file_overlap: bool = False
    max_concurrent_workers: int = 4

    @classmethod
    def from_dict(cls, data: Optional[Union[Dict[str, Any], "CoordinationConfig"]]) -> "CoordinationConfig":
        if isinstance(data, cls):
            return data
        if not data or not isinstance(data, dict):
            return cls()
        coord = data.get("coordination", data)
        if not isinstance(coord, dict):
            coord = data
        return cls(
            default_lease_ttl_seconds=int(coord.get("default_lease_ttl_seconds", 600)),
            heartbeat_interval_seconds=int(coord.get("heartbeat_interval_seconds", 120)),
            allow_file_overlap=bool(coord.get("allow_file_overlap", False)),
            max_concurrent_workers=int(coord.get("max_concurrent_workers", 4)),
        )


@dataclass
class CoordinationResult:
    success: bool
    task_id: str
    lease: Optional[TaskLease] = None
    handoff: Optional[TaskHandoff] = None
    error: Optional[str] = None
    conflict_type: Optional[str] = None

    @property
    def message(self) -> str:
        return self.error or ("Success" if self.success else "Unknown failure")

    def to_dict(self) -> Dict[str, Any]:
        ct = self.conflict_type.value if hasattr(self.conflict_type, "value") else self.conflict_type
        return {
            "success": self.success,
            "task_id": self.task_id,
            "lease": self.lease.to_dict() if self.lease else None,
            "handoff": self.handoff.to_dict() if self.handoff else None,
            "error": self.error,
            "message": self.message,
            "conflict_type": ct,
        }


class CoordinationManager:
    """Coordinates multi-agent task execution, leases, and resource conflicts."""

    def __init__(
        self,
        repo_root: Path,
        config: Optional[Union[Dict[str, Any], CoordinationConfig, str]] = None,
        default_change_id: Optional[str] = None,
    ):
        self.repo_root = Path(repo_root)
        if isinstance(config, str) and default_change_id is None:
            default_change_id = config
            config = None
        self.default_change_id = default_change_id
        self.config = CoordinationConfig.from_dict(config if isinstance(config, (dict, CoordinationConfig)) else None)

    def _get_target_change(self, change_id: Optional[str]) -> str:
        return change_id or self.default_change_id or FileLedgerStore.get_active_change(self.repo_root) or "default"

    def claim_task(
        self,
        task_id: str,
        owner_id: str,
        change_id: Optional[str] = None,
        target_files: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
        ttl_seconds: Optional[int] = None,
        force: bool = False,
        session_id: Optional[str] = None,
        runtime: Optional[str] = None,
        model: Optional[str] = None,
        role: Optional[str] = None,
        parent_agent_id: Optional[str] = None,
    ) -> CoordinationResult:
        """Atomically claim an exclusive task lease for a worker agent."""
        cid = self._get_target_change(change_id)
        ttl = ttl_seconds or self.config.default_lease_ttl_seconds
        req_files = [str(f).strip() for f in (target_files or files or []) if str(f).strip()]

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})
            coord = change.setdefault("coordination", {"leases": {}, "handoffs": []})
            leases_dict = coord.setdefault("leases", {})

            now = _now_utc()
            now_iso = _now_iso()

            # 1. Check existing lease for this task
            existing_data = leases_dict.get(task_id)
            if existing_data:
                existing_lease = TaskLease.from_dict(existing_data)
                # Idempotent re-claim by same owner
                if existing_lease.owner_id == owner_id and not is_lease_expired(existing_lease, now):
                    # Refresh lease
                    exp_dt = datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc)
                    existing_lease.expires_at = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    existing_lease.heartbeat_at = now_iso
                    existing_lease.status = LeaseStatus.RENEWED.value
                    if session_id:
                        existing_lease.session_id = session_id
                    if req_files:
                        existing_lease.target_files = list(set(existing_lease.target_files) | set(req_files))
                    leases_dict[task_id] = existing_lease.to_dict()
                    FileLedgerStore.save(self.repo_root, ledger)
                    return CoordinationResult(success=True, task_id=task_id, lease=existing_lease)

                # Check if unexpired lease held by another owner
                if not is_lease_expired(existing_lease, now) and not force:
                    err = (
                        f"Task '{task_id}' is already leased by '{existing_lease.owner_id}' "
                        f"(expires at {existing_lease.expires_at})"
                    )
                    return CoordinationResult(
                        success=False,
                        task_id=task_id,
                        error=err,
                        conflict_type=CoordinationConflictType.CONCURRENT_LEASE.value,
                        lease=existing_lease,
                    )
                elif is_lease_expired(existing_lease, now):
                    # Stale agent reclamation: mark old lease expired
                    existing_lease.status = LeaseStatus.EXPIRED.value
                    leases_dict[task_id] = existing_lease.to_dict()

            # 2. Check resource/file conflict across all concurrent active leases
            if not self.config.allow_file_overlap and req_files:
                for other_tid, other_data in leases_dict.items():
                    if other_tid == task_id:
                        continue
                    other_lease = TaskLease.from_dict(other_data)
                    if not is_lease_expired(other_lease, now) and other_lease.status in (LeaseStatus.ACTIVE.value, LeaseStatus.ACQUIRED.value, LeaseStatus.RENEWED.value):
                        overlap = set(req_files) & set(other_lease.target_files)
                        if overlap and other_lease.owner_id != owner_id:
                            err = (
                                f"Resource file conflict: task '{task_id}' targets {sorted(overlap)} "
                                f"which is currently locked by '{other_lease.owner_id}' for task '{other_tid}'"
                            )
                            return CoordinationResult(
                                success=False,
                                task_id=task_id,
                                error=err,
                                conflict_type=CoordinationConflictType.FILE_OVERLAP.value,
                                lease=other_lease,
                            )

            # 3. Check worker concurrency limit
            active_worker_count = len({
                l["owner_id"] for l in leases_dict.values()
                if not is_lease_expired(TaskLease.from_dict(l), now)
                and l.get("status") in (LeaseStatus.ACTIVE.value, LeaseStatus.ACQUIRED.value, LeaseStatus.RENEWED.value)
            })
            if active_worker_count >= self.config.max_concurrent_workers and owner_id not in {
                l["owner_id"] for l in leases_dict.values()
                if not is_lease_expired(TaskLease.from_dict(l), now)
            }:
                return CoordinationResult(
                    success=False,
                    task_id=task_id,
                    error=f"Maximum concurrent workers limit ({self.config.max_concurrent_workers}) reached",
                    conflict_type=CoordinationConflictType.CONCURRENT_LEASE.value,
                )

            # 4. Issue new lease with attributable ActionProvenance
            token = uuid.uuid4().hex
            exp_dt = datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc)
            sess_id = session_id or f"sess-{owner_id}"

            from .provenance import compute_payload_digest
            prov = ActionProvenance(
                action_id=f"act-{uuid.uuid4().hex[:12]}",
                action_name="claim_task",
                agent_id=owner_id,
                session_id=sess_id,
                change_id=cid,
                role=role or AgentRole.MAKER.value,
                task_id=task_id,
                lease_token=token,
                timestamp=now_iso,
                runtime=runtime or "antigravity",
                model=model or "unknown",
                skill="coordination",
                skill_version="1.0.0",
                agentflow_version="1.0.0",
                parent_agent_id=parent_agent_id,
                inputs_digest=compute_payload_digest({"task_id": task_id, "files": req_files, "ttl": ttl}),
                evidence_digest=compute_payload_digest({"lease_token": token, "expires_at": exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")}),
            )

            new_lease = TaskLease(
                task_id=task_id,
                owner_id=owner_id,
                lease_token=token,
                claimed_at=now_iso,
                expires_at=exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                heartbeat_at=now_iso,
                ttl_seconds=ttl,
                target_files=req_files,
                status=LeaseStatus.ACQUIRED.value,
                session_id=sess_id,
                provenance=prov.to_dict(),
            )
            leases_dict[task_id] = new_lease.to_dict()

            # Record turn provenance in ledger
            turns = change.setdefault("turns", [])
            turns.append({
                "turn_id": f"turn-{len(turns)+1:03d}",
                "timestamp": now_iso,
                "skill": "coordination",
                "harness": "coordination-manager",
                "execution_mode": "parallel",
                "session_id": sess_id,
                "inputs": {
                    "action": "claim_task",
                    "task_id": task_id,
                    "owner_id": owner_id,
                    "ttl_seconds": ttl,
                    "target_files": req_files,
                },
                "evidence": {"lease_token": token, "expires_at": new_lease.expires_at},
                "state_delta": {"task_leased": task_id, "owner": owner_id},
                "provenance": prov.to_dict(),
            })

            FileLedgerStore.save(self.repo_root, ledger)
            return CoordinationResult(success=True, task_id=task_id, lease=new_lease)

    def heartbeat_lease(
        self,
        task_id: str,
        lease_token: str,
        change_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> CoordinationResult:
        """Extend lease expiration deadline for an active worker holding a valid lease token."""
        cid = self._get_target_change(change_id)
        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})
            leases_dict = change.setdefault("coordination", {}).setdefault("leases", {})

            raw_lease = leases_dict.get(task_id)
            if not raw_lease:
                return CoordinationResult(success=False, task_id=task_id, error=f"No lease found for task '{task_id}'")

            lease = TaskLease.from_dict(raw_lease)
            if lease.lease_token != lease_token:
                return CoordinationResult(success=False, task_id=task_id, error="Invalid lease token")

            now = _now_utc()
            now_iso = _now_iso()
            ttl = ttl_seconds or lease.ttl_seconds
            exp_dt = datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc)

            lease.heartbeat_at = now_iso
            lease.expires_at = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            lease.status = LeaseStatus.RENEWED.value
            leases_dict[task_id] = lease.to_dict()

            FileLedgerStore.save(self.repo_root, ledger)
            return CoordinationResult(success=True, task_id=task_id, lease=lease)

    def release_task(
        self,
        task_id: str,
        lease_token: str,
        change_id: Optional[str] = None,
        completed: bool = False,
        evidence: Optional[Dict[str, Any]] = None,
        summary: str = "",
        session_id: Optional[str] = None,
        runtime: Optional[str] = None,
        model: Optional[str] = None,
    ) -> CoordinationResult:
        """Release a task lease, optionally completing the task in tasks.md and state ledger."""
        cid = self._get_target_change(change_id)
        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})
            leases_dict = change.setdefault("coordination", {}).setdefault("leases", {})

            raw_lease = leases_dict.get(task_id)
            if not raw_lease:
                return CoordinationResult(success=False, task_id=task_id, error=f"No lease found for task '{task_id}'")

            lease = TaskLease.from_dict(raw_lease)
            if lease.lease_token != lease_token:
                return CoordinationResult(success=False, task_id=task_id, error="Invalid lease token")

            now_iso = _now_iso()
            lease.status = LeaseStatus.RELEASED.value
            if session_id:
                lease.session_id = session_id
            leases_dict[task_id] = lease.to_dict()

            ev = dict(evidence or {})
            if summary:
                ev["summary"] = summary

            if completed:
                self._mark_task_completed_in_markdown(cid, task_id)
                task_st = change.setdefault("task_status", {"total": 1, "completed": 0, "pending": 1})
                task_st["completed"] = min(task_st.get("total", 1), task_st.get("completed", 0) + 1)
                task_st["pending"] = max(0, task_st.get("total", 1) - task_st["completed"])

            from .provenance import compute_payload_digest
            sess_id = session_id or lease.session_id or f"sess-{lease.owner_id}"
            prov = ActionProvenance(
                action_id=f"act-{uuid.uuid4().hex[:12]}",
                action_name="release_task",
                agent_id=lease.owner_id,
                session_id=sess_id,
                change_id=cid,
                role=AgentRole.MAKER.value,
                task_id=task_id,
                lease_token=lease_token,
                timestamp=now_iso,
                runtime=runtime or "antigravity",
                model=model or "unknown",
                skill="coordination",
                skill_version="1.0.0",
                agentflow_version="1.0.0",
                inputs_digest=compute_payload_digest({"task_id": task_id, "completed": completed}),
                evidence_digest=compute_payload_digest(ev),
            )

            turns = change.setdefault("turns", [])
            turns.append({
                "turn_id": f"turn-{len(turns)+1:03d}",
                "timestamp": now_iso,
                "skill": "coordination",
                "harness": "coordination-manager",
                "execution_mode": "parallel",
                "session_id": sess_id,
                "inputs": {
                    "action": "release_task",
                    "task_id": task_id,
                    "owner_id": lease.owner_id,
                    "completed": completed,
                },
                "evidence": ev,
                "state_delta": {"task_released": task_id, "completed": completed},
                "provenance": prov.to_dict(),
            })

            FileLedgerStore.save(self.repo_root, ledger)
            return CoordinationResult(success=True, task_id=task_id, lease=lease)

    def handoff_task(
        self,
        task_id: str,
        from_owner: Optional[str] = None,
        to_owner: Optional[str] = None,
        lease_token: Optional[str] = None,
        change_id: Optional[str] = None,
        reason: str = "",
        artifacts: Optional[List[str]] = None,
        verification_checklist: Optional[List[str]] = None,
        notes: str = "",
        new_ttl_seconds: Optional[int] = None,
        session_id: Optional[str] = None,
        runtime: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> CoordinationResult:
        """Atomically hand off task ownership from one agent (e.g. Maker) to another (e.g. Checker)."""
        # Support both (task_id, from_owner, to_owner, lease_token) and (task_id, lease_token, from_owner, to_owner)
        if from_owner and len(from_owner) == 32 and all(c in "0123456789abcdefABCDEF" for c in from_owner) and not lease_token:
            actual_token = from_owner
            actual_from = to_owner or ""
            actual_to = str(kwargs.get("arg4") or "")
        else:
            actual_token = lease_token or kwargs.get("token") or ""
            actual_from = from_owner or kwargs.get("from") or ""
            actual_to = to_owner or kwargs.get("to") or ""

        actual_reason = reason or notes or kwargs.get("reason", "") or kwargs.get("notes", "")
        checklist = verification_checklist or kwargs.get("checklist") or []

        cid = self._get_target_change(change_id)
        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})
            coord = change.setdefault("coordination", {"leases": {}, "handoffs": []})
            leases_dict = coord.setdefault("leases", {})
            handoffs_list = coord.setdefault("handoffs", [])

            raw_lease = leases_dict.get(task_id)
            if not raw_lease:
                return CoordinationResult(success=False, task_id=task_id, error=f"No lease found for task '{task_id}'")

            old_lease = TaskLease.from_dict(raw_lease)
            if old_lease.lease_token != actual_token:
                return CoordinationResult(success=False, task_id=task_id, error="Invalid lease token")
            if actual_from and old_lease.owner_id != actual_from:
                return CoordinationResult(success=False, task_id=task_id, error=f"Lease owner is '{old_lease.owner_id}', not '{actual_from}'")

            now = _now_utc()
            now_iso = _now_iso()
            new_token = uuid.uuid4().hex
            ttl = new_ttl_seconds or old_lease.ttl_seconds
            exp_dt = datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc)
            sess_id = session_id or old_lease.session_id or f"sess-{actual_to}"

            # Invalidate old lease
            old_lease.status = LeaseStatus.HANDED_OFF.value

            from .provenance import compute_payload_digest
            from_prov = ActionProvenance(
                action_id=f"act-{uuid.uuid4().hex[:12]}",
                action_name="handoff_release",
                agent_id=actual_from,
                session_id=session_id or old_lease.session_id or f"sess-{actual_from}",
                change_id=cid,
                role=AgentRole.MAKER.value,
                task_id=task_id,
                lease_token=actual_token,
                timestamp=now_iso,
                runtime=runtime or "antigravity",
                model=model or "unknown",
                skill="coordination",
                skill_version="1.0.0",
                agentflow_version="1.0.0",
                inputs_digest=compute_payload_digest({"task_id": task_id, "to_owner": actual_to, "reason": actual_reason}),
                evidence_digest=compute_payload_digest({"checklist": checklist, "artifacts": artifacts or []}),
            )
            to_prov = ActionProvenance(
                action_id=f"act-{uuid.uuid4().hex[:12]}",
                action_name="handoff_acquire",
                agent_id=actual_to,
                session_id=sess_id,
                change_id=cid,
                role=AgentRole.CHECKER.value,
                task_id=task_id,
                lease_token=new_token,
                timestamp=now_iso,
                runtime=runtime or "antigravity",
                model=model or "unknown",
                skill="coordination",
                skill_version="1.0.0",
                agentflow_version="1.0.0",
                parent_agent_id=actual_from,
                inputs_digest=compute_payload_digest({"task_id": task_id, "from_owner": actual_from, "reason": actual_reason}),
                evidence_digest=compute_payload_digest({"new_lease_token": new_token, "expires_at": exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")}),
            )

            # Issue new lease to recipient
            new_lease = TaskLease(
                task_id=task_id,
                owner_id=actual_to,
                lease_token=new_token,
                claimed_at=now_iso,
                expires_at=exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                heartbeat_at=now_iso,
                ttl_seconds=ttl,
                target_files=list(old_lease.target_files),
                status=LeaseStatus.ACTIVE.value,
                session_id=sess_id,
                metadata={"handed_off_from": actual_from, "reason": actual_reason},
                provenance=to_prov.to_dict(),
            )
            leases_dict[task_id] = new_lease.to_dict()

            # Record formal handoff event
            handoff_record = TaskHandoff(
                task_id=task_id,
                from_owner=actual_from,
                to_owner=actual_to,
                old_token=actual_token[:8] + "...",
                new_token=new_token[:8] + "...",
                timestamp=now_iso,
                reason=actual_reason,
                artifacts=artifacts or [],
                verification_checklist=checklist,
                notes=actual_reason,
                session_id=sess_id,
                from_provenance=from_prov.to_dict(),
                to_provenance=to_prov.to_dict(),
            )
            handoffs_list.append(handoff_record.to_dict())

            # Log provenance turn
            turns = change.setdefault("turns", [])
            turns.append({
                "turn_id": f"turn-{len(turns)+1:03d}",
                "timestamp": now_iso,
                "skill": "coordination",
                "harness": "coordination-manager",
                "execution_mode": "parallel",
                "session_id": sess_id,
                "inputs": {
                    "action": "handoff_task",
                    "task_id": task_id,
                    "from_owner": actual_from,
                    "to_owner": actual_to,
                    "reason": actual_reason,
                },
                "evidence": {"new_lease_token": new_token, "artifacts": artifacts or []},
                "state_delta": {"handoff": f"{actual_from} -> {actual_to}"},
                "provenance": to_prov.to_dict(),
            })

            FileLedgerStore.save(self.repo_root, ledger)
            return CoordinationResult(success=True, task_id=task_id, lease=new_lease, handoff=handoff_record)

    def reap_stale_leases(self, change_id: Optional[str] = None) -> List[TaskLease]:
        """Detect and reap any active leases whose TTL expiration has lapsed."""
        cid = self._get_target_change(change_id)
        reaped: List[TaskLease] = []
        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})
            leases_dict = change.setdefault("coordination", {}).setdefault("leases", {})

            now = _now_utc()
            now_iso = _now_iso()
            modified = False

            for tid, raw_data in list(leases_dict.items()):
                lease = TaskLease.from_dict(raw_data)
                if lease.status in (LeaseStatus.ACTIVE.value, LeaseStatus.ACQUIRED.value, LeaseStatus.RENEWED.value):
                    if is_lease_expired(lease, now):
                        lease.status = LeaseStatus.EXPIRED.value
                        leases_dict[tid] = lease.to_dict()
                        reaped.append(lease)
                        modified = True

            if modified:
                turns = change.setdefault("turns", [])
                turns.append({
                    "turn_id": f"turn-{len(turns)+1:03d}",
                    "timestamp": now_iso,
                    "skill": "coordination",
                    "harness": "stale-agent-reaper",
                    "execution_mode": "parallel",
                    "inputs": {"action": "reap_stale_leases", "reaped_count": len(reaped)},
                    "evidence": {"reaped_tasks": [l.task_id for l in reaped]},
                    "state_delta": {"stale_agents_reaped": len(reaped)},
                })
                FileLedgerStore.save(self.repo_root, ledger)

        return reaped

    def list_leases(self, change_id: Optional[str] = None, active_only: bool = False) -> List[TaskLease]:
        """List all leases for a change package, lazily reaping any expired leases."""
        self.reap_stale_leases(change_id)
        cid = self._get_target_change(change_id)
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        change = ledger.get("changes", {}).get(cid, {})
        leases_dict = change.get("coordination", {}).get("leases", {})

        leases = [TaskLease.from_dict(d) for d in leases_dict.values()]
        if active_only:
            leases = [l for l in leases if l.status in (LeaseStatus.ACTIVE.value, LeaseStatus.ACQUIRED.value, LeaseStatus.RENEWED.value)]
        return leases

    def _mark_task_completed_in_markdown(self, change_id: str, task_id: str) -> None:
        """Mark the corresponding item completed [x] in tasks.md."""
        candidates = [
            self.repo_root / "openspec" / "changes" / change_id / "tasks.md",
            self.repo_root / ".ship" / "changes" / change_id / "tasks.md",
            self.repo_root / "changes" / change_id / "tasks.md",
        ]
        tasks_file = next((c for c in candidates if c.exists()), None)
        if not tasks_file:
            return
        content = tasks_file.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(keepends=True)
        new_lines = []
        for line in lines:
            stripped = line.strip()
            # Match "- [ ] 1.1 ..." or "- [ ] <task_id> ..."
            if stripped.startswith(("- [ ]", "* [ ]")):
                task_body = stripped[5:].strip()
                if task_body.startswith(task_id) or f"`{task_id}`" in task_body:
                    line = line.replace("- [ ]", "- [x]", 1).replace("* [ ]", "* [x]", 1)
            new_lines.append(line)
        tasks_file.write_text("".join(new_lines), encoding="utf-8")
