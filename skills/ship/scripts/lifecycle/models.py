"""Domain models, dataclasses, and enums for the Ship Lifecycle Engine."""

from dataclasses import dataclass, field
from enum import Enum
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

    def to_dict(self) -> Dict[str, Any]:
        return {
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "skill": self.skill,
            "timestamp": self.timestamp,
            "harness": self.harness,
            "execution_mode": self.execution_mode,
            "inputs": self.inputs,
            "evidence": self.evidence,
            "state_delta": self.state_delta,
        }


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
        return {
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
        }

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
        return {
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
        }

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
        )


