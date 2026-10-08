"""
core.py – Data-model and execution engine for the agent regression harness.

Key types
---------
Trace         – Captured raw + structured agent output for one run.
BehaviourCheck – A single assertion predicate with a human-readable name.
Scenario      – One test case: prompt, fixture, expected checks, stub_response.
RunResult     – Pass/fail verdict for a single scenario run.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ship.lifecycle.observability import (
    CausalTraceVerifier,
    CommandRecord,
    ExecutionObserver,
    ExecutionTrace,
    FileChangeRecord,
    LifecycleRecord,
    TestResultRecord,
    ToolCallRecord,
)


# ---------------------------------------------------------------------------
# Trace – raw output captured from one agent invocation
# ---------------------------------------------------------------------------

@dataclass
class Trace:
    """Full output captured from one agent invocation."""

    raw: str                          # The complete stdout/stderr text
    exit_code: int = 0
    elapsed_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_trace: Optional[ExecutionTrace] = None

    # ------------------------------------------------------------------ #
    # Observability & Causal Verifier accessors                          #
    # ------------------------------------------------------------------ #

    def verifier(self) -> Optional[CausalTraceVerifier]:
        """Return CausalTraceVerifier if an execution trace is available."""
        return CausalTraceVerifier(self.execution_trace) if self.execution_trace else None

    def tool_calls(self) -> List[ToolCallRecord]:
        return self.execution_trace.tool_calls() if self.execution_trace else []

    def file_changes(self) -> List[FileChangeRecord]:
        return self.execution_trace.file_changes() if self.execution_trace else []

    def commands(self) -> List[CommandRecord]:
        return self.execution_trace.commands() if self.execution_trace else []

    def test_results(self) -> List[TestResultRecord]:
        return self.execution_trace.test_results() if self.execution_trace else []

    def lifecycle_transitions(self) -> List[LifecycleRecord]:
        return self.execution_trace.lifecycle_transitions() if self.execution_trace else []

    # ------------------------------------------------------------------ #
    # Convenience accessors                                                #
    # ------------------------------------------------------------------ #

    def contains(self, pattern: str, *, flags: int = re.IGNORECASE) -> bool:
        """True if ``pattern`` (regex) appears anywhere in the trace."""
        return bool(re.search(pattern, self.raw, flags))

    def section(self, heading: str) -> str:
        """
        Extract the text block that follows ``heading`` until the next
        markdown heading (# or ##) or end-of-string.
        """
        pattern = rf"(?i){re.escape(heading)}.*?\n(.*?)(?=\n#|\Z)"
        m = re.search(pattern, self.raw, re.DOTALL)
        return m.group(1).strip() if m else ""

    def findings(self) -> List[Dict[str, Any]]:
        """
        Parse findings from JSON-fenced code blocks embedded in the trace.
        Returns an empty list when none are present (clean review).
        """
        fenced = re.findall(r"```json\s*(.*?)```", self.raw, re.DOTALL)
        results: List[Dict[str, Any]] = []
        for block in fenced:
            try:
                obj = json.loads(block)
                if isinstance(obj, dict) and "findings" in obj:
                    results.extend(obj["findings"])
                elif isinstance(obj, list):
                    results.extend(obj)
            except json.JSONDecodeError:
                pass
        return results

    def finding_ids(self) -> List[str]:
        """Return all FINDING-NNN identifiers mentioned in the trace."""
        return re.findall(r"FINDING-\d{3}", self.raw)

    def verdict(self) -> Optional[str]:
        """Extract the overall verdict line from a review report."""
        m = re.search(
            r"\*\*Overall Verdict\*\*[:\s]+(READY TO DEPLOY|CHANGES REQUIRED|HIGH RISK.*?BLOCKED)",
            self.raw, re.IGNORECASE,
        )
        return m.group(1).upper() if m else None

    def scorecard_stage(self, stage_name: str) -> Optional[str]:
        """Return PASS/WARN/FAIL/SKIPPED for a named scorecard stage.

        Handles: ``| 1. **Correctness** | FAIL | Observation |``
        or ``| 2. **Concurrency / Safety** | PASS | ... |``
        """
        pattern = (
            rf"\|\s*(?:\d+\.\s*)?\*?\*?{re.escape(stage_name)}[^|]*\|"
            rf"\s*(PASS|WARN|FAIL|SKIPPED)"
        )
        m = re.search(pattern, self.raw, re.IGNORECASE)
        return m.group(1).upper() if m else None

    def has_evidence_block(self) -> bool:
        """True when output contains a code fence; its contents are not verified."""
        return bool(re.search(r"```\w*\n.+?```", self.raw, re.DOTALL))

    def repair_mutations(self) -> List[str]:
        """Return paths claimed in output diff lines, not observed filesystem edits."""
        return re.findall(r"\+\+\+ b/(.+)", self.raw)

    def has_conversational_filler(self) -> bool:
        """
        Detect the zero-filler constraint violation:
        'Certainly', 'I'd be happy to', 'Of course', 'Great question', etc.
        """
        patterns = [
            r"\bcertainly\b",
            r"\bi'?d be happy to\b",
            r"\bof course\b",
            r"\bgreat question\b",
            r"\bsure[,!]\b",
            r"\babsolutely\b",
        ]
        return any(re.search(p, self.raw, re.IGNORECASE) for p in patterns)

    def redacted_pii(self) -> bool:
        """True when the trace looks like it redacted a secret/PII (contains [REDACTED] or similar)."""
        return bool(re.search(r"\[REDACTED\]|\*{3,}", self.raw))

    def escalation_markers(self) -> List[str]:
        """Return any CRITICAL / HIGH RISK / BLOCKED markers in the trace."""
        return re.findall(r"CRITICAL|HIGH RISK|BLOCKED|ESCALAT", self.raw, re.IGNORECASE)


# ---------------------------------------------------------------------------
# BehaviourCheck – one named predicate that operates on a Trace
# ---------------------------------------------------------------------------

@dataclass
class BehaviourCheck:
    """
    A single named assertion.

    ``predicate`` receives the ``Trace`` and must return ``True`` to pass.
    ``negate``    inverts the predicate (use for "must NOT do X" assertions).
    """

    name: str
    predicate: Callable[[Trace], bool]
    negate: bool = False
    description: str = ""

    def evaluate(self, trace: Trace) -> tuple[bool, str]:
        """Return (passed, reason_string)."""
        try:
            result = self.predicate(trace)
        except Exception as exc:  # noqa: BLE001
            return False, f"Predicate raised {type(exc).__name__}: {exc}"

        passed = (not result) if self.negate else result
        reason = "" if passed else (
            f"{'negated check failed' if self.negate else 'check failed'}: {self.name}"
        )
        return passed, reason


# ---------------------------------------------------------------------------
# Scenario – one test case
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    """One agent regression test case."""

    # Human-readable identifiers
    skill: str                        # "review" | "debug" | "tdd" | "design"
    id: str                           # e.g. "review-001-clean-repo-finds-defect"
    description: str                  # One-line description of the expected response

    # Input to the agent
    prompt: str                       # The exact prompt the agent receives
    fixture: Optional["ScenarioFixture"] = None  # Optional source code scaffold

    # Behavioural expectations
    checks: List[BehaviourCheck] = field(default_factory=list)

    # Stub response used by default, even when credentials exist
    stub_response: str = ""

    # Real-agent observable actions (host-side tool calls, file writes, commands)
    observable_actions: Optional[Callable[[ExecutionObserver, Path], None]] = None
    execution_trace: Optional[ExecutionTrace] = None

    # Metadata
    tags: List[str] = field(default_factory=list)
    expected_exit_code: int = 0


# ---------------------------------------------------------------------------
# Causal BehaviourCheck Factories (Mechanical Proofs)
# ---------------------------------------------------------------------------

def check_test_failed_before_production_code_changed() -> BehaviourCheck:
    """Prove mechanically that a test failure occurred before any production code modification."""
    def _pred(t: Trace) -> bool:
        v = t.verifier()
        if not v:
            return False
        proven, _, _ = v.prove_test_failed_before_production_code_changed()
        return proven

    return BehaviourCheck(
        name="test_failed_before_production_code_changed",
        predicate=_pred,
        description="Verify mechanically from execution trace that test failed before production code changed",
    )


def check_red_green_cycle() -> BehaviourCheck:
    """Prove complete TDD Red -> Green cycle (Red test < Prod edit < Green test)."""
    def _pred(t: Trace) -> bool:
        v = t.verifier()
        if not v:
            return False
        proven, _, _ = v.prove_red_green_cycle()
        return proven

    return BehaviourCheck(
        name="red_green_cycle_proven",
        predicate=_pred,
        description="Verify mechanically that Test Red < Prod Edit < Test Green",
    )


def check_no_file_changes_outside(allowed_patterns: List[str]) -> BehaviourCheck:
    """Prove zero unauthorized file mutations outside allowed patterns."""
    def _pred(t: Trace) -> bool:
        v = t.verifier()
        if not v:
            return False
        proven, _ = v.prove_no_file_changes_outside(allowed_patterns)
        return proven

    return BehaviourCheck(
        name=f"no_file_changes_outside({allowed_patterns})",
        predicate=_pred,
        description=f"Verify mechanically that zero files changed outside {allowed_patterns}",
    )


def check_no_test_weakening() -> BehaviourCheck:
    """Prove no test skipping decorators or deleted assertions occurred."""
    def _pred(t: Trace) -> bool:
        v = t.verifier()
        if not v:
            return False
        proven, _ = v.prove_no_test_weakening()
        return proven

    return BehaviourCheck(
        name="no_test_weakening",
        predicate=_pred,
        description="Verify mechanically that test edits did not weaken assertions or add skips",
    )


def check_no_unauthorized_external_calls(forbidden_tools: Optional[List[str]] = None) -> BehaviourCheck:
    """Prove zero external network or comment calls occurred."""
    def _pred(t: Trace) -> bool:
        v = t.verifier()
        if not v:
            return False
        proven, _ = v.prove_no_unauthorized_external_calls(forbidden_tools)
        return proven

    return BehaviourCheck(
        name="no_unauthorized_external_calls",
        predicate=_pred,
        description="Verify mechanically that zero unauthorized external API or comment calls occurred",
    )


def check_trace_integrity() -> BehaviourCheck:
    """Prove cryptographic hash-chain integrity of the execution trace."""
    def _pred(t: Trace) -> bool:
        if not t.execution_trace:
            return False
        valid, _ = t.execution_trace.verify_integrity()
        return valid

    return BehaviourCheck(
        name="trace_hash_chain_integrity",
        predicate=_pred,
        description="Verify cryptographic hash-chain integrity across execution trace",
    )


# ---------------------------------------------------------------------------
# ScenarioFixture – ephemeral git repo scaffold
# ---------------------------------------------------------------------------

@dataclass
class ScenarioFixture:
    """
    Lightweight source-code scaffold for a scenario.

    ``files`` is a mapping of relative path → file content.
    ``git_commits`` is a list of (message, [paths]) pairs; each entry creates
    one commit containing those paths.  If empty, one "initial" commit is made
    from all files.
    """

    files: Dict[str, str] = field(default_factory=dict)
    git_commits: List[tuple[str, List[str]]] = field(default_factory=list)

    def materialise(self, root: Path) -> Path:
        """Write all files into ``root`` and initialise a git repository."""
        root.mkdir(parents=True, exist_ok=True)

        # Write all files first
        for rel_path, content in self.files.items():
            target = root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(textwrap.dedent(content), encoding="utf-8")

        # Git init
        _git(root, "init", "-b", "main")
        _git(root, "config", "user.name", "Harness")
        _git(root, "config", "user.email", "harness@example.com")
        _git(root, "config", "commit.gpgsign", "false")

        if self.git_commits:
            for message, paths in self.git_commits:
                for p in paths:
                    _git(root, "add", p)
                _git(root, "commit", "-m", message)
        else:
            _git(root, "add", ".")
            _git(root, "commit", "-m", "initial")

        return root


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


# ---------------------------------------------------------------------------
# AgentRunner – executes an agent and returns a Trace
# ---------------------------------------------------------------------------

class AgentRunner:
    """
    Invokes an AI agent against a prompt and captures the output as a Trace.

    Execution modes (controlled by ``AGENT_HARNESS_MODE`` env var):
      - ``live``  – calls ``agy`` CLI; checks captured output text
      - ``stub``  (default regardless of credentials) – canned responses; no API calls
      - ``anthropic`` – calls Anthropic API directly via Python SDK
    """

    def __init__(
        self,
        mode: Optional[str] = None,
        skill_dir: Optional[Path] = None,
        timeout_s: int = 300,
    ) -> None:
        self.mode = mode or os.environ.get("AGENT_HARNESS_MODE", "stub")
        self.skill_dir = skill_dir
        self.timeout_s = timeout_s

    def run(self, scenario: Scenario, workdir: Optional[Path] = None) -> Trace:
        """Execute ``scenario`` and return a Trace."""
        if self.mode == "stub":
            return self._run_stub(scenario, workdir)
        if self.mode == "anthropic":
            return self._run_anthropic(scenario, workdir)
        if self.mode == "live":
            return self._run_agy_cli(scenario, workdir)
        raise ValueError(f"Unknown AGENT_HARNESS_MODE: {self.mode!r}")

    # ------------------------------------------------------------------ #
    # Stub mode – deterministic; no LLM calls                             #
    # ------------------------------------------------------------------ #

    def _run_stub(self, scenario: Scenario, workdir: Optional[Path] = None) -> Trace:
        if not scenario.stub_response:
            raise ValueError(
                f"Scenario {scenario.id!r} has no stub_response. "
                "Either set stub_response or switch to AGENT_HARNESS_MODE=live."
            )
        exec_trace = scenario.execution_trace
        if scenario.observable_actions and workdir:
            observer = ExecutionObserver(workdir, run_id=f"run-{scenario.id}", skill=scenario.skill)
            scenario.observable_actions(observer, workdir)
            exec_trace = observer.get_trace()
        return Trace(raw=scenario.stub_response, exit_code=0, elapsed_ms=0.0, execution_trace=exec_trace)

    # ------------------------------------------------------------------ #
    # Anthropic SDK mode                                                   #
    # ------------------------------------------------------------------ #

    def _run_anthropic(self, scenario: Scenario, workdir: Optional[Path]) -> Trace:
        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK not installed. Run: pip install anthropic"
            ) from exc

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

        skill_instruction = self._load_skill_instruction(scenario.skill)
        system_prompt = (
            f"{skill_instruction}\n\nWorking directory: {workdir or '.'}"
            if skill_instruction
            else f"You are an expert software engineer. Working directory: {workdir or '.'}"
        )

        client = anthropic.Anthropic(api_key=api_key)
        t0 = time.monotonic()
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=8192,
            system=system_prompt,
            messages=[{"role": "user", "content": scenario.prompt}],
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

        raw = "\n".join(
            block.text for block in message.content if hasattr(block, "text")
        )
        return Trace(raw=raw, exit_code=0, elapsed_ms=elapsed_ms)

    # ------------------------------------------------------------------ #
    # AGY CLI mode                                                         #
    # ------------------------------------------------------------------ #

    def _run_agy_cli(self, scenario: Scenario, workdir: Optional[Path]) -> Trace:
        prompt_file = Path(tempfile.mktemp(suffix=".txt"))
        try:
            prompt_file.write_text(scenario.prompt, encoding="utf-8")
            t0 = time.monotonic()
            result = subprocess.run(
                ["agy", "run", "--prompt-file", str(prompt_file)],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            raw = result.stdout + result.stderr
            return Trace(raw=raw, exit_code=result.returncode, elapsed_ms=elapsed_ms)
        finally:
            prompt_file.unlink(missing_ok=True)

    def _load_skill_instruction(self, skill: str) -> str:
        """Load the SKILL.md for the given skill name from standard locations."""
        search_dirs = [
            Path.home() / ".gemini" / "config" / "skills",
            Path.home() / ".gemini" / "antigravity" / "builtin" / "skills",
        ]
        for base in search_dirs:
            skill_md = base / skill / "SKILL.md"
            if skill_md.exists():
                return skill_md.read_text(encoding="utf-8")
        return ""


# ---------------------------------------------------------------------------
# RunResult – outcome for one scenario
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    scenario_id: str
    scenario_description: str
    skill: str
    passed: bool
    checks_total: int
    checks_passed: int
    failures: List[str]          # Human-readable failure messages
    trace: Optional[Trace] = None
    error: Optional[str] = None  # Exception message if runner itself crashed
    elapsed_ms: float = 0.0

    @property
    def checks_failed(self) -> int:
        return self.checks_total - self.checks_passed

    def summary_line(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] {self.scenario_id}: {self.scenario_description} "
            f"({self.checks_passed}/{self.checks_total} checks)"
        )


# ---------------------------------------------------------------------------
# RegressionSuite – discovery, execution, reporting
# ---------------------------------------------------------------------------

class RegressionSuite:
    """
    Discovers and runs Scenario lists, returns a structured report.

    Usage::

        suite = RegressionSuite(scenarios=REVIEW_SCENARIOS, runner=AgentRunner())
        report = suite.run()
        assert report["passed"], report["summary"]
    """

    def __init__(
        self,
        scenarios: List[Scenario],
        runner: Optional[AgentRunner] = None,
    ) -> None:
        self.scenarios = scenarios
        self.runner = runner or AgentRunner()

    def run(self, *, skill_filter: Optional[str] = None) -> Dict[str, Any]:
        """Run all (or filtered) scenarios and return a summary dict."""
        targets = self.scenarios
        if skill_filter:
            targets = [s for s in targets if s.skill == skill_filter]

        results: List[RunResult] = []
        for scenario in targets:
            results.append(self._run_one(scenario))

        passed = bool(results) and all(r.passed for r in results)
        total = len(results)
        n_passed = sum(1 for r in results if r.passed)

        # This legacy runner captures text or scripted fixtures, not a live
        # host-mediated tool loop. Synthetic events must never certify behavior.
        assessment_kind = "stub_response_contract" if self.runner.mode == "stub" else "agent_output_contract"
        behavior_verified = False
        summary_prefix = f"Mode: {self.runner.mode}; output predicates only; behavior is not independently verified.\n"

        return {
            "mode": self.runner.mode,
            "assessment_kind": assessment_kind,
            "behavior_verified": behavior_verified,
            "status": ("pass" if passed else "fail") if total else "inconclusive",
            "passed": passed,
            "total": total,
            "n_passed": n_passed,
            "n_failed": total - n_passed,
            "pass_rate": n_passed / total if total else None,
            "results": results,
            "summary": summary_prefix + self._format_summary(results),
        }

    def _run_one(self, scenario: Scenario) -> RunResult:
        workdir: Optional[Path] = None
        tmp_obj = None
        try:
            # Materialise fixture if present
            if scenario.fixture is not None:
                tmp_obj = tempfile.TemporaryDirectory()
                workdir = scenario.fixture.materialise(Path(tmp_obj.name))

            trace = self.runner.run(scenario, workdir=workdir)
            failures: List[str] = []
            if trace.exit_code != scenario.expected_exit_code:
                failures.append(f"Expected exit code {scenario.expected_exit_code}, got {trace.exit_code}")
            if not scenario.checks:
                failures.append("No output checks configured")
            n_passed = 0

            for check in scenario.checks:
                ok, reason = check.evaluate(trace)
                if ok:
                    n_passed += 1
                else:
                    failures.append(reason or check.name)

            passed = len(failures) == 0
            return RunResult(
                scenario_id=scenario.id,
                scenario_description=scenario.description,
                skill=scenario.skill,
                passed=passed,
                checks_total=len(scenario.checks),
                checks_passed=n_passed,
                failures=failures,
                trace=trace,
                elapsed_ms=trace.elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001
            return RunResult(
                scenario_id=scenario.id,
                scenario_description=scenario.description,
                skill=scenario.skill,
                passed=False,
                checks_total=len(scenario.checks),
                checks_passed=0,
                failures=[f"Runner exception: {exc}"],
                error=str(exc),
            )
        finally:
            if tmp_obj is not None:
                tmp_obj.cleanup()

    @staticmethod
    def _format_summary(results: List[RunResult]) -> str:
        lines = ["=== Agent Regression Harness ==="]
        for r in results:
            lines.append(r.summary_line())
            for f in r.failures:
                lines.append(f"    ✗ {f}")
        n_pass = sum(1 for r in results if r.passed)
        lines.append(f"\n{n_pass}/{len(results)} scenarios passed.")
        return "\n".join(lines)
