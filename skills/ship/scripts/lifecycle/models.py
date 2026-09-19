"""Domain models, dataclasses, and enums for the Ship Lifecycle Engine."""

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class LifecyclePhase(str, Enum):
    INITIAL_PROPOSAL = "INITIAL_PROPOSAL"
    FRONTIER_ROUNDS = "FRONTIER_ROUNDS"
    SPEC_CONFIRMED = "SPEC_CONFIRMED"
    SPIKE_ACTIVE = "SPIKE_ACTIVE"
    TDD_ACTIVE = "TDD_ACTIVE"
    REVIEW_ACTIVE = "REVIEW_ACTIVE"
    DELIVERY_READY = "DELIVERY_READY"
    ARCHIVED = "ARCHIVED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    AUTONOMY_HALTED = "AUTONOMY_HALTED"


class GateStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    AUTONOMY_HALTED = "AUTONOMY_HALTED"


class VerificationTier(str, Enum):
    STRUCTURAL = "structural"
    GROUNDING = "grounding"
    EXECUTION = "execution"
    MUTATION = "mutation"
    COVERAGE = "coverage"


class StagnationType(str, Enum):
    SAME_EVIDENCE = "SAME_EVIDENCE"
    SAME_FINDING = "SAME_FINDING"
    SAME_PATCH = "SAME_PATCH"
    SAME_VERIFIER_FAILURE = "SAME_VERIFIER_FAILURE"
    OSCILLATING_STATE = "OSCILLATING_STATE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


@dataclass
class GitInfo:
    branch: str = "unknown"
    commit_sha: str = "unknown"
    is_dirty: bool = False
    commit_count: int = 0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "is_dirty": self.is_dirty,
            "commit_count": self.commit_count,
            "error": self.error,
        }


@dataclass
class ShipConfig:
    version: str = "1.0"
    project_name: str = ""
    scope: str = "."
    debt_thresholds: Dict[str, Any] = field(default_factory=lambda: {
        "max_todos": 10,
        "max_fixmes": 0,
        "max_hacks": 0,
        "max_complexity": 15,
    })
    gates: List[Dict[str, Any]] = field(default_factory=lambda: [
        {"name": "design", "required": True},
        {"name": "spike", "required": False},
        {"name": "implementation", "required": True},
        {"name": "simplify", "required": True},
        {"name": "review", "required": True},
        {"name": "delivery", "required": True},
    ])
    custom_settings: Dict[str, Any] = field(default_factory=dict)
    path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "project_name": self.project_name,
            "scope": self.scope,
            "debt_thresholds": self.debt_thresholds,
            "gates": self.gates,
            "custom_settings": self.custom_settings,
        }


@dataclass
class VerificationResult:
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)


@dataclass
class VerificationRecord:
    """Independent verification record for a claim-evidence pair."""
    claim: str
    gate: str
    tier: str
    verdict: str  # "VERIFIED" | "NOT_VERIFIED" | "INCONCLUSIVE" | "SKIPPED"
    method: str
    findings: List[str] = field(default_factory=list)
    score: Optional[float] = None
    timestamp: str = ""
    verifier_id: str = "agentflow-verifier"
    metadata: Dict[str, Any] = field(default_factory=dict)
    provenance: Optional[Any] = None
    target_provenance: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "claim": self.claim,
            "gate": self.gate,
            "tier": self.tier,
            "verdict": self.verdict,
            "method": self.method,
            "findings": self.findings,
            "score": self.score,
            "timestamp": self.timestamp,
            "verifier_id": self.verifier_id,
            "metadata": self.metadata,
        }
        if self.provenance:
            res["provenance"] = self.provenance.to_dict() if hasattr(self.provenance, "to_dict") else self.provenance
        if self.target_provenance:
            res["target_provenance"] = self.target_provenance.to_dict() if hasattr(self.target_provenance, "to_dict") else self.target_provenance
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationRecord":
        return cls(
            claim=str(data.get("claim", "")),
            gate=str(data.get("gate", "")),
            tier=str(data.get("tier", "")),
            verdict=str(data.get("verdict", "")),
            method=str(data.get("method", "")),
            findings=list(data.get("findings", [])),
            score=data.get("score"),
            timestamp=str(data.get("timestamp", "")),
            verifier_id=str(data.get("verifier_id", "agentflow-verifier")),
            metadata=dict(data.get("metadata", {})),
            provenance=data.get("provenance"),
            target_provenance=data.get("target_provenance"),
        )


@dataclass
class GateResult:
    status: GateStatus
    details: Dict[str, Any] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)


@dataclass
class OpenSpecInfo:
    change_name: str
    exists: bool = False
    proposal_exists: bool = False
    specs_count: int = 0
    tasks_count: int = 0
    tasks_completed: int = 0
    all_tasks_complete: bool = False
    specs: List[Dict[str, Any]] = field(default_factory=list)
    path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_name": self.change_name,
            "exists": self.exists,
            "proposal_exists": self.proposal_exists,
            "specs_count": self.specs_count,
            "tasks_count": self.tasks_count,
            "tasks_completed": self.tasks_completed,
            "all_tasks_complete": self.all_tasks_complete,
            "specs": self.specs,
        }


@dataclass
class TurnContract:
    change_id: str
    phase: str
    skill: str
    role: str
    execution_mode: str = "sequential"
    inputs: Dict[str, Any] = field(default_factory=dict)
    hard_constraints: List[str] = field(default_factory=list)
    exit_criteria: List[str] = field(default_factory=list)
    output_evidence: str = ""
    action_prompt: str = ""
    suggested_command: Optional[str] = None
    suggested_mcp_tool: Optional[str] = None
    suggested_mcp_args: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_id": self.change_id,
            "phase": self.phase,
            "skill": self.skill,
            "role": self.role,
            "execution_mode": self.execution_mode,
            "inputs": self.inputs,
            "hard_constraints": self.hard_constraints,
            "exit_criteria": self.exit_criteria,
            "output_evidence": self.output_evidence,
            "action_prompt": self.action_prompt,
            "suggested_command": self.suggested_command,
            "suggested_mcp_tool": self.suggested_mcp_tool,
            "suggested_mcp_args": self.suggested_mcp_args,
        }


class AgentRole(str, Enum):
    ARCHITECT = "ARCHITECT"
    TECH_LEAD = "TECH_LEAD"
    MAKER = "MAKER"
    CHECKER = "CHECKER"
    VERIFIER = "VERIFIER"
    REMEDIATOR = "REMEDIATOR"
    SUPERVISOR = "SUPERVISOR"
    COORDINATOR = "COORDINATOR"
    SPECIALIST = "SPECIALIST"


@dataclass
class AgentIdentity:
    agent_id: str
    role: str = AgentRole.SPECIALIST.value
    runtime: str = "antigravity"
    model: str = "unknown"
    parent_agent_id: Optional[str] = None
    created_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role.value if hasattr(self.role, "value") else str(self.role),
            "runtime": self.runtime,
            "model": self.model,
            "parent_agent_id": self.parent_agent_id,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentIdentity":
        return cls(
            agent_id=str(data.get("agent_id", "")),
            role=str(data.get("role", AgentRole.SPECIALIST.value)),
            runtime=str(data.get("runtime", "antigravity")),
            model=str(data.get("model", "unknown")),
            parent_agent_id=data.get("parent_agent_id"),
            created_at=str(data.get("created_at", "")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class AgentSession:
    session_id: str
    agent_id: str
    change_id: str
    role: str = AgentRole.SPECIALIST.value
    started_at: str = ""
    ended_at: Optional[str] = None
    agentflow_version: str = "1.0.0"
    skill: str = ""
    skill_version: str = "1.0.0"
    runtime: str = "antigravity"
    model: str = "unknown"
    status: str = "ACTIVE"
    parent_session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "change_id": self.change_id,
            "role": self.role.value if hasattr(self.role, "value") else str(self.role),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "agentflow_version": self.agentflow_version,
            "skill": self.skill,
            "skill_version": self.skill_version,
            "runtime": self.runtime,
            "model": self.model,
            "status": self.status,
            "parent_session_id": self.parent_session_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSession":
        return cls(
            session_id=str(data.get("session_id", "")),
            agent_id=str(data.get("agent_id", "")),
            change_id=str(data.get("change_id", "")),
            role=str(data.get("role", AgentRole.SPECIALIST.value)),
            started_at=str(data.get("started_at", "")),
            ended_at=data.get("ended_at"),
            agentflow_version=str(data.get("agentflow_version", "1.0.0")),
            skill=str(data.get("skill", "")),
            skill_version=str(data.get("skill_version", "1.0.0")),
            runtime=str(data.get("runtime", "antigravity")),
            model=str(data.get("model", "unknown")),
            status=str(data.get("status", "ACTIVE")),
            parent_session_id=data.get("parent_session_id"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ActionProvenance:
    action_id: str
    action_name: str
    agent_id: str
    session_id: str
    change_id: str
    role: str = AgentRole.SPECIALIST.value
    task_id: Optional[str] = None
    lease_token: Optional[str] = None
    timestamp: str = ""
    runtime: str = "antigravity"
    model: str = "unknown"
    skill: str = ""
    skill_version: str = "1.0.0"
    agentflow_version: str = "1.0.0"
    parent_agent_id: Optional[str] = None
    inputs_digest: str = ""
    evidence_digest: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_name": self.action_name,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "change_id": self.change_id,
            "role": self.role.value if hasattr(self.role, "value") else str(self.role),
            "task_id": self.task_id,
            "lease_token": self.lease_token,
            "timestamp": self.timestamp,
            "runtime": self.runtime,
            "model": self.model,
            "skill": self.skill,
            "skill_version": self.skill_version,
            "agentflow_version": self.agentflow_version,
            "parent_agent_id": self.parent_agent_id,
            "inputs_digest": self.inputs_digest,
            "evidence_digest": self.evidence_digest,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionProvenance":
        return cls(
            action_id=str(data.get("action_id", "")),
            action_name=str(data.get("action_name", "")),
            agent_id=str(data.get("agent_id", "")),
            session_id=str(data.get("session_id", "")),
            change_id=str(data.get("change_id", "")),
            role=str(data.get("role", AgentRole.SPECIALIST.value)),
            task_id=data.get("task_id"),
            lease_token=data.get("lease_token"),
            timestamp=str(data.get("timestamp", "")),
            runtime=str(data.get("runtime", "antigravity")),
            model=str(data.get("model", "unknown")),
            skill=str(data.get("skill", "")),
            skill_version=str(data.get("skill_version", "1.0.0")),
            agentflow_version=str(data.get("agentflow_version", "1.0.0")),
            parent_agent_id=data.get("parent_agent_id"),
            inputs_digest=str(data.get("inputs_digest", "")),
            evidence_digest=str(data.get("evidence_digest", "")),
            metadata=dict(data.get("metadata", {})),
        )


class CapabilityOperation(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"
    GIT = "GIT"
    NETWORK = "NETWORK"
    NETWORK_READ = "NETWORK_READ"
    NETWORK_WRITE = "NETWORK_WRITE"
    SECRET_READ = "SECRET_READ"
    CLOUD_MUTATE = "CLOUD_MUTATE"
    GITHUB_WRITE = "GITHUB_WRITE"


class ExecutionRing(str, Enum):
    RING_0_HYPERVISOR = "RING_0_HYPERVISOR"
    RING_1_GOVERNANCE = "RING_1_GOVERNANCE"
    RING_2_PRODUCTION = "RING_2_PRODUCTION"
    RING_3_WORKSPACE = "RING_3_WORKSPACE"


@dataclass
class Capability:
    capability_id: str
    agent_id: str
    change_id: str
    operation: str
    target: str
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    granted_at: str = ""
    expires_at: Optional[str] = None
    approval_ref: str = ""
    revoked: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "agent_id": self.agent_id,
            "change_id": self.change_id,
            "operation": self.operation.value if hasattr(self.operation, "value") else str(self.operation),
            "target": self.target,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "granted_at": self.granted_at,
            "expires_at": self.expires_at,
            "approval_ref": self.approval_ref,
            "revoked": self.revoked,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Capability":
        return cls(
            capability_id=str(data.get("capability_id", "")),
            agent_id=str(data.get("agent_id", "")),
            change_id=str(data.get("change_id", "")),
            operation=str(data.get("operation", CapabilityOperation.READ.value)),
            target=str(data.get("target", "*")),
            task_id=data.get("task_id"),
            session_id=data.get("session_id"),
            granted_at=str(data.get("granted_at", "")),
            expires_at=data.get("expires_at"),
            approval_ref=str(data.get("approval_ref", "")),
            revoked=bool(data.get("revoked", False)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class AccessDecision:
    allowed: bool
    reason: str
    ring: str
    agent_id: str
    operation: str
    target: str
    capability_id: Optional[str] = None
    violation_code: Optional[str] = None
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "ring": self.ring,
            "agent_id": self.agent_id,
            "operation": self.operation,
            "target": self.target,
            "capability_id": self.capability_id,
            "violation_code": self.violation_code,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccessDecision":
        return cls(
            allowed=bool(data.get("allowed", False)),
            reason=str(data.get("reason", "")),
            ring=str(data.get("ring", "")),
            agent_id=str(data.get("agent_id", "")),
            operation=str(data.get("operation", "")),
            target=str(data.get("target", "")),
            capability_id=data.get("capability_id"),
            violation_code=data.get("violation_code"),
            timestamp=str(data.get("timestamp", "")),
        )


@dataclass
class DurableApproval:
    approval_id: str
    human: str
    agent: str
    change: str
    action: str
    scope: str
    issued_at: str
    expires_at: Optional[str] = None
    reason: str = ""
    revoked: bool = False
    signature: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "human": self.human,
            "agent": self.agent,
            "change": self.change,
            "action": self.action,
            "scope": self.scope,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "reason": self.reason,
            "revoked": self.revoked,
            "signature": self.signature,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DurableApproval":
        return cls(
            approval_id=str(data.get("approval_id", "")),
            human=str(data.get("human", "")),
            agent=str(data.get("agent", "")),
            change=str(data.get("change", "")),
            action=str(data.get("action", "")),
            scope=str(data.get("scope", "*")),
            issued_at=str(data.get("issued_at", "")),
            expires_at=data.get("expires_at"),
            reason=str(data.get("reason", "")),
            revoked=bool(data.get("revoked", False)),
            signature=str(data.get("signature", "")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ApprovalRequest:
    request_id: str
    agent: str
    change: str
    action: str
    scope: str
    reason: str
    requested_at: str
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED, EXPIRED
    approval_id: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "agent": self.agent,
            "change": self.change,
            "action": self.action,
            "scope": self.scope,
            "reason": self.reason,
            "requested_at": self.requested_at,
            "status": self.status,
            "approval_id": self.approval_id,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "rejection_reason": self.rejection_reason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalRequest":
        return cls(
            request_id=str(data.get("request_id", "")),
            agent=str(data.get("agent", "")),
            change=str(data.get("change", "")),
            action=str(data.get("action", "")),
            scope=str(data.get("scope", "*")),
            reason=str(data.get("reason", "")),
            requested_at=str(data.get("requested_at", "")),
            status=str(data.get("status", "PENDING")),
            approval_id=data.get("approval_id"),
            reviewed_by=data.get("reviewed_by"),
            reviewed_at=data.get("reviewed_at"),
            rejection_reason=data.get("rejection_reason"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class TurnRecord:
    turn_id: str
    skill: str
    timestamp: str = ""
    harness: str = "generic"
    execution_mode: str = "sequential"
    inputs: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    state_delta: Dict[str, Any] = field(default_factory=dict)
    provenance: Optional[Any] = None
    session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "turn_id": self.turn_id,
            "skill": self.skill,
            "timestamp": self.timestamp,
            "harness": self.harness,
            "execution_mode": self.execution_mode,
            "inputs": self.inputs,
            "evidence": self.evidence,
            "state_delta": self.state_delta,
            "session_id": self.session_id,
        }
        if self.provenance:
            res["provenance"] = self.provenance.to_dict() if hasattr(self.provenance, "to_dict") else self.provenance
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TurnRecord":
        return cls(
            turn_id=str(data.get("turn_id", "")),
            skill=str(data.get("skill", "")),
            timestamp=str(data.get("timestamp", "")),
            harness=str(data.get("harness", "generic")),
            execution_mode=str(data.get("execution_mode", "sequential")),
            inputs=dict(data.get("inputs", {})),
            evidence=dict(data.get("evidence", {})),
            state_delta=dict(data.get("state_delta", {})),
            provenance=data.get("provenance"),
            session_id=data.get("session_id"),
        )


class LeaseStatus(str, Enum):
    ACQUIRED = "ACQUIRED"
    ACTIVE = "ACTIVE"
    RENEWED = "RENEWED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    PREEMPTED = "PREEMPTED"
    HANDED_OFF = "HANDED_OFF"


class CoordinationConflictType(str, Enum):
    CONCURRENT_LEASE = "CONCURRENT_LEASE"
    FILE_OVERLAP = "FILE_OVERLAP"
    SPEC_COLLISION = "SPEC_COLLISION"
    STALE_REVISION = "STALE_REVISION"


@dataclass
class TaskLease:
    task_id: str
    owner_id: str
    lease_token: str
    claimed_at: str = ""
    expires_at: str = ""
    heartbeat_at: str = ""
    ttl_seconds: int = 600
    target_files: List[str] = field(default_factory=list)
    status: Any = "ACTIVE"
    metadata: Dict[str, Any] = field(default_factory=dict)
    change_id: Optional[str] = None
    files: Optional[List[str]] = None
    acquired_at: Optional[str] = None
    session_id: Optional[str] = None
    provenance: Optional[Any] = None

    def __post_init__(self):
        if self.acquired_at and not self.claimed_at:
            self.claimed_at = self.acquired_at
        elif not self.acquired_at and self.claimed_at:
            self.acquired_at = self.claimed_at
        if self.files is not None and not self.target_files:
            self.target_files = list(self.files)
        elif self.files is None and self.target_files:
            self.files = list(self.target_files)
        if not self.heartbeat_at and self.claimed_at:
            self.heartbeat_at = self.claimed_at

    def to_dict(self) -> Dict[str, Any]:
        st = self.status.value if hasattr(self.status, "value") else str(self.status)
        res = {
            "task_id": self.task_id,
            "owner_id": self.owner_id,
            "lease_token": self.lease_token,
            "claimed_at": self.claimed_at,
            "expires_at": self.expires_at,
            "heartbeat_at": self.heartbeat_at,
            "ttl_seconds": self.ttl_seconds,
            "target_files": self.target_files,
            "files": self.files or self.target_files,
            "status": st,
            "metadata": self.metadata,
            "change_id": self.change_id,
            "session_id": self.session_id,
        }
        if self.provenance:
            res["provenance"] = self.provenance.to_dict() if hasattr(self.provenance, "to_dict") else self.provenance
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskLease":
        raw_status = data.get("status", "ACTIVE")
        st_val = raw_status.value if hasattr(raw_status, "value") else str(raw_status)
        return cls(
            task_id=str(data.get("task_id", "")),
            owner_id=str(data.get("owner_id", "")),
            lease_token=str(data.get("lease_token", "")),
            claimed_at=str(data.get("claimed_at") or data.get("acquired_at") or ""),
            expires_at=str(data.get("expires_at", "")),
            heartbeat_at=str(data.get("heartbeat_at", "")),
            ttl_seconds=int(data.get("ttl_seconds", 600)),
            target_files=list(data.get("target_files") or data.get("files") or []),
            status=st_val,
            metadata=dict(data.get("metadata", {})),
            change_id=data.get("change_id"),
            session_id=data.get("session_id"),
            provenance=data.get("provenance"),
        )


@dataclass
class TaskHandoff:
    task_id: str
    from_owner: str
    to_owner: str
    old_token: str = ""
    new_token: str = ""
    timestamp: str = ""
    reason: str = ""
    artifacts: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    handed_off_at: Optional[str] = None
    verification_checklist: List[str] = field(default_factory=list)
    notes: str = ""
    session_id: Optional[str] = None
    from_provenance: Optional[Any] = None
    to_provenance: Optional[Any] = None

    def __post_init__(self):
        if self.handed_off_at and not self.timestamp:
            self.timestamp = self.handed_off_at
        elif not self.handed_off_at and self.timestamp:
            self.handed_off_at = self.timestamp
        if self.notes and not self.reason:
            self.reason = self.notes
        elif not self.notes and self.reason:
            self.notes = self.reason

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "task_id": self.task_id,
            "from_owner": self.from_owner,
            "to_owner": self.to_owner,
            "old_token": self.old_token,
            "new_token": self.new_token,
            "timestamp": self.timestamp,
            "handed_off_at": self.handed_off_at or self.timestamp,
            "reason": self.reason,
            "notes": self.notes or self.reason,
            "artifacts": self.artifacts,
            "verification_checklist": self.verification_checklist,
            "metadata": self.metadata,
            "session_id": self.session_id,
        }
        if self.from_provenance:
            res["from_provenance"] = self.from_provenance.to_dict() if hasattr(self.from_provenance, "to_dict") else self.from_provenance
        if self.to_provenance:
            res["to_provenance"] = self.to_provenance.to_dict() if hasattr(self.to_provenance, "to_dict") else self.to_provenance
        return res

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskHandoff":
        return cls(
            task_id=str(data.get("task_id", "")),
            from_owner=str(data.get("from_owner", "")),
            to_owner=str(data.get("to_owner", "")),
            old_token=str(data.get("old_token", "")),
            new_token=str(data.get("new_token", "")),
            timestamp=str(data.get("timestamp") or data.get("handed_off_at") or ""),
            reason=str(data.get("reason") or data.get("notes") or ""),
            artifacts=list(data.get("artifacts", [])),
            verification_checklist=list(data.get("verification_checklist", [])),
            metadata=dict(data.get("metadata", {})),
            session_id=data.get("session_id"),
            from_provenance=data.get("from_provenance"),
            to_provenance=data.get("to_provenance"),
        )


class RecoveryStrategy(str, Enum):
    RESUME = "RESUME"
    ROLLBACK = "ROLLBACK"
    RECONCILE = "RECONCILE"
    ABORT = "ABORT"


@dataclass
class RecoveryDecision:
    strategy: str  # RecoveryStrategy
    change_id: str
    reconciled_items: List[str] = field(default_factory=list)
    restored_phase: str = ""
    next_step: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        st = self.strategy.value if hasattr(self.strategy, "value") else str(self.strategy)
        return {
            "strategy": st,
            "change_id": self.change_id,
            "reconciled_items": self.reconciled_items,
            "restored_phase": self.restored_phase,
            "next_step": self.next_step,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class EventType(str, Enum):
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_STOPPED = "AGENT_STOPPED"
    TASK_CLAIMED = "TASK_CLAIMED"
    LEASE_GRANTED = "LEASE_GRANTED"
    LEASE_RELEASED = "LEASE_RELEASED"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    ACTION_REQUESTED = "ACTION_REQUESTED"
    ACTION_ALLOWED = "ACTION_ALLOWED"
    ACTION_DENIED = "ACTION_DENIED"
    FILE_MODIFIED = "FILE_MODIFIED"
    TEST_EXECUTED = "TEST_EXECUTED"
    EVIDENCE_CREATED = "EVIDENCE_CREATED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    REMEDIATION_STARTED = "REMEDIATION_STARTED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_REVOKED = "APPROVAL_REVOKED"
    CAPABILITY_GRANTED = "CAPABILITY_GRANTED"
    CAPABILITY_REVOKED = "CAPABILITY_REVOKED"
    GATE_EVALUATED = "GATE_EVALUATED"
    CHECKPOINT_CREATED = "CHECKPOINT_CREATED"
    HALT_TRIGGERED = "HALT_TRIGGERED"
    RESUME_TRIGGERED = "RESUME_TRIGGERED"


@dataclass
class ExecutionEvent:
    event_id: str
    event_type: str
    timestamp: str
    change_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    target: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    prev_event_hash: Optional[str] = None
    event_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        et = self.event_type.value if hasattr(self.event_type, "value") else str(self.event_type)
        return {
            "event_id": self.event_id,
            "event_type": et,
            "timestamp": self.timestamp,
            "change_id": self.change_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "target": self.target,
            "payload": self.payload,
            "provenance": self.provenance,
            "prev_event_hash": self.prev_event_hash,
            "event_hash": self.event_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionEvent":
        return cls(
            event_id=str(data.get("event_id", "")),
            event_type=str(data.get("event_type", "")),
            timestamp=str(data.get("timestamp", "")),
            change_id=data.get("change_id"),
            agent_id=data.get("agent_id"),
            session_id=data.get("session_id"),
            task_id=data.get("task_id"),
            target=data.get("target"),
            payload=dict(data.get("payload", {})),
            provenance=dict(data.get("provenance", {})),
            prev_event_hash=data.get("prev_event_hash"),
            event_hash=str(data.get("event_hash", "")),
        )

    def canonical_string(self) -> str:
        """Deterministic canonical representation for cryptographic hash chaining."""
        et = self.event_type.value if hasattr(self.event_type, "value") else str(self.event_type)
        payload_str = json.dumps(self.payload, sort_keys=True, separators=(",", ":"))
        prov_str = json.dumps(self.provenance, sort_keys=True, separators=(",", ":"))
        return (
            f"{self.event_id}|{et}|{self.timestamp}|{self.change_id}|"
            f"{self.agent_id or ''}|{self.session_id or ''}|{self.task_id or ''}|"
            f"{self.target or ''}|{payload_str}|{prov_str}|{self.prev_event_hash or ''}"
        )





