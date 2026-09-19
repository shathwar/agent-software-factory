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


class EventReplayer:
    """Deterministic state rebuilder from cryptographic execution event streams."""

    @staticmethod
    def replay(events: List[ExecutionEvent], target_change: Optional[str] = None) -> Dict[str, Any]:
        """Reconstruct authoritative change state deterministically from events."""
        reconstructed: Dict[str, Any] = {
            "version": 1,
            "active_change_id": target_change,
            "changes": {},
        }

        for e in events:
            cid = e.change_id or target_change or "default"
            if target_change and e.change_id and e.change_id != target_change:
                continue

            ch = reconstructed["changes"].setdefault(cid, {
                "phase": "INITIAL_PROPOSAL",
                "revision_counter": 1,
                "task_status": {},
                "evidence": {},
                "verification": {},
                "checkpoints": {},
                "blockers": [],
                "turns": [],
                "budget": {
                    "limits": {},
                    "consumed": {
                        "tokens": 0,
                        "model_calls": 0,
                        "turns": 0,
                        "time_seconds": 0.0,
                        "dollars": 0.0,
                        "tool_executions": 0,
                        "network_operations": 0,
                    },
                    "history": [],
                },
                "provenance": {"identities": {}, "sessions": {}},
                "capabilities": {},
                "approvals": {"requests": {}, "authorizations": {}},
                "coordination": {"leases": {}, "handoffs": []},
            })

            et = e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)
            payload = e.payload or {}

            # 1. Identity & Sessions
            if et == EventType.AGENT_STARTED.value:
                aid = e.agent_id or payload.get("agent_id")
                if aid:
                    ch["provenance"]["identities"][aid] = {
                        "agent_id": aid,
                        "role": payload.get("role", "worker"),
                        "registered_at": e.timestamp,
                    }
            elif et == EventType.SESSION_CREATED.value:
                sid = e.session_id or payload.get("session_id")
                aid = e.agent_id or payload.get("agent_id")
                if sid and aid:
                    ch["provenance"]["sessions"][sid] = {
                        "session_id": sid,
                        "agent_id": aid,
                        "created_at": e.timestamp,
                        "active": True,
                    }

            # 2. Coordination & Leases
            elif et in (EventType.TASK_CLAIMED.value, EventType.LEASE_GRANTED.value):
                tid = e.task_id or payload.get("task_id")
                if tid:
                    ch["coordination"]["leases"][tid] = {
                        "task_id": tid,
                        "owner_id": e.agent_id or payload.get("owner_id"),
                        "lease_token": payload.get("lease_token", f"token-{tid}"),
                        "status": "ACTIVE",
                        "acquired_at": e.timestamp,
                        "expires_at": payload.get("expires_at"),
                        "files": payload.get("files", []),
                    }
            elif et == EventType.LEASE_RELEASED.value:
                tid = e.task_id or payload.get("task_id")
                if tid and tid in ch["coordination"]["leases"]:
                    ch["coordination"]["leases"][tid]["status"] = "RELEASED"
            elif et == EventType.LEASE_EXPIRED.value:
                tid = e.task_id or payload.get("task_id")
                if tid and tid in ch["coordination"]["leases"]:
                    ch["coordination"]["leases"][tid]["status"] = "EXPIRED"

            # 3. Capabilities
            elif et == EventType.CAPABILITY_GRANTED.value:
                cap_id = payload.get("capability_id") or e.target
                if cap_id:
                    ch["capabilities"][cap_id] = {
                        "capability_id": cap_id,
                        "agent_id": e.agent_id,
                        "operation": payload.get("operation"),
                        "target": payload.get("target"),
                        "revoked": False,
                        "granted_at": e.timestamp,
                        "expires_at": payload.get("expires_at"),
                        "approval_ref": payload.get("approval_ref", ""),
                    }
            elif et == EventType.CAPABILITY_REVOKED.value:
                cap_id = payload.get("capability_id") or e.target
                if cap_id and cap_id in ch["capabilities"]:
                    ch["capabilities"][cap_id]["revoked"] = True

            # 4. Approvals
            elif et == EventType.APPROVAL_REQUESTED.value:
                req_id = payload.get("request_id") or e.target
                if req_id:
                    ch["approvals"]["requests"][req_id] = {
                        "request_id": req_id,
                        "agent_id": e.agent_id,
                        "action": payload.get("action"),
                        "scope": payload.get("scope"),
                        "status": "PENDING",
                        "requested_at": e.timestamp,
                    }
            elif et == EventType.APPROVAL_GRANTED.value:
                appr_id = payload.get("approval_id") or e.target
                req_id = payload.get("request_id")
                if req_id and req_id in ch["approvals"]["requests"]:
                    ch["approvals"]["requests"][req_id]["status"] = "APPROVED"
                if appr_id:
                    ch["approvals"]["authorizations"][appr_id] = {
                        "approval_id": appr_id,
                        "human": payload.get("human"),
                        "agent": e.agent_id or payload.get("agent"),
                        "action": payload.get("action"),
                        "scope": payload.get("scope"),
                        "expires_at": payload.get("expires_at"),
                        "status": "ACTIVE",
                    }
            elif et == EventType.APPROVAL_REVOKED.value:
                appr_id = payload.get("approval_id") or e.target
                if appr_id and appr_id in ch["approvals"]["authorizations"]:
                    ch["approvals"]["authorizations"][appr_id]["status"] = "REVOKED"

            # 5. Checkpoints
            elif et == EventType.CHECKPOINT_CREATED.value:
                gate = payload.get("gate") or e.target
                if gate:
                    ch["checkpoints"][gate] = {
                        "gate": gate,
                        "timestamp": e.timestamp,
                        "change": cid,
                        "ref": payload.get("ref"),
                    }

            # 6. Blockers & Halts
            elif et == EventType.HALT_TRIGGERED.value:
                reason = payload.get("reason", "Unknown halt")
                halt_str = f"Halt: {reason}"
                if halt_str not in ch["blockers"]:
                    ch["blockers"].append(halt_str)
            elif et == EventType.RESUME_TRIGGERED.value:
                ch["blockers"] = [b for b in ch["blockers"] if not b.startswith("Halt:")]

            # 7. Budget & Consumption
            elif et == EventType.BUDGET_UPDATED.value:
                limits = payload.get("limits", {})
                if limits:
                    ch["budget"]["limits"] = dict(limits)
            elif et == EventType.RESOURCE_CONSUMED.value:
                delta = payload.get("delta", {})
                con = ch["budget"]["consumed"]
                for k in ("tokens", "model_calls", "turns", "tool_executions", "network_operations"):
                    con[k] = con.get(k, 0) + int(delta.get(k, 0) or 0)
                for k in ("dollars", "time_seconds"):
                    con[k] = round(con.get(k, 0.0) + float(delta.get(k, 0.0) or 0.0), 4)
                ch["budget"]["history"].append({
                    "timestamp": e.timestamp,
                    "agent_id": e.agent_id,
                    "delta": delta,
                    "reason": payload.get("reason", ""),
                })

            # 8. Verifications
            elif et == EventType.VERIFICATION_PASSED.value:
                tier = payload.get("tier") or "execution"
                ch["verification"][tier] = {
                    "verdict": "VERIFIED",
                    "score": payload.get("score", 1.0),
                    "timestamp": e.timestamp,
                }
            elif et == EventType.VERIFICATION_FAILED.value:
                tier = payload.get("tier") or "execution"
                ch["verification"][tier] = {
                    "verdict": "NOT_VERIFIED",
                    "reason": payload.get("reason", ""),
                    "timestamp": e.timestamp,
                }

        return reconstructed

    @classmethod
    def verify_state_matches_events(
        cls,
        repo_root: Path,
        change_id: Optional[str] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Verify that authoritative ledger state matches reconstructed event state."""
        logger = EventLogger(repo_root)
        valid, msg, broken_id = logger.verify_integrity()
        if not valid:
            return False, f"Event log integrity broken: {msg}", {"broken_event_id": broken_id}

        events = logger.query(change_id=change_id)
        cid = change_id or (FileLedgerStore.load(repo_root).get("active_change_id") or "default")
        replayed = cls.replay(events, target_change=cid)

        actual_ledger = FileLedgerStore.load(repo_root)
        act_ch = actual_ledger.get("changes", {}).get(cid, {})
        rep_ch = replayed.get("changes", {}).get(cid, {})

        mismatches: Dict[str, Any] = {}

        # Compare blockers
        act_halts = sorted([b for b in act_ch.get("blockers", []) if b.startswith("Halt:")])
        rep_halts = sorted([b for b in rep_ch.get("blockers", []) if b.startswith("Halt:")])
        if act_halts != rep_halts:
            mismatches["halt_blockers"] = {"actual": act_halts, "replayed": rep_halts}

        # Compare consumption totals
        act_con = act_ch.get("budget", {}).get("consumed", {})
        rep_con = rep_ch.get("budget", {}).get("consumed", {})
        for k in ("tokens", "model_calls", "dollars", "tool_executions", "network_operations"):
            if act_con.get(k) != rep_con.get(k):
                mismatches[f"budget_{k}"] = {"actual": act_con.get(k), "replayed": rep_con.get(k)}

        # Compare active leases
        act_leases = {k: v.get("status") for k, v in act_ch.get("coordination", {}).get("leases", {}).items()}
        rep_leases = {k: v.get("status") for k, v in rep_ch.get("coordination", {}).get("leases", {}).items()}
        if act_leases != rep_leases:
            mismatches["leases"] = {"actual": act_leases, "replayed": rep_leases}

        if mismatches:
            return False, f"Ledger state diverges from event stream in {len(mismatches)} section(s)", mismatches

        return True, f"Replay verified: ledger state for '{cid}' perfectly matches event stream ({len(events)} events)", {}
