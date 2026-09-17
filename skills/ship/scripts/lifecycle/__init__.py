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
from .models import (
    GateResult, GateStatus, GitInfo, LifecyclePhase, OpenSpecInfo, ShipConfig, VerificationResult,
    TurnContract, TurnRecord,
)
from .ledger import FileLedgerStore, record_turn_to_ledger, get_turns_from_ledger
from .turns import get_next_turn_contract, format_turn_contract, format_turns_log
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
    "TurnContract",
    "TurnRecord",
    "VerificationResult",
    "canonicalize_gate_name",
    "determine_lifecycle_state",
    "format_summary",
    "format_turn_contract",
    "format_turns_log",
    "get_next_turn_contract",
    "get_turns_from_ledger",
    "inspect_review_reports",
    "inspect_spikes",
    "is_spike_completed",
    "is_test_evidence_passing",
    "merge_spec_requirements",
    "normalize_req_title",
    "parse_requirements_doc",
    "record_turn_to_ledger",
    "validate_delivery_readiness",
    "validate_judge_report_contract",
    "validate_review_approval",
]
