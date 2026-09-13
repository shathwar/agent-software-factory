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


class GateStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


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
