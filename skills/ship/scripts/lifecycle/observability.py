"""
observability.py – Real-Agent Observability & Immutable Execution Trace Engine.

Provides tamper-evident observation of what an agent ACTUALLY DID:
Agent
 ├─ tool calls
 ├─ file changes
 ├─ commands
 ├─ test results
 ├─ lifecycle transitions
 └─ timestamps/order

Enables mechanical causal proofs (e.g. "Test failed before production code changed")
rather than trusting the agent's prose narrative.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .events import GENESIS_PREV_HASH, compute_event_hash
from .models import EventType, ExecutionEvent
try:
    from ..tool_runtime import classify_file
except ImportError:  # Standalone copied skill distribution.
    from tool_runtime import classify_file


def is_test_file(path):
    return classify_file(str(path))["is_test"]


def is_production_code(path):
    return classify_file(str(path))["is_production"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Structured Observation Records
# ---------------------------------------------------------------------------

@dataclass
class ToolCallRecord:
    name: str
    arguments: Dict[str, Any]
    call_id: str
    timestamp: str
    seq: int
    agent_id: Optional[str] = None


@dataclass
class ToolResultRecord:
    name: str
    call_id: str
    result: Any
    error: Optional[str]
    duration_ms: float
    timestamp: str
    seq: int


@dataclass
class FileChangeRecord:
    path: str
    change_type: str  # 'created', 'modified', 'deleted'
    before_hash: str
    after_hash: str
    diff: str
    is_test: bool
    is_production: bool
    timestamp: str
    seq: int


@dataclass
class CommandRecord:
    command: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timestamp: str
    seq: int
    is_test_run: bool = False


@dataclass
class TestResultRecord:
    framework: str  # 'pytest', 'unittest', 'jest', 'generic'
    command: str
    exit_code: int
    total_count: int
    passed_count: int
    failed_count: int
    failures: List[str]
    duration_ms: float
    timestamp: str
    seq: int

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and self.failed_count == 0


@dataclass
class LifecycleRecord:
    skill: str
    phase: str
    action: str
    state_delta: Dict[str, Any]
    timestamp: str
    seq: int


# ---------------------------------------------------------------------------
# Immutable-ish Execution Trace
# ---------------------------------------------------------------------------

class ExecutionTrace:
    """
    Append-only, cryptographically hash-chained execution trace for an AgentFlow run.
    Contains verifiable records of tool calls, file changes, commands, test results,
    and lifecycle transitions with monotonic sequencing and microsecond timestamps.
    """

    def __init__(self, run_id: str, events: Optional[List[ExecutionEvent]] = None) -> None:
        self.run_id = run_id
        self.events: List[ExecutionEvent] = list(events or [])

    def append_event(self, event: ExecutionEvent) -> None:
        self.events.append(event)

    def verify_integrity(self) -> Tuple[bool, str]:
        """
        Verify the SHA-256 hash chain of the entire trace from genesis.
        Returns (valid, details).
        """
        if not self.events:
            return True, "Empty trace is trivially valid"

        expected_prev = GENESIS_PREV_HASH
        for idx, event in enumerate(self.events):
            if event.prev_event_hash != expected_prev:
                return (
                    False,
                    f"Hash chain broken at index {idx} ({event.event_id}): expected prev '{expected_prev}', got '{event.prev_event_hash}'",
                )
            computed = compute_event_hash(event)
            if computed != event.event_hash:
                return (
                    False,
                    f"Tampered payload at index {idx} ({event.event_id}): computed '{computed}', stored '{event.event_hash}'",
                )
            expected_prev = event.event_hash

        return True, f"Execution trace integrity verified ({len(self.events)} events hash-chained)"

    # ------------------------------------------------------------------ #
    # Query Helpers                                                       #
    # ------------------------------------------------------------------ #

    def tool_calls(self) -> List[ToolCallRecord]:
        results = []
        for idx, e in enumerate(self.events):
            if e.event_type == EventType.TOOL_CALL.value:
                results.append(
                    ToolCallRecord(
                        name=str(e.payload.get("name", "")),
                        arguments=dict(e.payload.get("arguments", {})),
                        call_id=str(e.payload.get("call_id", e.event_id)),
                        timestamp=e.timestamp,
                        seq=idx,
                        agent_id=e.agent_id,
                    )
                )
        return results

    def file_changes(self) -> List[FileChangeRecord]:
        results = []
        for idx, e in enumerate(self.events):
            if e.event_type == EventType.FILE_MODIFIED.value:
                p = e.payload
                path_str = str(p.get("path", ""))
                results.append(
                    FileChangeRecord(
                        path=path_str,
                        change_type=str(p.get("change_type", "modified")),
                        before_hash=str(p.get("before_hash", "")),
                        after_hash=str(p.get("after_hash", "")),
                        diff=str(p.get("diff", "")),
                        is_test=bool(p.get("is_test", is_test_file(path_str))),
                        is_production=bool(p.get("is_production", is_production_code(path_str))),
                        timestamp=e.timestamp,
                        seq=idx,
                    )
                )
        return results

    def commands(self) -> List[CommandRecord]:
        results = []
        for idx, e in enumerate(self.events):
            if e.event_type == EventType.COMMAND_EXEC.value:
                p = e.payload
                results.append(
                    CommandRecord(
                        command=str(p.get("command", "")),
                        cwd=str(p.get("cwd", ".")),
                        exit_code=int(p.get("exit_code", 0)),
                        stdout=str(p.get("stdout", "")),
                        stderr=str(p.get("stderr", "")),
                        duration_ms=float(p.get("duration_ms", 0.0)),
                        timestamp=e.timestamp,
                        seq=idx,
                        is_test_run=bool(p.get("is_test_run", False)),
                    )
                )
        return results

    def test_results(self) -> List[TestResultRecord]:
        results = []
        for idx, e in enumerate(self.events):
            if e.event_type == EventType.TEST_EXECUTED.value:
                p = e.payload
                results.append(
                    TestResultRecord(
                        framework=str(p.get("framework", "generic")),
                        command=str(p.get("command", "")),
                        exit_code=int(p.get("exit_code", 0)),
                        total_count=int(p.get("total_count", 0)),
                        passed_count=int(p.get("passed_count", 0)),
                        failed_count=int(p.get("failed_count", 0)),
                        failures=list(p.get("failures", [])),
                        duration_ms=float(p.get("duration_ms", 0.0)),
                        timestamp=e.timestamp,
                        seq=idx,
                    )
                )
        return results

    def lifecycle_transitions(self) -> List[LifecycleRecord]:
        results = []
        for idx, e in enumerate(self.events):
            if e.event_type in (
                EventType.LIFECYCLE_TRANSITION.value,
                EventType.STEP_STARTED.value,
                EventType.STEP_COMPLETED.value,
            ):
                p = e.payload
                results.append(
                    LifecycleRecord(
                        skill=str(p.get("skill", "")),
                        phase=str(p.get("phase", p.get("status", ""))),
                        action=str(p.get("action", "")),
                        state_delta=dict(p.get("state_delta", {})),
                        timestamp=e.timestamp,
                        seq=idx,
                    )
                )
        return results

    def timeline(self) -> List[Dict[str, Any]]:
        """Return a chronological sequence of all events with human-readable summary."""
        items = []
        for idx, e in enumerate(self.events):
            summary = ""
            if e.event_type == EventType.TOOL_CALL.value:
                summary = f"Tool call: {e.payload.get('name')} {json.dumps(e.payload.get('arguments', {}))[:60]}"
            elif e.event_type == EventType.FILE_MODIFIED.value:
                kind = "test" if e.payload.get("is_test") else ("prod" if e.payload.get("is_production") else "other")
                summary = f"File {e.payload.get('change_type')}: {e.payload.get('path')} ({kind})"
            elif e.event_type == EventType.COMMAND_EXEC.value:
                summary = f"Command (exit {e.payload.get('exit_code')}): {e.payload.get('command')}"
            elif e.event_type == EventType.TEST_EXECUTED.value:
                status = "PASS" if e.payload.get("exit_code") == 0 else "FAIL"
                summary = f"Tests {status}: {e.payload.get('failed_count')} failed / {e.payload.get('total_count')} total"
            else:
                summary = f"{e.event_type}: {e.target or ''}"

            items.append({
                "seq": idx,
                "event_id": e.event_id,
                "event_type": e.event_type,
                "timestamp": e.timestamp,
                "summary": summary,
                "payload": e.payload,
            })
        return items

    # ------------------------------------------------------------------ #
    # Serialization                                                       #
    # ------------------------------------------------------------------ #

    def to_jsonl(self, file_path: Path) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("w", encoding="utf-8") as f:
            for event in self.events:
                f.write(json.dumps(event.to_dict(), separators=(",", ":")) + "\n")

    @classmethod
    def from_jsonl(cls, file_path: Path, run_id: Optional[str] = None) -> "ExecutionTrace":
        events: List[ExecutionEvent] = []
        if file_path.exists():
            with file_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if line_str:
                        events.append(ExecutionEvent.from_dict(json.loads(line_str)))
        rid = run_id or (events[0].change_id if events and events[0].change_id else "run-default")
        return cls(run_id=rid, events=events)


# ---------------------------------------------------------------------------
# Causal Trace Verifier (The Mechanical Proof Engine)
# ---------------------------------------------------------------------------

class CausalTraceVerifier:
    """
    Evaluates causal invariants on an ExecutionTrace without trusting agent narrative.
    Proves strict operational boundaries mechanically.
    """

    def __init__(self, trace: ExecutionTrace) -> None:
        self.trace = trace

    def prove_test_failed_before_production_code_changed(
        self,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        P0 INVARIANT: Prove that a test execution failed (Red Phase)
        BEFORE any production code file was created or modified.

        Returns (proven, explanation, evidence).
        """
        test_runs = self.trace.test_results()
        file_changes = self.trace.file_changes()

        # Find first failing test run
        first_test_failure: Optional[TestResultRecord] = None
        for tr in test_runs:
            if not tr.passed:
                first_test_failure = tr
                break

        # Fallback: check command executions with nonzero exit code running test commands
        if not first_test_failure:
            for cmd in self.trace.commands():
                if cmd.is_test_run and cmd.exit_code != 0:
                    first_test_failure = TestResultRecord(
                        framework="command",
                        command=cmd.command,
                        exit_code=cmd.exit_code,
                        total_count=1,
                        passed_count=0,
                        failed_count=1,
                        failures=[cmd.stderr or cmd.stdout],
                        duration_ms=cmd.duration_ms,
                        timestamp=cmd.timestamp,
                        seq=cmd.seq,
                    )
                    break

        # Find first production code change
        first_prod_change: Optional[FileChangeRecord] = None
        for fc in file_changes:
            if fc.is_production:
                first_prod_change = fc
                break

        # Case 1: No production code changed at all
        if not first_prod_change:
            if first_test_failure:
                return (
                    True,
                    "No production code changed; test failure observed in isolation",
                    {"first_test_failure": first_test_failure, "first_prod_change": None},
                )
            return (
                False,
                "Neither test failure nor production code modification was observed",
                {},
            )

        # Case 2: Production code changed, but no test failure ever ran
        if not first_test_failure:
            return (
                False,
                f"Iron Law violation: production file '{first_prod_change.path}' was modified "
                f"at seq {first_prod_change.seq} ({first_prod_change.timestamp}), but NO failing "
                "test execution was ever recorded in the execution trace.",
                {"first_prod_change": first_prod_change, "first_test_failure": None},
            )

        # Case 3: Compare sequence / timestamps
        if first_test_failure.seq >= first_prod_change.seq:
            return (
                False,
                f"Iron Law violation: production file '{first_prod_change.path}' was modified "
                f"at seq {first_prod_change.seq} ({first_prod_change.timestamp}) BEFORE "
                f"the first test failure occurred at seq {first_test_failure.seq} ({first_test_failure.timestamp}).",
                {
                    "first_prod_change": first_prod_change,
                    "first_test_failure": first_test_failure,
                    "order_violation": True,
                },
            )

        # Success: Red phase proved mechanically before production change
        return (
            True,
            f"Proved mechanically: Test failed at seq {first_test_failure.seq} "
            f"({first_test_failure.timestamp}) before production file '{first_prod_change.path}' "
            f"was modified at seq {first_prod_change.seq} ({first_prod_change.timestamp}).",
            {
                "first_test_failure": first_test_failure,
                "first_prod_change": first_prod_change,
                "seq_delta": first_prod_change.seq - first_test_failure.seq,
            },
        )

    def prove_red_green_cycle(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Prove complete TDD Red -> Green cycle:
        1. Test fails (Red) at t1
        2. Production code changes at t2 > t1
        3. Test passes (Green) at t3 > t2
        """
        red_proven, red_msg, red_ev = self.prove_test_failed_before_production_code_changed()
        if not red_proven:
            return False, f"Red phase not established: {red_msg}", red_ev

        first_prod = red_ev["first_prod_change"]
        if not first_prod:
            return False, "No production code modification was recorded", {}

        # Look for green test run after the production modification
        green_test: Optional[TestResultRecord] = None
        for tr in self.trace.test_results():
            if tr.passed and tr.seq > first_prod.seq:
                green_test = tr
                break

        if not green_test:
            for cmd in self.trace.commands():
                if cmd.is_test_run and cmd.exit_code == 0 and cmd.seq > first_prod.seq:
                    green_test = TestResultRecord(
                        framework="command",
                        command=cmd.command,
                        exit_code=0,
                        total_count=1,
                        passed_count=1,
                        failed_count=0,
                        failures=[],
                        duration_ms=cmd.duration_ms,
                        timestamp=cmd.timestamp,
                        seq=cmd.seq,
                    )
                    break

        if not green_test:
            return (
                False,
                f"Red phase and production edits were recorded, but no passing test (Green) was observed after seq {first_prod.seq}.",
                red_ev,
            )

        return (
            True,
            f"Proved Red-Green cycle: Test Red (seq {red_ev['first_test_failure'].seq}) -> "
            f"Prod Edit (seq {first_prod.seq}) -> Test Green (seq {green_test.seq})",
            {
                "red_test": red_ev["first_test_failure"],
                "prod_edit": first_prod,
                "green_test": green_test,
            },
        )

    def prove_no_file_changes_outside(self, allowed_patterns: List[str]) -> Tuple[bool, str]:
        """Verify that zero files were modified outside the permitted path regexes."""
        file_changes = self.trace.file_changes()
        compiled = [re.compile(p) for p in allowed_patterns]
        violations = []

        for fc in file_changes:
            if not any(cp.search(fc.path) for cp in compiled):
                violations.append(fc.path)

        if violations:
            return (
                False,
                f"Containment violation: unauthorized file mutations detected in {sorted(set(violations))}",
            )
        return True, f"All {len(file_changes)} file modifications conformed to allowed boundaries"

    def prove_no_test_weakening(self) -> Tuple[bool, str]:
        """Verify that no test edits deleted assertions or inserted skipping decorators."""
        test_changes = [fc for fc in self.trace.file_changes() if fc.is_test]
        violations = []

        weakening_patterns = [
            re.compile(r"^\+\s*@pytest\.mark\.skip", re.MULTILINE),
            re.compile(r"^\+\s*xit\(", re.MULTILINE),
            re.compile(r"^\+\s*it\.skip\(", re.MULTILINE),
            re.compile(r"^\+\s*@unittest\.skip", re.MULTILINE),
        ]

        for tc in test_changes:
            diff = tc.diff
            for pat in weakening_patterns:
                if pat.search(diff):
                    violations.append(f"{tc.path}: inserted skip decorator ({pat.pattern})")

            # Check if assertion lines were deleted without replacement
            deleted_asserts = len(re.findall(r"^-\s*assert\b", diff, re.MULTILINE))
            added_asserts = len(re.findall(r"^\+\s*assert\b", diff, re.MULTILINE))
            if deleted_asserts > 0 and added_asserts == 0:
                violations.append(f"{tc.path}: deleted {deleted_asserts} assertion(s) without replacement")

        if violations:
            return False, "Test weakening detected:\n" + "\n".join(f"  • {v}" for v in violations)
        return True, "No test weakening detected across test modifications"

    def prove_no_unauthorized_external_calls(self, forbidden_tools: Optional[List[str]] = None) -> Tuple[bool, str]:
        """Verify that no forbidden network tools or API commands were executed."""
        forbidden_set = set(forbidden_tools or ["gh_comment", "github_write", "curl", "send_request", "post_review"])
        violations = []

        for tc in self.trace.tool_calls():
            if tc.name in forbidden_set:
                violations.append(f"Tool call: {tc.name} at {tc.timestamp}")

        for cmd in self.trace.commands():
            cmd_lower = cmd.command.lower()
            if any(term in cmd_lower for term in ("curl ", "wget ", "gh pr comment", "gh api")):
                violations.append(f"Command: {cmd.command} at {cmd.timestamp}")

        if violations:
            return False, "Unauthorized external calls observed:\n" + "\n".join(f"  • {v}" for v in violations)
        return True, "Zero unauthorized external calls observed"


# ---------------------------------------------------------------------------
# Test Output Parser Helper
# ---------------------------------------------------------------------------

def parse_test_command_output(command: str, exit_code: int, stdout: str, stderr: str) -> Optional[Dict[str, Any]]:
    """Parse output of test runners (pytest, unittest, jest, cargo test)."""
    text = (stdout + "\n" + stderr).strip()
    cmd_lower = command.lower()

    # Pytest
    if "pytest" in cmd_lower or "test session starts" in text:
        m_summary = re.search(r"(=+)\s*(.*?)\s*in\s*[\d\.]+s\s*=+", text)
        summary_line = m_summary.group(2) if m_summary else text

        passed = 0
        failed = 0
        m_p = re.search(r"(\d+)\s+passed", summary_line)
        if m_p:
            passed = int(m_p.group(1))
        m_f = re.search(r"(\d+)\s+failed", summary_line)
        if m_f:
            failed = int(m_f.group(1))

        failures = re.findall(r"FAILED\s+(.*?)(?:\n|$)", text)
        return {
            "framework": "pytest",
            "command": command,
            "exit_code": exit_code,
            "total_count": passed + failed,
            "passed_count": passed,
            "failed_count": failed,
            "failures": failures,
        }

    # Python unittest
    if "unittest" in cmd_lower or "Ran " in text:
        m_ran = re.search(r"Ran\s+(\d+)\s+tests?", text)
        total = int(m_ran.group(1)) if m_ran else 0
        failed = 0
        m_f = re.search(r"FAILED\s*\((?:failures=(\d+))?(?:,\s*errors=(\d+))?\)", text)
        if m_f:
            f_count = int(m_f.group(1) or 0)
            e_count = int(m_f.group(2) or 0)
            failed = f_count + e_count
        passed = max(0, total - failed)
        failures = re.findall(r"FAIL:\s+(.*?)(?:\n|$)", text) + re.findall(r"ERROR:\s+(.*?)(?:\n|$)", text)
        return {
            "framework": "unittest",
            "command": command,
            "exit_code": exit_code,
            "total_count": total,
            "passed_count": passed,
            "failed_count": failed,
            "failures": failures,
        }

    # Generic test runner command check
    if any(k in cmd_lower for k in ("test", "pytest", "npm test", "jest")):
        return {
            "framework": "generic",
            "command": command,
            "exit_code": exit_code,
            "total_count": 1 if exit_code == 0 else 0,
            "passed_count": 1 if exit_code == 0 else 0,
            "failed_count": 0 if exit_code == 0 else 1,
            "failures": [text[:200]] if exit_code != 0 else [],
        }

    return None


# ---------------------------------------------------------------------------
# Execution Observer (Host-side Runtime Monitor)
# ---------------------------------------------------------------------------

class ExecutionObserver:
    """
    Host-side observer that tracks a workspace during an AgentFlow run:
    - Snapshots filesystem changes with SHA-256 before & after and unified diffs.
    - Intercepts tool calls and tool results.
    - Records command executions and parses test runner outputs.
    - Appends cryptographically chained events into the execution trace.
    """

    def __init__(
        self,
        repo_root: Path,
        run_id: Optional[str] = None,
        skill: str = "ship",
        change_id: Optional[str] = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.run_id = run_id or f"run-{int(time.time() * 1000)}"
        self.skill = skill
        self.change_id = change_id
        self.trace = ExecutionTrace(run_id=self.run_id)
        self.file_snapshots: Dict[str, str] = {}  # rel_path -> sha256
        self.file_contents: Dict[str, str] = {}   # rel_path -> text (for diffs)
        self._seq = 0
        self._last_hash = GENESIS_PREV_HASH
        self._take_baseline_snapshot()

    def __enter__(self) -> "ExecutionObserver":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.snapshot_file_changes()

    def _next_event_id(self) -> str:
        self._seq += 1
        return f"evt-{self._seq:06d}"

    def _emit(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        target: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> ExecutionEvent:
        ts = _now_iso()
        event = ExecutionEvent(
            event_id=self._next_event_id(),
            event_type=event_type.value,
            timestamp=ts,
            change_id=self.change_id,
            agent_id=agent_id,
            target=target,
            payload=payload,
            prev_event_hash=self._last_hash,
            event_hash="",
        )
        event.event_hash = compute_event_hash(event)
        self._last_hash = event.event_hash
        self.trace.append_event(event)
        return event

    # ------------------------------------------------------------------ #
    # File Change Snapshotting                                            #
    # ------------------------------------------------------------------ #

    def _compute_hash(self, path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            return ""

    def _read_text_safe(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def _take_baseline_snapshot(self) -> None:
        self.file_snapshots.clear()
        self.file_contents.clear()
        if not self.repo_root.exists():
            return

        for p in self.repo_root.rglob("*"):
            if p.is_file() and not self._is_ignored(p):
                rel = str(p.relative_to(self.repo_root))
                self.file_snapshots[rel] = self._compute_hash(p)
                self.file_contents[rel] = self._read_text_safe(p)

    def _is_ignored(self, p: Path) -> bool:
        # Never follow agent-created links when collecting host-side evidence.
        # A regular file replaced by a link is recorded as deletion, not read.
        if p.is_symlink() or not p.resolve().is_relative_to(self.repo_root):
            return True
        parts = p.parts
        return any(
            ignored in parts
            for ignored in (".git", ".agentflow", ".pytest_cache", "__pycache__", "node_modules", ".ruff_cache")
        )

    def snapshot_file_changes(self) -> List[FileChangeRecord]:
        """
        Compare working directory against last snapshot and emit FILE_MODIFIED events.
        """
        current_snapshots: Dict[str, str] = {}
        current_contents: Dict[str, str] = {}
        records: List[FileChangeRecord] = []

        if self.repo_root.exists():
            for p in self.repo_root.rglob("*"):
                if p.is_file() and not self._is_ignored(p):
                    rel = str(p.relative_to(self.repo_root))
                    current_snapshots[rel] = self._compute_hash(p)
                    current_contents[rel] = self._read_text_safe(p)

        all_paths = sorted(set(self.file_snapshots.keys()) | set(current_snapshots.keys()))

        for rel in all_paths:
            before_hash = self.file_snapshots.get(rel, "")
            after_hash = current_snapshots.get(rel, "")

            if before_hash == after_hash:
                continue

            change_type = "modified"
            before_text = self.file_contents.get(rel, "")
            after_text = current_contents.get(rel, "")

            if not before_hash:
                change_type = "created"
            elif not after_hash:
                change_type = "deleted"

            diff = "".join(
                difflib.unified_diff(
                    before_text.splitlines(keepends=True),
                    after_text.splitlines(keepends=True),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
            )

            is_test = is_test_file(rel)
            is_prod = is_production_code(rel)

            event = self._emit(
                EventType.FILE_MODIFIED,
                payload={
                    "path": rel,
                    "change_type": change_type,
                    "before_hash": before_hash,
                    "after_hash": after_hash,
                    "diff": diff,
                    "is_test": is_test,
                    "is_production": is_prod,
                },
                target=rel,
            )

            record = FileChangeRecord(
                path=rel,
                change_type=change_type,
                before_hash=before_hash,
                after_hash=after_hash,
                diff=diff,
                is_test=is_test,
                is_production=is_prod,
                timestamp=event.timestamp,
                seq=len(self.trace.events) - 1,
            )
            records.append(record)

        self.file_snapshots = current_snapshots
        self.file_contents = current_contents
        return records

    # ------------------------------------------------------------------ #
    # Tool Call Observation                                              #
    # ------------------------------------------------------------------ #

    def observe_tool_call(
        self,
        name: str,
        arguments: Dict[str, Any],
        call_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> ToolCallRecord:
        cid = call_id or f"call-{int(time.time() * 1000)}"
        event = self._emit(
            EventType.TOOL_CALL,
            payload={"name": name, "arguments": arguments, "call_id": cid},
            target=name,
            agent_id=agent_id,
        )
        return ToolCallRecord(
            name=name,
            arguments=arguments,
            call_id=cid,
            timestamp=event.timestamp,
            seq=len(self.trace.events) - 1,
            agent_id=agent_id,
        )

    def observe_tool_result(
        self,
        call_id: str,
        name: str,
        result: Any = None,
        error: Optional[str] = None,
        duration_ms: float = 0.0,
    ) -> ToolResultRecord:
        event = self._emit(
            EventType.TOOL_RESULT,
            payload={
                "call_id": call_id,
                "name": name,
                "result": str(result)[:500] if result is not None else None,
                "error": error,
                "duration_ms": duration_ms,
            },
            target=name,
        )
        return ToolResultRecord(
            name=name,
            call_id=call_id,
            result=result,
            error=error,
            duration_ms=duration_ms,
            timestamp=event.timestamp,
            seq=len(self.trace.events) - 1,
        )

    # ------------------------------------------------------------------ #
    # Command and Test Run Observation                                   #
    # ------------------------------------------------------------------ #

    def observe_command(
        self,
        command: str,
        cwd: Optional[str] = None,
        exit_code: int = 0,
        stdout: str = "",
        stderr: str = "",
        duration_ms: float = 0.0,
    ) -> CommandRecord:
        working_dir = cwd or str(self.repo_root)
        parsed_test = parse_test_command_output(command, exit_code, stdout, stderr)
        is_test = parsed_test is not None

        cmd_event = self._emit(
            EventType.COMMAND_EXEC,
            payload={
                "command": command,
                "cwd": working_dir,
                "exit_code": exit_code,
                "stdout": stdout[:2000],
                "stderr": stderr[:2000],
                "duration_ms": duration_ms,
                "is_test_run": is_test,
            },
            target=command,
        )

        # If it was a test execution, emit dedicated TEST_EXECUTED event
        if parsed_test:
            self._emit(
                EventType.TEST_EXECUTED,
                payload=parsed_test,
                target=parsed_test["framework"],
            )

        # Snapshot files in case the command wrote files on disk
        self.snapshot_file_changes()

        return CommandRecord(
            command=command,
            cwd=working_dir,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timestamp=cmd_event.timestamp,
            seq=len(self.trace.events) - 1,
            is_test_run=is_test,
        )

    def execute_command(self, command: str, cwd: Optional[Path] = None) -> CommandRecord:
        """Run command in shell and observe execution and filesystem side-effects."""
        run_dir = cwd or self.repo_root
        t0 = time.monotonic()
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(run_dir),
            capture_output=True,
            text=True,
        )
        duration_ms = (time.monotonic() - t0) * 1000
        return self.observe_command(
            command=command,
            cwd=str(run_dir),
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------ #
    # Lifecycle Transitions                                              #
    # ------------------------------------------------------------------ #

    def observe_lifecycle_transition(
        self,
        skill: str,
        phase: str,
        action: str,
        state_delta: Optional[Dict[str, Any]] = None,
    ) -> LifecycleRecord:
        event = self._emit(
            EventType.LIFECYCLE_TRANSITION,
            payload={
                "skill": skill,
                "phase": phase,
                "action": action,
                "state_delta": state_delta or {},
            },
            target=skill,
        )
        return LifecycleRecord(
            skill=skill,
            phase=phase,
            action=action,
            state_delta=state_delta or {},
            timestamp=event.timestamp,
            seq=len(self.trace.events) - 1,
        )

    def get_trace(self) -> ExecutionTrace:
        return self.trace
