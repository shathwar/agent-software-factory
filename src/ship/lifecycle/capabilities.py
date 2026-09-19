"""Capability policy evaluation for trusted host integrations.

Evolves the security model from coarse role-based permissions:
  "Agent is allowed to write Ring 2"
to fine-grained object capabilities (OCAP):
  "This agent, in this session, for this task, currently holds this capability."

Policy evaluation pipeline (the host must enforce returned decisions):
Agent -> Identity -> Capability -> Ring policy -> Lease -> Action -> ALLOW / DENY

Zero external dependencies: 100% Python 3.10+ standard library.
"""

from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from .models import (
    AccessDecision,
    Capability,
    CapabilityOperation,
    ExecutionRing,
    TaskLease,
)
from .ledger import FileLedgerStore


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_expired(expires_at: Optional[str], now: Optional[datetime] = None) -> bool:
    if not expires_at:
        return False
    now_dt = now or _now_utc()
    try:
        norm = expires_at.replace("Z", "+00:00")
        exp_dt = datetime.fromisoformat(norm)
        return now_dt > exp_dt
    except Exception:
        return True


def _target_matches(cap_pattern: str, requested_target: str) -> bool:
    """Evaluate whether cap_pattern matches requested_target path/pattern."""
    p = cap_pattern.strip()
    t = requested_target.strip()

    if p == "*" or p == "**" or p == t:
        return True

    # Strip leading ./ for uniform matching
    if p.startswith("./"):
        p = p[2:]
    if t.startswith("./"):
        t = t[2:]

    # Exact match
    if p == t:
        return True

    # fnmatch check
    if fnmatch.fnmatchcase(t, p):
        return True

    # Subdirectory/prefix matching (e.g. src/auth matches src/auth/login.py)
    if not p.endswith("*") and not p.endswith("/"):
        p_dir = p + "/*"
        if fnmatch.fnmatchcase(t, p_dir):
            return True

    return False


class CapabilityManager:
    """Manages creation, revocation, discovery, and enforcement of fine-grained capabilities."""

    def __init__(self, repo_root: Path, ledger_store: Optional[FileLedgerStore] = None):
        self.repo_root = Path(repo_root).resolve()
        self.ledger_store = ledger_store or FileLedgerStore()

    def _get_target_change(self, change_id: Optional[str]) -> str:
        return change_id or FileLedgerStore.get_active_change(self.repo_root) or "default"

    @staticmethod
    def classify_target_ring(target: str, operation: str = "READ") -> ExecutionRing:
        """Classify a resource target into one of four Execution Rings:
        Ring 0: Hypervisor & Ledger (Immutable)
        Ring 1: Architecture & Governance (Design-Gate Locked)
        Ring 2: Production Code & Tests (TDD / Ship Dev)
        Ring 3: Disposable Workspace & Scratch (Sandboxed)
        """
        norm = target.replace("\\", "/").strip()
        if norm.startswith("./"):
            norm = norm[2:]

        # Ring 0: Hypervisor & Ledger
        ring_0_patterns = [
            ".agentflow/ledger.json",
            ".agentflow/state.json",
            ".agentflow/state.lock",
            ".agentflow/checkpoints*",
            ".agentflow/archive*",
            "refs/ship/*",
            "refs/notes/*",
        ]
        for pat in ring_0_patterns:
            if fnmatch.fnmatchcase(norm, pat) or norm == pat:
                return ExecutionRing.RING_0_HYPERVISOR

        # Ring 1: Architecture & Governance
        ring_1_patterns = [
            ".agentflow.json",
            ".agentflow/config*",
            "*invariants*.md",
            "ARCHITECTURAL_INVARIANTS.md",
            "openspec/*",
            "specs/*",
            "docs/adr/*",
            "adr/*",
            "*ADR*.md",
            ".ship/changes/*/spec.md",
            ".ship/changes/*/proposal.md",
        ]
        for pat in ring_1_patterns:
            if fnmatch.fnmatchcase(norm, pat) or fnmatch.fnmatchcase(norm.lower(), pat.lower()):
                return ExecutionRing.RING_1_GOVERNANCE

        # Ring 3: Disposable Workspace & Scratch
        ring_3_patterns = [
            ".agentflow/spikes/*",
            "scratch/*",
            "*/scratch/*",
            "build/*",
            "dist/*",
            "*.egg-info*",
            "__pycache__/*",
            "*.pyc",
            ".pytest_cache/*",
            ".mypy_cache/*",
            ".ruff_cache/*",
            "/tmp/*",
            "tmp/*",
        ]
        for pat in ring_3_patterns:
            if fnmatch.fnmatchcase(norm, pat) or norm.startswith(".agentflow/spikes/") or norm.startswith("scratch/"):
                return ExecutionRing.RING_3_WORKSPACE

        # Ring 2: Production Code & Tests (Default for workspace code and config)
        return ExecutionRing.RING_2_PRODUCTION

    def grant_capability(
        self,
        agent_id: str,
        operation: Union[CapabilityOperation, str],
        target: str,
        change_id: Optional[str] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        approval_ref: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Capability:
        """Grant a fine-grained capability to an attributable agent principal."""
        cid = self._get_target_change(change_id)
        now_dt = _now_utc()
        now_iso = _now_iso()
        op_val = operation.value if hasattr(operation, "value") else str(operation).upper()

        expires_at = None
        if ttl_seconds:
            exp_dt = datetime.fromtimestamp(now_dt.timestamp() + ttl_seconds, tz=timezone.utc)
            expires_at = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        cap_id = f"cap-{uuid.uuid4().hex[:12]}"
        cap = Capability(
            capability_id=cap_id,
            agent_id=agent_id,
            change_id=cid,
            operation=op_val,
            target=target,
            task_id=task_id,
            session_id=session_id,
            granted_at=now_iso,
            expires_at=expires_at,
            approval_ref=approval_ref,
            revoked=False,
            metadata=metadata or {},
        )

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})
            caps = change.setdefault("capabilities", {})
            caps[cap_id] = cap.to_dict()

            # Record turn audit trail
            turns = change.setdefault("turns", [])
            turns.append({
                "turn_id": f"turn-{len(turns)+1:03d}",
                "timestamp": now_iso,
                "skill": "capability-manager",
                "harness": "hypervisor",
                "execution_mode": "sequential",
                "session_id": session_id,
                "inputs": {
                    "action": "grant_capability",
                    "agent_id": agent_id,
                    "operation": op_val,
                    "target": target,
                    "task_id": task_id,
                    "approval_ref": approval_ref,
                },
                "evidence": {"capability_id": cap_id, "expires_at": expires_at},
                "state_delta": {"capability_granted": cap_id},
            })

            FileLedgerStore.save(self.repo_root, ledger)
            return cap

    def revoke_capability(
        self,
        capability_id: str,
        change_id: Optional[str] = None,
        reason: str = "",
    ) -> Optional[Capability]:
        """Revoke an active capability."""
        cid = self._get_target_change(change_id)
        now_iso = _now_iso()

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})
            caps = change.setdefault("capabilities", {})
            data = caps.get(capability_id)
            if not data:
                return None

            cap = Capability.from_dict(data)
            cap.revoked = True
            if reason:
                cap.metadata["revocation_reason"] = reason
            cap.metadata["revoked_at"] = now_iso
            caps[capability_id] = cap.to_dict()

            # Record turn audit trail
            turns = change.setdefault("turns", [])
            turns.append({
                "turn_id": f"turn-{len(turns)+1:03d}",
                "timestamp": now_iso,
                "skill": "capability-manager",
                "harness": "hypervisor",
                "execution_mode": "sequential",
                "inputs": {"action": "revoke_capability", "capability_id": capability_id, "reason": reason},
                "evidence": {"revoked": True},
                "state_delta": {"capability_revoked": capability_id},
            })

            FileLedgerStore.save(self.repo_root, ledger)
            return cap

    def get_capability(self, capability_id: str, change_id: Optional[str] = None) -> Optional[Capability]:
        """Retrieve capability by token ID."""
        cid = self._get_target_change(change_id)
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        change = ledger.get("changes", {}).get(cid, {})
        data = change.get("capabilities", {}).get(capability_id)
        return Capability.from_dict(data) if data else None

    def list_capabilities(
        self,
        change_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Capability]:
        """List all capabilities matching criteria."""
        cid = self._get_target_change(change_id)
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        change = ledger.get("changes", {}).get(cid, {})
        caps_dict = change.get("capabilities", {})
        res = [Capability.from_dict(d) for d in caps_dict.values()]

        if agent_id:
            res = [c for c in res if c.agent_id == agent_id]

        if active_only:
            now_dt = _now_utc()
            res = [c for c in res if not c.revoked and not _is_expired(c.expires_at, now_dt)]

        return res

    def evaluate_access(
        self,
        agent_id: str,
        operation: Union[CapabilityOperation, str],
        target: str,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        change_id: Optional[str] = None,
        lease_token: Optional[str] = None,
    ) -> AccessDecision:
        """Evaluate the capability policy; this method does not execute or intercept actions:
        Agent -> Identity -> Capability -> Ring policy -> Lease -> Action -> ALLOW / DENY
        """
        cid = self._get_target_change(change_id)
        op_val = operation.value if hasattr(operation, "value") else str(operation).upper()
        now_dt = _now_utc()
        now_iso = _now_iso()

        ring = self.classify_target_ring(target, op_val)
        ring_val = ring.value if hasattr(ring, "value") else str(ring)

        def _record_decision(dec: AccessDecision) -> AccessDecision:
            with FileLedgerStore.lock(self.repo_root):
                ledger_mut = FileLedgerStore.load(self.repo_root, auto_sync=False)
                ch_mut = ledger_mut.setdefault("changes", {}).setdefault(cid, {})
                audit_log = ch_mut.setdefault("security_audit", [])
                audit_log.append(dec.to_dict())
                FileLedgerStore.save(self.repo_root, ledger_mut)
            return dec

        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        change = ledger.get("changes", {}).get(cid, {})

        # 1. Identity Gate: Agent principal must be registered
        identities = change.get("provenance", {}).get("identities", {})
        if agent_id not in identities:
            # Check if active session or default session exists for agent
            sessions = change.get("provenance", {}).get("sessions", {})
            has_agent_session = any(s.get("agent_id") == agent_id for s in sessions.values())
            if not has_agent_session:
                return _record_decision(AccessDecision(
                    allowed=False,
                    reason=f"Principal '{agent_id}' is not registered in the provenance ledger",
                    ring=ring_val,
                    agent_id=agent_id,
                    operation=op_val,
                    target=target,
                    violation_code="UNKNOWN_PRINCIPAL",
                    timestamp=now_iso,
                ))

        # 2. Ring 0 Policy Gate: Autonomous agents cannot mutate Hypervisor & Ledger directly
        if ring == ExecutionRing.RING_0_HYPERVISOR and op_val in (
            CapabilityOperation.WRITE.value,
            CapabilityOperation.DELETE.value,
            CapabilityOperation.GIT.value,
        ):
            # Check if capability has explicit hypervisor/human approval_ref
            caps = change.get("capabilities", {})
            has_hypervisor_grant = False
            for d in caps.values():
                c = Capability.from_dict(d)
                if (
                    c.agent_id == agent_id
                    and c.operation in (op_val, "*")
                    and not c.revoked
                    and not _is_expired(c.expires_at, now_dt)
                    and _target_matches(c.target, target)
                    and (
                        c.approval_ref.startswith("hypervisor:")
                        or c.approval_ref.startswith("system:")
                        or c.approval_ref.startswith("human:")
                    )
                ):
                    has_hypervisor_grant = True
                    break

            if not has_hypervisor_grant:
                return _record_decision(AccessDecision(
                    allowed=False,
                    reason="Ring 0 (Hypervisor & Ledger) direct write access restricted to hypervisor/human approval",
                    ring=ring_val,
                    agent_id=agent_id,
                    operation=op_val,
                    target=target,
                    violation_code="RING_0_RESTRICTED",
                    timestamp=now_iso,
                ))

        # 3. Capability Matching Gate: Must hold an active, matching capability
        caps = change.get("capabilities", {})
        matching_cap: Optional[Capability] = None
        expired_match: Optional[Capability] = None

        for d in caps.values():
            c = Capability.from_dict(d)
            if c.agent_id != agent_id:
                continue
            if c.operation not in (op_val, "*", "ALL"):
                continue
            if not _target_matches(c.target, target):
                continue
            # Scoped constraints: task and session bindings
            if task_id and c.task_id and c.task_id != task_id:
                continue
            if session_id and c.session_id and c.session_id != session_id:
                continue

            if c.revoked:
                continue
            if _is_expired(c.expires_at, now_dt):
                expired_match = c
                continue

            matching_cap = c
            break

        if not matching_cap:
            if expired_match:
                return _record_decision(AccessDecision(
                    allowed=False,
                    reason=f"Capability '{expired_match.capability_id}' for {op_val} on '{target}' expired at {expired_match.expires_at}",
                    ring=ring_val,
                    agent_id=agent_id,
                    operation=op_val,
                    target=target,
                    capability_id=expired_match.capability_id,
                    violation_code="CAPABILITY_EXPIRED",
                    timestamp=now_iso,
                ))
            return _record_decision(AccessDecision(
                allowed=False,
                reason=f"No active capability authorizes agent '{agent_id}' to perform {op_val} on '{target}'",
                ring=ring_val,
                agent_id=agent_id,
                operation=op_val,
                target=target,
                violation_code="NO_CAPABILITY",
                timestamp=now_iso,
            ))

        # 4. Ring 1 Policy Gate: Architecture & Governance mutation requires authorized ADR or design approval
        if ring == ExecutionRing.RING_1_GOVERNANCE and op_val in (
            CapabilityOperation.WRITE.value,
            CapabilityOperation.DELETE.value,
        ):
            ref = matching_cap.approval_ref.lower()
            valid_approval = (
                ref.startswith("adr:")
                or ref.startswith("design:")
                or ref.startswith("gate:design")
                or ref.startswith("human:")
                or ref.startswith("tech_lead:")
                or "adr" in ref
            )
            if not valid_approval:
                return _record_decision(AccessDecision(
                    allowed=False,
                    reason="Ring 1 (Architecture & Governance) mutations require an approved ADR or design gate authorization ref",
                    ring=ring_val,
                    agent_id=agent_id,
                    operation=op_val,
                    target=target,
                    capability_id=matching_cap.capability_id,
                    violation_code="RING_1_UNAUTHORIZED",
                    timestamp=now_iso,
                ))

        # 5. Ring 2 & Lease Gate: Production code mutation requires an active Task Lease covering target file
        if ring == ExecutionRing.RING_2_PRODUCTION and op_val in (
            CapabilityOperation.WRITE.value,
            CapabilityOperation.DELETE.value,
        ):
            if not task_id:
                return _record_decision(AccessDecision(
                    allowed=False,
                    reason=f"Ring 2 file mutation on '{target}' requires an explicit task_id binding",
                    ring=ring_val,
                    agent_id=agent_id,
                    operation=op_val,
                    target=target,
                    capability_id=matching_cap.capability_id,
                    violation_code="LEASE_REQUIRED",
                    timestamp=now_iso,
                ))

            # Query lease in coordination store
            leases = change.get("coordination", {}).get("leases", {})
            lease_data = leases.get(task_id)
            if not lease_data:
                return _record_decision(AccessDecision(
                    allowed=False,
                    reason=f"No active task lease found for task '{task_id}'",
                    ring=ring_val,
                    agent_id=agent_id,
                    operation=op_val,
                    target=target,
                    capability_id=matching_cap.capability_id,
                    violation_code="LEASE_REQUIRED",
                    timestamp=now_iso,
                ))

            lease = TaskLease.from_dict(lease_data)
            if lease.owner_id != agent_id:
                return _record_decision(AccessDecision(
                    allowed=False,
                    reason=f"Task lease for task '{task_id}' is owned by '{lease.owner_id}', not '{agent_id}'",
                    ring=ring_val,
                    agent_id=agent_id,
                    operation=op_val,
                    target=target,
                    capability_id=matching_cap.capability_id,
                    violation_code="LEASE_OWNER_MISMATCH",
                    timestamp=now_iso,
                ))

            if lease_token and lease.lease_token != lease_token:
                return _record_decision(AccessDecision(
                    allowed=False,
                    reason="Provided lease token does not match active lease token",
                    ring=ring_val,
                    agent_id=agent_id,
                    operation=op_val,
                    target=target,
                    capability_id=matching_cap.capability_id,
                    violation_code="LEASE_TOKEN_INVALID",
                    timestamp=now_iso,
                ))

            if _is_expired(lease.expires_at, now_dt):
                return _record_decision(AccessDecision(
                    allowed=False,
                    reason=f"Task lease for task '{task_id}' expired at {lease.expires_at}",
                    ring=ring_val,
                    agent_id=agent_id,
                    operation=op_val,
                    target=target,
                    capability_id=matching_cap.capability_id,
                    violation_code="LEASE_EXPIRED",
                    timestamp=now_iso,
                ))

            # Check target files boundaries if lease has target_files specified
            if lease.target_files:
                file_covered = any(
                    _target_matches(tf, target) or tf == target
                    for tf in lease.target_files
                )
                if not file_covered:
                    return _record_decision(AccessDecision(
                        allowed=False,
                        reason=f"Target '{target}' is outside the leased file boundaries {lease.target_files}",
                        ring=ring_val,
                        agent_id=agent_id,
                        operation=op_val,
                        target=target,
                        capability_id=matching_cap.capability_id,
                        violation_code="LEASE_FILE_MISMATCH",
                        timestamp=now_iso,
                    ))

        # All gates passed: ALLOW
        decision = AccessDecision(
            allowed=True,
            reason=f"Capability '{matching_cap.capability_id}' authorizes {op_val} on '{target}' in {ring_val}",
            ring=ring_val,
            agent_id=agent_id,
            operation=op_val,
            target=target,
            capability_id=matching_cap.capability_id,
            timestamp=now_iso,
        )

        return _record_decision(decision)
