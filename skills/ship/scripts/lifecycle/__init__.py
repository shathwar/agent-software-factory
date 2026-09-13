"""Ship Lifecycle Engine Package."""

from .checkpoints import CheckpointManager
from .config import ShipConfigManager
from .engine import LifecycleEngine, format_summary
from .evidence import (
    inspect_review_reports,
    inspect_spikes,
    is_spike_completed,
    is_test_evidence_passing,
    validate_judge_report_contract,
    validate_review_approval,
)
from .gates import determine_lifecycle_state, validate_delivery_readiness
from .ledger import FileLedgerStore
from .models import GateResult, GateStatus, GitInfo, LifecyclePhase, OpenSpecInfo, ShipConfig, VerificationResult
from .specs import OpenSpecRepository, merge_spec_requirements, normalize_req_title, parse_requirements_doc
from .trailers import CommitTrailerGenerator, canonicalize_gate_name
from .vcs import GIT_NOTES_REF, GitClient

__all__ = [
    "CheckpointManager",
    "CommitTrailerGenerator",
    "FileLedgerStore",
    "GIT_NOTES_REF",
    "GateResult",
    "GateStatus",
    "GitClient",
    "GitInfo",
    "LifecycleEngine",
    "LifecyclePhase",
    "OpenSpecInfo",
    "OpenSpecRepository",
    "ShipConfig",
    "ShipConfigManager",
    "VerificationResult",
    "canonicalize_gate_name",
    "determine_lifecycle_state",
    "format_summary",
    "inspect_review_reports",
    "inspect_spikes",
    "is_spike_completed",
    "is_test_evidence_passing",
    "merge_spec_requirements",
    "normalize_req_title",
    "parse_requirements_doc",
    "validate_delivery_readiness",
    "validate_judge_report_contract",
    "validate_review_approval",
]
