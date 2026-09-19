"""Interface and protocol specifications for the Ship Lifecycle Engine."""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Protocol, Tuple

from .models import GateResult, GitInfo, ShipConfig, VerificationResult


class IVcsClient(Protocol):
    """Protocol for Version Control System interactions."""

    def run_cmd(self, args: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
        """Run a git command and return (exit_code, stdout, stderr)."""
        ...

    def get_output(self, args: List[str], cwd: Optional[Path] = None, default: str = "") -> str:
        """Run a git command and return stripped stdout or default."""
        ...

    def get_info(self, repo_path: Path) -> GitInfo:
        """Retrieve branch, commit SHA, dirty status, and commit count."""
        ...

    def compute_fingerprint(self, repo_path: Path, scope: str = ".") -> str:
        """Compute a deterministic hash fingerprint of tracked and untracked changes."""
        ...

    def attach_note(self, repo_path: Path, commit_ref: str, notes_ref: str, payload: Dict[str, Any]) -> bool:
        """Attach JSON payload to a commit via Git Notes."""
        ...

    def read_note(self, repo_path: Path, commit_ref: str, notes_ref: str) -> Optional[Dict[str, Any]]:
        """Read JSON payload from a commit via Git Notes."""
        ...


class ILedgerStore(Protocol):
    """Protocol for thread-safe state ledger persistence."""

    def get_ledger_path(self, repo_path: Path) -> Path:
        """Return the path to .agentflow/state.json."""
        ...

    @contextmanager
    def lock(self, repo_path: Path, timeout: float = 10.0) -> Iterator[None]:
        """Context manager acquiring an exclusive file lock on the ledger."""
        ...

    def load(self, repo_path: Path) -> Dict[str, Any]:
        """Load ledger state, creating a default one if missing."""
        ...

    def save(self, repo_path: Path, ledger: Dict[str, Any]) -> None:
        """Atomically persist ledger state to disk."""
        ...

    def mutate_change(
        self,
        repo_path: Path,
        change_id: str,
        mutator_fn: Callable[[Dict[str, Any]], None],
    ) -> Dict[str, Any]:
        """Perform thread-safe atomic mutation of a specific change entry."""
        ...

    def get_active_change(self, repo_path: Path) -> Optional[str]:
        """Get currently active change ID."""
        ...

    def set_active_change(self, repo_path: Path, change_id: str) -> Dict[str, Any]:
        """Set active change ID in ledger."""
        ...

    def clear_active_change(self, repo_path: Path) -> Dict[str, Any]:
        """Clear active change ID in ledger."""
        ...


class ISpecRepository(Protocol):
    """Protocol for discovering and synchronizing specifications and ADRs."""

    def inspect_adrs(self, repo_path: Path) -> List[Dict[str, Any]]:
        """Find and parse Architecture Decision Records."""
        ...

    def inspect_openspec(self, repo_path: Path, target_change: Optional[str] = None) -> Dict[str, Any]:
        """Inspect active OpenSpec changes."""
        ...

    def inspect_archived_openspec(self, repo_path: Path) -> List[Dict[str, Any]]:
        """Inspect archived OpenSpec packages."""
        ...

    def inspect_living_specs(self, repo_path: Path) -> List[Dict[str, Any]]:
        """Inspect living specifications."""
        ...

    def merge_spec_requirements(self, living_text: str, delta_text: str) -> str:
        """Merge delta spec requirements into living specifications."""
        ...

    def archive_change(
        self,
        repo_path: Path,
        change: Optional[str] = None,
        force: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Promote active OpenSpec change to living truth and archive it."""
        ...


class IEvidenceVerifier(Protocol):
    """Protocol for evidence verifiers."""

    def verify(self, repo_path: Path, change_data: Dict[str, Any]) -> VerificationResult:
        """Verify evidence for a specific lifecycle aspect."""
        ...


class IGateEvaluator(Protocol):
    """Protocol for phase gate evaluators."""

    @property
    def gate_name(self) -> str:
        """Canonical gate identifier."""
        ...

    def evaluate(
        self,
        repo_path: Path,
        config: ShipConfig,
        ledger: Dict[str, Any],
        active_change: Dict[str, Any],
    ) -> GateResult:
        """Evaluate gate requirements and return GateResult."""
        ...
