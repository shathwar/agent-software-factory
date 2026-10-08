"""Agent Identity & Provenance Engine.

Establishes an unbroken binding chain:
agent -> session -> change -> task -> lease -> action -> evidence -> verification

Zero external dependencies (Python 3.10+ standard library).
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from .models import (
    AgentRole,
    AgentIdentity,
    AgentSession,
    ActionProvenance,
    TaskLease,
    VerificationRecord,
)
from .ledger import FileLedgerStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_payload_digest(payload: Any) -> str:
    """Compute a canonical, deterministic SHA-256 digest for any arbitrary JSON-compatible payload."""
    if payload is None:
        return ""
    if isinstance(payload, str):
        content = payload.encode("utf-8")
    elif hasattr(payload, "to_dict"):
        content = json.dumps(payload.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    else:
        try:
            content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except Exception:
            content = str(payload).encode("utf-8")
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


class ProvenanceManager:
    """Manages Agent Identity, Sessions, and cryptographic Action Provenance chains."""

    def __init__(self, repo_root: Path, ledger_store: Optional[FileLedgerStore] = None):
        self.repo_root = Path(repo_root).resolve()
        self.ledger_store = ledger_store or FileLedgerStore()

    def _get_target_change(self, change_id: Optional[str]) -> str:
        return change_id or FileLedgerStore.get_active_change(self.repo_root) or "default"

    def register_identity(
        self,
        agent_id: str,
        role: Optional[Union[AgentRole, str]] = None,
        runtime: str = "antigravity",
        model: str = "unknown",
        parent_agent_id: Optional[str] = None,
        change_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentIdentity:
        """Register or update an agent identity principal in the ledger."""
        cid = self._get_target_change(change_id)
        role_str = role.value if hasattr(role, "value") else str(role or AgentRole.SPECIALIST.value)
        now_iso = _now_iso()

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})
            prov_store = change.setdefault("provenance", {"identities": {}, "sessions": {}, "actions": []})
            identities = prov_store.setdefault("identities", {})

            existing = identities.get(agent_id)
            if existing:
                identity = AgentIdentity.from_dict(existing)
                identity.role = role_str
                identity.runtime = runtime
                identity.model = model
                if parent_agent_id:
                    identity.parent_agent_id = parent_agent_id
                if metadata:
                    identity.metadata.update(metadata)
            else:
                identity = AgentIdentity(
                    agent_id=agent_id,
                    role=role_str,
                    runtime=runtime,
                    model=model,
                    parent_agent_id=parent_agent_id,
                    created_at=now_iso,
                    metadata=metadata or {},
                )

            identities[agent_id] = identity.to_dict()
            FileLedgerStore.save(self.repo_root, ledger)
            return identity

    def get_identity(self, agent_id: str, change_id: Optional[str] = None) -> Optional[AgentIdentity]:
        """Retrieve an agent identity by principal ID."""
        cid = self._get_target_change(change_id)
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        change = ledger.get("changes", {}).get(cid, {})
        identities = change.get("provenance", {}).get("identities", {})
        data = identities.get(agent_id)
        return AgentIdentity.from_dict(data) if data else None

    def list_identities(self, change_id: Optional[str] = None) -> List[AgentIdentity]:
        """List all registered agent principals for the specified change."""
        cid = self._get_target_change(change_id)
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        change = ledger.get("changes", {}).get(cid, {})
        identities = change.get("provenance", {}).get("identities", {})
        return [AgentIdentity.from_dict(d) for d in identities.values()]

    def start_session(
        self,
        agent_id: str,
        role: Optional[Union[AgentRole, str]] = None,
        change_id: Optional[str] = None,
        runtime: Optional[str] = None,
        model: Optional[str] = None,
        skill: str = "",
        skill_version: str = "1.0.0",
        agentflow_version: str = "1.0.0",
        parent_session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentSession:
        """Start a new execution session for an agent principal."""
        cid = self._get_target_change(change_id)
        now_iso = _now_iso()
        session_id = f"sess-{uuid.uuid4().hex[:12]}"

        # Look up or auto-register identity
        ident = self.get_identity(agent_id, cid)
        resolved_role = (
            role.value if hasattr(role, "value") else str(role)
            if role else (ident.role if ident else AgentRole.SPECIALIST.value)
        )
        resolved_runtime = runtime or (ident.runtime if ident else "antigravity")
        resolved_model = model or (ident.model if ident else "unknown")

        if not ident:
            self.register_identity(
                agent_id=agent_id,
                role=resolved_role,
                runtime=resolved_runtime,
                model=resolved_model,
                change_id=cid,
            )

        from .signing import AgentTokenAuthority
        token_auth = AgentTokenAuthority()
        session_token = token_auth.mint_session_token(
            agent_id=agent_id,
            session_id=session_id,
            role=resolved_role,
            ring="RING_2_PRODUCTION",
            change_id=cid,
            parent_session_id=parent_session_id,
        )

        session_meta = dict(metadata or {})
        session_meta["session_token"] = session_token

        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            change_id=cid,
            role=resolved_role,
            started_at=now_iso,
            agentflow_version=agentflow_version,
            skill=skill,
            skill_version=skill_version,
            runtime=resolved_runtime,
            model=resolved_model,
            status="ACTIVE",
            parent_session_id=parent_session_id,
            metadata=session_meta,
        )

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})
            prov_store = change.setdefault("provenance", {"identities": {}, "sessions": {}, "actions": []})
            prov_store.setdefault("sessions", {})[session_id] = session.to_dict()

            # Record turn provenance
            turns = change.setdefault("turns", [])
            turns.append({
                "turn_id": f"turn-{len(turns)+1:03d}",
                "timestamp": now_iso,
                "skill": skill or "provenance",
                "harness": "provenance-manager",
                "execution_mode": "sequential",
                "session_id": session_id,
                "inputs": {"action": "start_session", "agent_id": agent_id, "role": resolved_role},
                "evidence": {"session_id": session_id, "started_at": now_iso},
                "state_delta": {"active_session": session_id, "agent": agent_id},
            })

            FileLedgerStore.save(self.repo_root, ledger)

            try:
                from .events import EventLogger
                EventLogger(self.repo_root).emit(
                    event_type="AGENT_STARTED",
                    change_id=cid,
                    agent_id=agent_id,
                    session_id=session_id,
                    payload={
                        "role": resolved_role,
                        "runtime": resolved_runtime,
                        "model": resolved_model,
                        "skill": skill,
                        "skill_version": skill_version,
                        "agentflow_version": agentflow_version,
                    },
                )
            except Exception:
                pass

            return session

    def end_session(
        self,
        session_id: str,
        change_id: Optional[str] = None,
        status: str = "COMPLETED",
    ) -> Optional[AgentSession]:
        """Mark an active session as completed/closed."""
        cid = self._get_target_change(change_id)
        now_iso = _now_iso()

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})
            sessions = change.setdefault("provenance", {}).setdefault("sessions", {})
            data = sessions.get(session_id)
            if not data:
                return None

            session = AgentSession.from_dict(data)
            session.ended_at = now_iso
            session.status = status
            sessions[session_id] = session.to_dict()

            FileLedgerStore.save(self.repo_root, ledger)

            try:
                from .events import EventLogger
                EventLogger(self.repo_root).emit(
                    event_type="AGENT_STOPPED",
                    change_id=cid,
                    agent_id=session.agent_id,
                    session_id=session_id,
                    payload={"status": status, "ended_at": now_iso},
                )
            except Exception:
                pass

            return session

    def get_session(self, session_id: str, change_id: Optional[str] = None) -> Optional[AgentSession]:
        """Retrieve session record by session ID."""
        cid = self._get_target_change(change_id)
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        change = ledger.get("changes", {}).get(cid, {})
        sessions = change.get("provenance", {}).get("sessions", {})
        data = sessions.get(session_id)
        return AgentSession.from_dict(data) if data else None

    def list_sessions(self, change_id: Optional[str] = None, active_only: bool = False) -> List[AgentSession]:
        """List all sessions recorded for a change package."""
        cid = self._get_target_change(change_id)
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        change = ledger.get("changes", {}).get(cid, {})
        sessions = change.get("provenance", {}).get("sessions", {})
        res = [AgentSession.from_dict(d) for d in sessions.values()]
        if active_only:
            res = [s for s in res if s.status == "ACTIVE" and not s.ended_at]
        return res

    def build_action_provenance(
        self,
        action_name: str,
        agent_id: str,
        session_id: Optional[str] = None,
        change_id: Optional[str] = None,
        role: Optional[Union[AgentRole, str]] = None,
        task_id: Optional[str] = None,
        lease_token: Optional[str] = None,
        inputs: Optional[Any] = None,
        evidence: Optional[Any] = None,
        parent_agent_id: Optional[str] = None,
        runtime: Optional[str] = None,
        model: Optional[str] = None,
        skill: Optional[str] = None,
        skill_version: str = "1.0.0",
        agentflow_version: str = "1.0.0",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ActionProvenance:
        """Create and record an immutable ActionProvenance record."""
        cid = self._get_target_change(change_id)
        now_iso = _now_iso()
        action_id = f"act-{uuid.uuid4().hex[:12]}"

        # Look up session context if provided
        sess = self.get_session(session_id, cid) if session_id else None
        ident = self.get_identity(agent_id, cid)

        resolved_session_id = session_id or (sess.session_id if sess else f"implicit-{agent_id}")
        resolved_role = (
            role.value if hasattr(role, "value") else str(role)
            if role else (sess.role if sess else (ident.role if ident else AgentRole.SPECIALIST.value))
        )
        resolved_runtime = runtime or (sess.runtime if sess else (ident.runtime if ident else "antigravity"))
        resolved_model = model or (sess.model if sess else (ident.model if ident else "unknown"))
        resolved_skill = skill or (sess.skill if sess else "")
        resolved_parent = parent_agent_id or (ident.parent_agent_id if ident else None)

        inp_digest = compute_payload_digest(inputs)
        ev_digest = compute_payload_digest(evidence)

        prov = ActionProvenance(
            action_id=action_id,
            action_name=action_name,
            agent_id=agent_id,
            session_id=resolved_session_id,
            change_id=cid,
            role=resolved_role,
            task_id=task_id,
            lease_token=lease_token,
            timestamp=now_iso,
            runtime=resolved_runtime,
            model=resolved_model,
            skill=resolved_skill,
            skill_version=skill_version,
            agentflow_version=agentflow_version,
            parent_agent_id=resolved_parent,
            inputs_digest=inp_digest,
            evidence_digest=ev_digest,
            metadata=metadata or {},
        )

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            change = ledger.setdefault("changes", {}).setdefault(cid, {})
            actions = change.setdefault("provenance", {}).setdefault("actions", [])
            actions.append(prov.to_dict())
            FileLedgerStore.save(self.repo_root, ledger)

        return prov

    def verify_binding_chain(
        self,
        provenance: ActionProvenance,
        task_lease: Optional[TaskLease] = None,
        verification_record: Optional[VerificationRecord] = None,
    ) -> Dict[str, Any]:
        """Verify the unbroken provenance binding chain:
        agent -> session -> change -> task -> lease -> action -> evidence -> verification
        """
        chain_steps: List[str] = []
        errors: List[str] = []

        # 1. Agent Identity
        chain_steps.append(f"agent:{provenance.agent_id} ({provenance.role})")
        if not provenance.agent_id:
            errors.append("Action has no attributable agent_id principal")

        # 2. Session & Token Verification
        chain_steps.append(f"session:{provenance.session_id}")
        if not provenance.session_id:
            errors.append("Action is not bound to a session")
        else:
            sess = self.get_session(provenance.session_id, provenance.change_id)
            if sess and sess.metadata and "session_token" in sess.metadata:
                from .signing import AgentTokenAuthority
                token_auth = AgentTokenAuthority()
                valid_tok, tok_reason, claims = token_auth.verify_session_token(sess.metadata["session_token"])
                if not valid_tok:
                    errors.append(f"Session token verification failed: {tok_reason}")
                elif claims.get("agent_id") != provenance.agent_id:
                    errors.append(
                        f"Session token agent '{claims.get('agent_id')}' does not match action agent '{provenance.agent_id}'"
                    )

        # 3. Change
        chain_steps.append(f"change:{provenance.change_id}")
        if not provenance.change_id:
            errors.append("Action is not bound to a target change")

        # 4. Task
        if provenance.task_id:
            chain_steps.append(f"task:{provenance.task_id}")

        # 5. Lease
        if task_lease:
            chain_steps.append(f"lease:{task_lease.lease_token[:8]}...")
            if task_lease.owner_id != provenance.agent_id:
                errors.append(
                    f"Lease owner '{task_lease.owner_id}' does not match action agent '{provenance.agent_id}'"
                )
            if provenance.task_id and task_lease.task_id != provenance.task_id:
                errors.append(
                    f"Lease task_id '{task_lease.task_id}' does not match action task_id '{provenance.task_id}'"
                )

        # 6. Action
        chain_steps.append(f"action:{provenance.action_name} [{provenance.action_id}]")

        # 7. Evidence
        if provenance.evidence_digest:
            chain_steps.append(f"evidence:{provenance.evidence_digest[:16]}...")

        # 8. Verification (Maker != Checker rule)
        if verification_record:
            chain_steps.append(f"verification:{verification_record.verdict} by {verification_record.verifier_id}")
            verif_prov = verification_record.provenance
            if verif_prov:
                verifier_agent = verif_prov.get("agent_id") if isinstance(verif_prov, dict) else getattr(verif_prov, "agent_id", None)
                if verifier_agent and verifier_agent == provenance.agent_id:
                    errors.append(
                        f"Maker-Checker violation: agent '{provenance.agent_id}' cannot independently verify their own action"
                    )

        return {
            "valid": len(errors) == 0,
            "chain": chain_steps,
            "chain_str": " -> ".join(chain_steps),
            "errors": errors,
            "attributable_principal": {
                "agent_id": provenance.agent_id,
                "role": provenance.role,
                "session_id": provenance.session_id,
                "runtime": provenance.runtime,
                "model": provenance.model,
                "skill": f"{provenance.skill}@{provenance.skill_version}" if provenance.skill else "core",
                "agentflow_version": provenance.agentflow_version,
                "parent_agent_id": provenance.parent_agent_id,
                "timestamp": provenance.timestamp,
            },
        }

    @staticmethod
    def enforce_maker_checker_separation(
        maker_prov: Union[ActionProvenance, Dict[str, Any]],
        checker_prov: Union[ActionProvenance, Dict[str, Any]],
    ) -> Tuple[bool, str]:
        """Mechanically enforce that the producer of evidence cannot be the verifier of that evidence."""
        m_id = maker_prov.get("agent_id") if isinstance(maker_prov, dict) else maker_prov.agent_id
        c_id = checker_prov.get("agent_id") if isinstance(checker_prov, dict) else checker_prov.agent_id

        if not m_id:
            return False, "Evidence producer has no attributable agent_id"
        if not c_id:
            return False, "Evidence verifier has no attributable agent_id"
        if m_id == c_id:
            return False, f"Maker != Checker violation: Principal '{m_id}' cannot verify their own evidence"

        return True, f"Maker ({m_id}) != Checker ({c_id}) separation verified"
