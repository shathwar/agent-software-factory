"""Execution Event Log (Forensic Audit Trail) with Cryptographic Hash Chaining.

Authoritative state remains in .agentflow/ledger.json;
.agentflow/events.jsonl provides the tamper-evident chronological event stream
documenting every lifecycle action, identity transition, and governance decision.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .ledger import FileLedgerStore
from .models import EventType, ExecutionEvent
from .paths import get_event_log_file


GENESIS_PREV_HASH = "0" * 64


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_event_hash(event: ExecutionEvent) -> str:
    """Compute SHA-256 digest of an event's canonical string representation."""
    return hashlib.sha256(event.canonical_string().encode("utf-8")).hexdigest()


class EventLogger:
    """Append-only, tamper-evident execution event log manager."""

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()
        self.event_file = get_event_log_file(self.repo_root)

    def _ensure_dir(self) -> None:
        self.event_file.parent.mkdir(parents=True, exist_ok=True)

    def _get_last_event_info(self) -> Tuple[int, str]:
        """Return (event_count, last_event_hash)."""
        if not self.event_file.exists():
            return 0, GENESIS_PREV_HASH

        count = 0
        last_hash = GENESIS_PREV_HASH
        with self.event_file.open("r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                count += 1
                try:
                    data = json.loads(line_str)
                    last_hash = data.get("event_hash", last_hash)
                except Exception:
                    pass
        return count, last_hash

    def emit(
        self,
        event_type: Union[EventType, str],
        change_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        target: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        provenance: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
    ) -> ExecutionEvent:
        """Emit a cryptographically chained event to the execution log."""
        self._ensure_dir()
        et = event_type.value if hasattr(event_type, "value") else str(event_type)
        ts = timestamp or _now_iso()

        with FileLedgerStore.lock(self.repo_root):
            count, prev_hash = self._get_last_event_info()
            event_id = f"evt-{count + 1:06d}"

            event = ExecutionEvent(
                event_id=event_id,
                event_type=et,
                timestamp=ts,
                change_id=change_id,
                agent_id=agent_id,
                session_id=session_id,
                task_id=task_id,
                target=target,
                payload=payload or {},
                provenance=provenance or {},
                prev_event_hash=prev_hash,
                event_hash="",
            )
            event.event_hash = compute_event_hash(event)

            # Append JSON line
            with self.event_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), separators=(",", ":")) + "\n")

            return event

    def read_all(self) -> List[ExecutionEvent]:
        """Read all execution events from log."""
        if not self.event_file.exists():
            return []
        events: List[ExecutionEvent] = []
        with self.event_file.open("r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    events.append(ExecutionEvent.from_dict(json.loads(line_str)))
                except Exception:
                    pass
        return events

    def tail(
        self,
        n: int = 50,
        event_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        change_id: Optional[str] = None,
    ) -> List[ExecutionEvent]:
        """Return the most recent N matching events."""
        events = self.read_all()
        filtered = []
        for e in events:
            if event_type and e.event_type.upper() != event_type.upper():
                continue
            if agent_id and e.agent_id != agent_id:
                continue
            if change_id and e.change_id != change_id:
                continue
            filtered.append(e)
        return filtered[-n:]

    def query(
        self,
        change_id: Optional[str] = None,
        event_types: Optional[Union[List[str], str]] = None,
        event_type: Optional[Union[EventType, str]] = None,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[ExecutionEvent]:
        """Query execution events by filter criteria."""
        events = self.read_all()
        res = []
        if event_type:
            et_val = event_type.value if hasattr(event_type, "value") else str(event_type)
            types_set = {et_val.upper()}
        elif event_types:
            if isinstance(event_types, str):
                types_set = {event_types.upper()}
            else:
                types_set = {t.upper() for t in event_types}
        else:
            types_set = None

        for e in events:
            if change_id and e.change_id != change_id:
                continue
            if types_set and e.event_type.upper() not in types_set:
                continue
            if agent_id and e.agent_id != agent_id:
                continue
            if task_id and e.task_id != task_id:
                continue
            res.append(e)

        if limit is not None and limit > 0:
            res = res[-limit:]
        return res

    def verify_integrity(self) -> Tuple[bool, str, Optional[str]]:
        """Verify the cryptographic hash-chain integrity of the event stream.

        Returns:
            (valid, details_message, broken_event_id_or_none)
        """
        if not self.event_file.exists():
            return True, "No events log found (empty log is valid)", None

        expected_prev_hash = GENESIS_PREV_HASH
        idx = 0

        with self.event_file.open("r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                idx += 1
                try:
                    data = json.loads(line_str)
                    event = ExecutionEvent.from_dict(data)
                except Exception as exc:
                    return False, f"Malformed JSON line at index {idx}: {exc}", None

                # 1. Check prev_event_hash linkage
                if event.prev_event_hash != expected_prev_hash:
                    return (
                        False,
                        f"Hash chain broken at event '{event.event_id}' (index {idx}): expected prev_hash '{expected_prev_hash}', got '{event.prev_event_hash}'",
                        event.event_id,
                    )

                # 2. Recompute and verify event_hash
                computed_hash = compute_event_hash(event)
                if computed_hash != event.event_hash:
                    return (
                        False,
                        f"Tampered event payload at event '{event.event_id}' (index {idx}): computed '{computed_hash}', stored '{event.event_hash}'",
                        event.event_id,
                    )

                expected_prev_hash = event.event_hash

        return True, f"Cryptographic hash chain verified successfully ({idx} events)", None
