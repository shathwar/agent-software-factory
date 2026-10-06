"""Evaluation & Regression Harness: System Benchmark Engine for AgentFlow.

Measures AgentFlow across 10 core dimensions:
1. Policy Enforcement
2. Convergence Guardrails
3. Verification Quality
4. False Approvals (target: 0.0%)
5. False Blocks (target: 0.0%)
6. Crash Recovery & Reconciliation (target: 100%)
7. Race Conditions & Concurrency
8. Latency Distribution (p50, p90, p95, p99)
9. Cost Tracking & Ceilings
10. Autonomy Completion Rate
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
import json
import math
from pathlib import Path
import statistics
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional

from .approvals import ApprovalManager
from .capabilities import CapabilityManager
from .convergence import ConvergenceController, evaluate_convergence
from .coordination import CoordinationManager
from .events import EventLogger
from .ledger import FileLedgerStore
from .models import (
    CapabilityOperation,
    EventType,
    StagnationType,
)
from .provenance import ProvenanceManager
from .recovery import RecoveryManager
from .verification import verify_finding_grounding


class BenchmarkDimension(str, Enum):
    POLICY_ENFORCEMENT = "policy_enforcement"
    CONVERGENCE = "convergence"
    VERIFICATION_QUALITY = "verification_quality"
    FALSE_APPROVALS = "false_approvals"
    FALSE_BLOCKS = "false_blocks"
    RECOVERY = "recovery"
    RACE_CONDITIONS = "race_conditions"
    LATENCY = "latency"
    COST = "cost"
    AUTONOMY_COMPLETION = "autonomy_completion"


@dataclass
class ScenarioResult:
    scenario_id: str
    name: str
    dimension: str
    passed: bool
    duration_ms: float
    cost_dollars: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    diagnostics: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "dimension": self.dimension,
            "passed": self.passed,
            "duration_ms": round(self.duration_ms, 2),
            "cost_dollars": round(self.cost_dollars, 4),
            "metrics": self.metrics,
            "error": self.error,
            "diagnostics": self.diagnostics,
        }


@dataclass
class EvaluationReport:
    timestamp: str
    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    pass_rate_pct: Optional[float]
    policy_enforcement_rate: Optional[float]
    convergence_detection_rate: Optional[float]
    verification_quality_score: Optional[float]
    false_approval_rate: Optional[float]
    false_block_rate: Optional[float]
    recovery_success_rate: Optional[float]
    race_condition_resilience: Optional[float]
    latency_percentiles_ms: Dict[str, float]
    total_cost_dollars: float
    autonomy_completion_rate: Optional[float]
    scenario_results: List[ScenarioResult] = field(default_factory=list)
    dimension_statuses: Dict[str, str] = field(default_factory=dict)

    @property
    def status(self) -> str:
        """Overall outcome applies only to the selected suite."""
        if self.failed_scenarios or "failed" in self.dimension_statuses.values():
            return "failed"
        if not self.total_scenarios:
            return "unrun"
        if "inconclusive" in self.dimension_statuses.values():
            return "inconclusive"
        return "passed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "status": self.status,
            "dimension_statuses": self.dimension_statuses,
            "total_scenarios": self.total_scenarios,
            "passed_scenarios": self.passed_scenarios,
            "failed_scenarios": self.failed_scenarios,
            "pass_rate_pct": round(self.pass_rate_pct, 1) if self.pass_rate_pct is not None else None,
            "summary_rates": {
                "policy_enforcement_rate": round(self.policy_enforcement_rate, 4) if self.policy_enforcement_rate is not None else None,
                "convergence_detection_rate": round(self.convergence_detection_rate, 4) if self.convergence_detection_rate is not None else None,
                "verification_quality_score": round(self.verification_quality_score, 4) if self.verification_quality_score is not None else None,
                "false_approval_rate": round(self.false_approval_rate, 4) if self.false_approval_rate is not None else None,
                "false_block_rate": round(self.false_block_rate, 4) if self.false_block_rate is not None else None,
                "recovery_success_rate": round(self.recovery_success_rate, 4) if self.recovery_success_rate is not None else None,
                "race_condition_resilience": round(self.race_condition_resilience, 4) if self.race_condition_resilience is not None else None,
                "autonomy_completion_rate": round(self.autonomy_completion_rate, 4) if self.autonomy_completion_rate is not None else None,
            },
            "latency_percentiles_ms": {k: round(v, 2) for k, v in self.latency_percentiles_ms.items()},
            "total_cost_dollars": round(self.total_cost_dollars, 4),
            "scenarios": [s.to_dict() for s in self.scenario_results],
        }


# =============================================================================
# Benchmark Scenario Implementations
# =============================================================================

def scenario_policy_enforcement(repo_root: Path) -> ScenarioResult:
    """Benchmark: Verify strict Ring 0/1/2 policy boundaries and capability enforcement."""
    t0 = time.perf_counter()
    diag = []
    cid = "c-default"

    prov = ProvenanceManager(repo_root)
    prov.register_identity(agent_id="agent-worker", role="maker", change_id=cid)
    cap_mgr = CapabilityManager(repo_root)

    # 1. Ring 0 direct mutation must be denied
    dec_r0 = cap_mgr.evaluate_access(
        agent_id="agent-worker",
        operation=CapabilityOperation.WRITE,
        target=".agentflow/ledger.json",
        change_id=cid,
    )
    if dec_r0.allowed or "Ring 0" not in dec_r0.reason:
        return ScenarioResult(
            scenario_id="policy_enforcement",
            name="Policy Enforcement & Ring Isolation",
            dimension=BenchmarkDimension.POLICY_ENFORCEMENT.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error=f"Ring 0 mutation wrongly allowed: {dec_r0.reason}",
        )
    diag.append("Ring 0 mutation blocked cleanly")

    # 2. Ring 1 governance mutation without ADR approval must be denied
    cap_mgr.grant_capability(
        agent_id="agent-worker",
        operation=CapabilityOperation.WRITE,
        target=".agentflow.json",
        ttl_seconds=3600,
        approval_ref="maker:self",  # Unapproved governance write ref
        change_id=cid,
    )
    dec_r1 = cap_mgr.evaluate_access(
        agent_id="agent-worker",
        operation=CapabilityOperation.WRITE,
        target=".agentflow.json",
        change_id=cid,
    )
    if dec_r1.allowed or "Ring 1" not in dec_r1.reason:
        return ScenarioResult(
            scenario_id="policy_enforcement",
            name="Policy Enforcement & Ring Isolation",
            dimension=BenchmarkDimension.POLICY_ENFORCEMENT.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error=f"Ring 1 governance mutation wrongly allowed: {dec_r1.reason}",
        )
    diag.append("Ring 1 mutation blocked cleanly without ADR approval")

    # 3. Unauthorized secret read must be denied
    dec_sec = cap_mgr.evaluate_access(
        agent_id="agent-worker",
        operation=CapabilityOperation.SECRET_READ,
        target="AWS_SECRET_ACCESS_KEY",
        change_id=cid,
    )
    if dec_sec.allowed:
        return ScenarioResult(
            scenario_id="policy_enforcement",
            name="Policy Enforcement & Ring Isolation",
            dimension=BenchmarkDimension.POLICY_ENFORCEMENT.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error="Unauthorized secret read wrongly allowed",
        )
    diag.append("Unauthorized secret read blocked cleanly")

    return ScenarioResult(
        scenario_id="policy_enforcement",
        name="Policy Enforcement & Ring Isolation",
        dimension=BenchmarkDimension.POLICY_ENFORCEMENT.value,
        passed=True,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        metrics={"checks_enforced": 3, "violations_intercepted": 3},
        diagnostics=diag,
    )


def scenario_convergence_guardrails(repo_root: Path) -> ScenarioResult:
    """Benchmark: Verify anti-infinite loop oscillation detection and budget ceilings."""
    t0 = time.perf_counter()
    diag = []

    # 1. Detect oscillating remediation loop (A -> B -> A -> B)
    change_oscillating = {
        "change_id": "c-osc",
        "turns": [
            {"turn_id": "t1", "skill": "fix_a", "state_delta": {"mode": "jwt"}},
            {"turn_id": "t2", "skill": "fix_b", "state_delta": {"mode": "session"}},
            {"turn_id": "t3", "skill": "fix_a", "state_delta": {"mode": "jwt"}},
            {"turn_id": "t4", "skill": "fix_b", "state_delta": {"mode": "session"}},
        ],
    }
    status_osc = evaluate_convergence(change_oscillating)
    if not status_osc.is_halted or status_osc.stagnation_type != StagnationType.OSCILLATING_STATE.value:
        return ScenarioResult(
            scenario_id="convergence_guardrails",
            name="Convergence Guardrails & Oscillation Detection",
            dimension=BenchmarkDimension.CONVERGENCE.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error="Oscillating state loop was not detected",
        )
    diag.append(f"Oscillation detected: {status_osc.reason}")

    # 2. Detect budget ceiling breach (max_total_turns)
    turns_exhausted = [
        {"turn_id": f"t{i}", "skill": "tdd", "timestamp": "2026-01-01T00:00:00Z"}
        for i in range(30)
    ]
    change_exhausted = {"change_id": "c-exh", "turns": turns_exhausted}
    cfg = {"convergence": {"max_total_turns": 25}}
    status_exh = evaluate_convergence(change_exhausted, config=cfg)
    if not status_exh.is_halted or "turns limit exceeded" not in status_exh.reason:
        return ScenarioResult(
            scenario_id="convergence_guardrails",
            name="Convergence Guardrails & Oscillation Detection",
            dimension=BenchmarkDimension.CONVERGENCE.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error="Total turns budget limit breach was not halted",
        )
    diag.append(f"Budget exhaustion halted: {status_exh.reason}")

    return ScenarioResult(
        scenario_id="convergence_guardrails",
        name="Convergence Guardrails & Oscillation Detection",
        dimension=BenchmarkDimension.CONVERGENCE.value,
        passed=True,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        metrics={"stagnation_detected": True, "budget_enforced": True},
        diagnostics=diag,
    )


def scenario_verification_quality(repo_root: Path) -> ScenarioResult:
    """Benchmark: Verify grounding accuracy and contradictory test evidence detection."""
    t0 = time.perf_counter()
    diag = []

    # Create dummy source file for grounding
    src_file = repo_root / "src" / "math_lib.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n")

    # 1. Hallucinated finding citing nonexistent line range
    hallucinated_finding = {
        "file": "src/math_lib.py",
        "line": "L150-L160",
        "evidence": "def nonexistent(): return None",
    }
    grounded, msg = verify_finding_grounding(hallucinated_finding, repo_root)
    if grounded:
        return ScenarioResult(
            scenario_id="verification_quality",
            name="Verification Quality & Grounding Fidelity",
            dimension=BenchmarkDimension.VERIFICATION_QUALITY.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error="Hallucinated finding was wrongly accepted as grounded",
        )
    diag.append("Hallucinated finding rejected by grounding inspector")

    # 2. Valid grounded finding
    valid_finding = {
        "file": "src/math_lib.py",
        "line": "L1-L2",
        "evidence": "def add(a, b):\n    return a + b",
    }
    grounded_valid, msg_valid = verify_finding_grounding(valid_finding, repo_root)
    if not grounded_valid:
        return ScenarioResult(
            scenario_id="verification_quality",
            name="Verification Quality & Grounding Fidelity",
            dimension=BenchmarkDimension.VERIFICATION_QUALITY.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error=f"Valid finding was wrongly rejected by grounding: {msg_valid}",
        )
    diag.append("Valid finding grounded with exact match")

    return ScenarioResult(
        scenario_id="verification_quality",
        name="Verification Quality & Grounding Fidelity",
        dimension=BenchmarkDimension.VERIFICATION_QUALITY.value,
        passed=True,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        metrics={"grounding_accuracy": 1.0, "hallucinations_caught": 1},
        diagnostics=diag,
    )


def scenario_false_approvals(repo_root: Path) -> ScenarioResult:
    """Benchmark: Verify that forged, replayed, or cross-agent approvals are rejected (target: 0.0%)."""
    t0 = time.perf_counter()
    diag = []

    prov = ProvenanceManager(repo_root)
    prov.register_identity("agent-alice", "maker", change_id="c1")
    prov.register_identity("agent-bob", "checker", change_id="c1")
    appr_mgr = ApprovalManager(repo_root)

    # Human grants approval to Alice for change 'c1'
    appr = appr_mgr.issue_direct_approval(
        human="sec_lead:carol",
        agent="agent-alice",
        action="SECRET_READ",
        scope="AWS_*",
        reason="Deploy credentials",
        change="c1",
    )

    # 1. Attack: Bob attempts to use Alice's approval
    valid, err, _ = appr_mgr.validate_approval(appr.approval_id, "agent-bob", "c1", "SECRET_READ", "AWS_KEY")
    if valid:
        return ScenarioResult(
            scenario_id="false_approvals",
            name="False Approval Resilience (Cross-Agent & Cross-Change)",
            dimension=BenchmarkDimension.FALSE_APPROVALS.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error="Cross-agent approval reuse was wrongly accepted (False Approval)",
        )
    diag.append("Cross-agent approval replay rejected cleanly")

    # 2. Attack: Alice attempts to use approval in change 'c2'
    valid_c2, err_c2, _ = appr_mgr.validate_approval(appr.approval_id, "agent-alice", "c2", "SECRET_READ", "AWS_KEY")
    if valid_c2:
        return ScenarioResult(
            scenario_id="false_approvals",
            name="False Approval Resilience (Cross-Agent & Cross-Change)",
            dimension=BenchmarkDimension.FALSE_APPROVALS.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error="Cross-change approval reuse was wrongly accepted (False Approval)",
        )
    diag.append("Cross-change approval replay rejected cleanly")

    # 3. Attack: Tampered signature
    ledger = FileLedgerStore.load(repo_root)
    ledger["changes"]["c1"]["approvals"]["authorizations"][appr.approval_id]["scope"] = "*"
    FileLedgerStore.save(repo_root, ledger)

    valid_tamper, err_tamper, _ = appr_mgr.validate_approval(appr.approval_id, "agent-alice", "c1", "SECRET_READ", "AWS_KEY")
    if valid_tamper or err_tamper != "APPROVAL_TAMPERED":
        return ScenarioResult(
            scenario_id="false_approvals",
            name="False Approval Resilience (Cross-Agent & Cross-Change)",
            dimension=BenchmarkDimension.FALSE_APPROVALS.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error="Tampered approval signature was wrongly accepted",
        )
    diag.append("Tampered approval signature detected and rejected")

    return ScenarioResult(
        scenario_id="false_approvals",
        name="False Approval Resilience (Cross-Agent & Cross-Change)",
        dimension=BenchmarkDimension.FALSE_APPROVALS.value,
        passed=True,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        metrics={"false_approval_rate": 0.0, "attacks_deflected": 3},
        diagnostics=diag,
    )


def scenario_false_blocks(repo_root: Path) -> ScenarioResult:
    """Benchmark: Verify that legitimate authorized operations are allowed (target: 0.0% false blocks)."""
    t0 = time.perf_counter()
    diag = []

    prov = ProvenanceManager(repo_root)
    prov.register_identity("agent-legit", "maker", change_id="c-legit")
    cap_mgr = CapabilityManager(repo_root)
    coord = CoordinationManager(repo_root)

    # Grant valid capability for Ring 2 file modification
    cap_mgr.grant_capability(
        agent_id="agent-legit",
        operation=CapabilityOperation.WRITE,
        target="src/features/login.py",
        ttl_seconds=3600,
        approval_ref="human:supervisor",
        change_id="c-legit",
    )

    # Claim exclusive task lease
    coord_res = coord.claim_task(
        task_id="task-login",
        owner_id="agent-legit",
        change_id="c-legit",
        ttl_seconds=300,
        files=["src/features/login.py"],
    )
    if not coord_res.success or not coord_res.lease:
        return ScenarioResult(
            scenario_id="false_blocks",
            name="False Block Prevention (Legitimate Operation Allowance)",
            dimension=BenchmarkDimension.FALSE_BLOCKS.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error=f"Task claim failed: {coord_res.error}",
        )

    # Evaluate access for legitimate file write
    dec = cap_mgr.evaluate_access(
        agent_id="agent-legit",
        operation=CapabilityOperation.WRITE,
        target="src/features/login.py",
        change_id="c-legit",
        task_id="task-login",
        lease_token=coord_res.lease.lease_token,
    )

    if not dec.allowed:
        return ScenarioResult(
            scenario_id="false_blocks",
            name="False Block Prevention (Legitimate Operation Allowance)",
            dimension=BenchmarkDimension.FALSE_BLOCKS.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error=f"Legitimate operation was wrongly blocked (False Block): {dec.reason}",
        )
    diag.append("Legitimate authorized file write permitted smoothly")

    return ScenarioResult(
        scenario_id="false_blocks",
        name="False Block Prevention (Legitimate Operation Allowance)",
        dimension=BenchmarkDimension.FALSE_BLOCKS.value,
        passed=True,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        metrics={"false_block_rate": 0.0, "legitimate_operations_allowed": 1},
        diagnostics=diag,
    )


def scenario_recovery_reconciliation(repo_root: Path) -> ScenarioResult:
    """Benchmark: Verify deterministic crash recovery across checkpoints, leases, and halt clearance."""
    t0 = time.perf_counter()
    diag = []
    change_id = "c-recover"

    # Create checkpoints directory and place an orphan checkpoint file
    chk_dir = repo_root / ".agentflow" / "checkpoints"
    chk_dir.mkdir(parents=True, exist_ok=True)
    orphan_chk = chk_dir / f"{change_id}_implementation.json"
    orphan_chk.write_text(json.dumps({"gate": "implementation", "orphan": True}))

    FileLedgerStore.save(repo_root, {
        "version": 1,
        "active_change_id": change_id,
        "changes": {
            change_id: {
                "phase": "implementation",
                "turns": [],
                "blockers": ["Halt: Non-converging loop"],
                "checkpoints": {},  # Does not list implementation checkpoint
                "active_leases": {"task-orphan": {"agent_id": "agent-crashed", "expires_at": 100}},
            }
        },
    })

    # Run deterministic recovery manager
    rec_mgr = RecoveryManager(repo_root)
    decision = rec_mgr.reconcile_and_recover(
        change_id=change_id,
        intervened_by="supervisor",
        notes="Automated benchmark recovery test",
    )

    # Check orphan checkpoint was pruned
    if orphan_chk.exists():
        return ScenarioResult(
            scenario_id="recovery_reconciliation",
            name="Deterministic Crash Recovery & State Reconciliation",
            dimension=BenchmarkDimension.RECOVERY.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error="Orphan checkpoint receipt was not pruned during recovery",
        )
    diag.append("Orphan checkpoint receipt pruned")

    # Ledger state must have cleared the halt blocker
    ledger = FileLedgerStore.load(repo_root)
    blockers = ledger.get("changes", {}).get(change_id, {}).get("blockers", [])
    if any(b.startswith("Halt:") for b in blockers):
        return ScenarioResult(
            scenario_id="recovery_reconciliation",
            name="Deterministic Crash Recovery & State Reconciliation",
            dimension=BenchmarkDimension.RECOVERY.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error="Halt blocker was not cleared by recovery",
        )
    diag.append(f"Reconciled {len(decision.reconciled_items)} divergent items via {decision.strategy}")

    return ScenarioResult(
        scenario_id="recovery_reconciliation",
        name="Deterministic Crash Recovery & State Reconciliation",
        dimension=BenchmarkDimension.RECOVERY.value,
        passed=True,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        metrics={"recovery_success": 1.0, "reconciled_items": len(decision.reconciled_items)},
        diagnostics=diag,
    )


def scenario_race_concurrency(repo_root: Path) -> ScenarioResult:
    """Benchmark: Verify concurrency resilience across task leases and event log hash chaining."""
    t0 = time.perf_counter()
    diag = []

    # 1. 10 threads race to claim the exact same exclusive task lease
    coord = CoordinationManager(repo_root)
    successes = 0
    conflicts = 0

    def attempt_claim(agent_idx: int):
        agent_id = f"worker-{agent_idx}"
        res = coord.claim_task(
            task_id="race-task-1",
            owner_id=agent_id,
            change_id="c-race",
            ttl_seconds=30,
        )
        return res.success, (res.lease.owner_id if res.lease else res.error)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(attempt_claim, i) for i in range(10)]
        for f in as_completed(futures):
            ok, val = f.result()
            if ok:
                successes += 1
            else:
                conflicts += 1

    if successes != 1 or conflicts != 9:
        return ScenarioResult(
            scenario_id="race_concurrency",
            name="Race Condition & Concurrency Resilience",
            dimension=BenchmarkDimension.RACE_CONDITIONS.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error=f"Mutual exclusion violated: {successes} succeeded (expected 1), {conflicts} conflicts",
        )
    diag.append("10-thread lease contention yielded exactly 1 winner and 9 clean conflicts")

    # 2. 15 threads concurrently append to EventLogger
    ev_logger = EventLogger(repo_root)

    def append_event(idx: int):
        ev_logger.emit(
            event_type=EventType.ACTION_ALLOWED,
            agent_id=f"worker-{idx}",
            change_id="c-race",
            payload={"thread_idx": idx},
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(append_event, range(15)))

    # Verify event stream integrity
    valid_chain, chain_msg, broken_id = ev_logger.verify_integrity()
    if not valid_chain:
        return ScenarioResult(
            scenario_id="race_concurrency",
            name="Race Condition & Concurrency Resilience",
            dimension=BenchmarkDimension.RACE_CONDITIONS.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error=f"Concurrent event log hash chain corrupted: {chain_msg} (at {broken_id})",
        )
    diag.append("Concurrent event logging preserved 100% cryptographic hash chain integrity")

    return ScenarioResult(
        scenario_id="race_concurrency",
        name="Race Condition & Concurrency Resilience",
        dimension=BenchmarkDimension.RACE_CONDITIONS.value,
        passed=True,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        metrics={"lease_mutual_exclusion": 1.0, "event_log_chain_valid": True},
        diagnostics=diag,
    )


def scenario_latency_profile(repo_root: Path) -> ScenarioResult:
    """Benchmark: Measure latency distribution across 50 rapid policy evaluations."""
    t0 = time.perf_counter()
    prov = ProvenanceManager(repo_root)
    prov.register_identity("agent-perf", "maker", change_id="c-default")
    cap_mgr = CapabilityManager(repo_root)

    durations_ms: List[float] = []
    iterations = 50

    for _ in range(iterations):
        start = time.perf_counter()
        cap_mgr.evaluate_access(
            agent_id="agent-perf",
            operation=CapabilityOperation.READ,
            target="src/app.py",
            change_id="c-default",
        )
        elapsed = (time.perf_counter() - start) * 1000.0
        durations_ms.append(elapsed)

    durations_ms.sort()
    min_ms = durations_ms[0]
    p50_ms = statistics.median(durations_ms)
    p90_idx = int(math.ceil(0.90 * len(durations_ms))) - 1
    p95_idx = int(math.ceil(0.95 * len(durations_ms))) - 1
    p99_idx = int(math.ceil(0.99 * len(durations_ms))) - 1
    p90_ms = durations_ms[min(p90_idx, len(durations_ms) - 1)]
    p95_ms = durations_ms[min(p95_idx, len(durations_ms) - 1)]
    p99_ms = durations_ms[min(p99_idx, len(durations_ms) - 1)]
    max_ms = durations_ms[-1]
    mean_ms = statistics.mean(durations_ms)

    return ScenarioResult(
        scenario_id="latency_profile",
        name="Latency Distribution & Performance Profiling",
        dimension=BenchmarkDimension.LATENCY.value,
        passed=True,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        metrics={
            "iterations": iterations,
            "min_ms": round(min_ms, 3),
            "p50_ms": round(p50_ms, 3),
            "p90_ms": round(p90_ms, 3),
            "p95_ms": round(p95_ms, 3),
            "p99_ms": round(p99_ms, 3),
            "max_ms": round(max_ms, 3),
            "mean_ms": round(mean_ms, 3),
        },
        diagnostics=[f"p50: {p50_ms:.2f}ms, p95: {p95_ms:.2f}ms, mean: {mean_ms:.2f}ms across {iterations} ops"],
    )


def scenario_cost_tracking(repo_root: Path) -> ScenarioResult:
    """Benchmark: Measure cost tracking across turns and verify cost ceiling enforcement."""
    t0 = time.perf_counter()
    diag = []

    # Simulate turns with model/token costs
    turns = [
        {"turn_id": f"turn-{i:03d}", "skill": "tdd", "evidence": {"cost_dollars": 0.50}}
        for i in range(10)
    ]
    change = {"change_id": "c-cost", "turns": turns}

    # With budget ceiling of $4.00, $5.00 total should halt
    cfg = {"convergence": {"max_cost_dollars": 4.00}}
    status = evaluate_convergence(change, config=cfg)

    if not status.is_halted or "cost ceiling exceeded" not in status.reason.lower():
        return ScenarioResult(
            scenario_id="cost_tracking",
            name="Cost Tracking & Financial Guardrails",
            dimension=BenchmarkDimension.COST.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error=f"Cost ceiling breach was not halted: {status.reason}",
        )
    diag.append(f"Cost ceiling enforced cleanly: {status.reason} (total: ${status.total_cost:.2f})")

    return ScenarioResult(
        scenario_id="cost_tracking",
        name="Cost Tracking & Financial Guardrails",
        dimension=BenchmarkDimension.COST.value,
        passed=True,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        cost_dollars=status.total_cost,
        metrics={"total_cost_tracked": status.total_cost, "cost_halt_triggered": True},
        diagnostics=diag,
    )


def scenario_autonomy_completion(repo_root: Path) -> ScenarioResult:
    """Benchmark: Measure end-to-end autonomy completion rate across full lifecycle gates."""
    t0 = time.perf_counter()
    diag = []
    cid = "c-complete"

    # Setup a complete verified change
    change_data = {
        "change_id": cid,
        "phase": "implementation",
        "turns": [
            {
                "turn_id": "turn-001",
                "skill": "tdd",
                "evidence": {"tests_passed": True, "exit_code": 0},
            }
        ],
        "evidence": {
            "design": {"status": "CONFIRMED", "digest": "sha256:11111111111111111111111111111111"},
            "implementation": {"tests_passed": True, "exit_code": 0},
            "review": {"verdict": "PASS", "critical_or_high_count": 0},
        },
        "verification": {
            "execution": {"verdict": "VERIFIED", "tier": "execution"},
            "grounding": {"verdict": "VERIFIED", "tier": "grounding"},
        },
        "blockers": [],
    }

    controller = ConvergenceController()
    converged, msg = controller.certify_convergence(change_data)

    if not converged:
        return ScenarioResult(
            scenario_id="autonomy_completion",
            name="Autonomous Lifecycle Completion Rate",
            dimension=BenchmarkDimension.AUTONOMY_COMPLETION.value,
            passed=False,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            error=f"Autonomous change convergence failed: {msg}",
        )
    diag.append("Change certified for delivery within bounded convergence rules")

    return ScenarioResult(
        scenario_id="autonomy_completion",
        name="Autonomous Lifecycle Completion Rate",
        dimension=BenchmarkDimension.AUTONOMY_COMPLETION.value,
        passed=True,
        duration_ms=(time.perf_counter() - t0) * 1000.0,
        metrics={"completion_rate": 1.0, "delivery_certified": True},
        diagnostics=diag,
    )


# Registry of benchmark scenarios
STANDARD_SCENARIOS: List[Callable[[Path], ScenarioResult]] = [
    scenario_policy_enforcement,
    scenario_convergence_guardrails,
    scenario_verification_quality,
    scenario_false_approvals,
    scenario_false_blocks,
    scenario_recovery_reconciliation,
    scenario_race_concurrency,
    scenario_latency_profile,
    scenario_cost_tracking,
    scenario_autonomy_completion,
]


SCENARIO_DIMENSIONS = {
    "scenario_policy_enforcement": "policy_enforcement",
    "scenario_convergence_guardrails": "convergence",
    "scenario_verification_quality": "verification_quality",
    "scenario_false_approvals": "false_approvals",
    "scenario_false_blocks": "false_blocks",
    "scenario_recovery_reconciliation": "recovery",
    "scenario_race_concurrency": "race_conditions",
    "scenario_latency_profile": "latency",
    "scenario_cost_tracking": "cost",
    "scenario_autonomy_completion": "autonomy_completion",
}


# =============================================================================
# Evaluation Runner & Scorecard Formatter
# =============================================================================

class EvaluationRunner:
    """Executes repeatable benchmark scenarios against AgentFlow and aggregates metrics."""

    def __init__(self, scenarios: Optional[List[Callable[[Path], ScenarioResult]]] = None):
        self.scenarios = list(STANDARD_SCENARIOS) if scenarios is None else scenarios

    def run_suite(
        self,
        dimension_filter: Optional[str] = None,
        iterations: int = 1,
    ) -> EvaluationReport:
        """Run benchmark suite across isolated temporary workspaces and compute statistical aggregates."""
        if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
            raise ValueError("iterations must be a positive integer")
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        results: List[ScenarioResult] = []

        scenarios_to_run = self.scenarios
        if dimension_filter and dimension_filter.lower() != "all":
            df = dimension_filter.lower()
            scenarios_to_run = [
                s for s in self.scenarios
                if df in s.__name__.lower() or df == SCENARIO_DIMENSIONS.get(s.__name__)
            ]

        if dimension_filter and dimension_filter.lower() != "all" and not scenarios_to_run:
            raise ValueError(f"Unknown benchmark suite: {dimension_filter}")

        for scenario_fn in scenarios_to_run:
            for _ in range(iterations):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    repo_root = Path(tmp_dir)
                    # Initialize clean .agentflow structure
                    FileLedgerStore.save(repo_root, {"version": 1, "active_change_id": "c-default", "changes": {}})
                    try:
                        res = scenario_fn(repo_root)
                    except Exception as exc:
                        res = ScenarioResult(
                            scenario_id=scenario_fn.__name__,
                            name=scenario_fn.__name__,
                            dimension=SCENARIO_DIMENSIONS.get(scenario_fn.__name__, "unknown"),
                            passed=False,
                            duration_ms=0.0,
                            error=str(exc),
                        )
                    results.append(res)

        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        pass_rate = (passed / total * 100.0) if total > 0 else None
        by_dimension = {
            dim: [r for r in results if r.dimension == dim]
            for dim in sorted({d.value for d in BenchmarkDimension} | {r.dimension for r in results})
        }

        def get_metric(dim: str, key: str, *, rate: bool = True) -> Optional[float]:
            # Never drop failed iterations or fabricate missing measurements.
            matching = by_dimension[dim]
            values = [r.metrics.get(key) for r in matching]
            if not values or any(
                not isinstance(v, (int, float)) or isinstance(v, bool)
                or not math.isfinite(v) or v < 0 or (rate and v > 1)
                for v in values
            ):
                return None
            return float(statistics.mean(values))

        def scenario_pass_rate(dim: str) -> Optional[float]:
            matching = by_dimension[dim]
            return sum(r.passed for r in matching) / len(matching) if matching else None

        policy_rate = scenario_pass_rate("policy_enforcement")
        convergence_rate = scenario_pass_rate("convergence")
        verif_score = get_metric("verification_quality", "grounding_accuracy")
        false_appr_rate = get_metric("false_approvals", "false_approval_rate")
        false_block_rate = get_metric("false_blocks", "false_block_rate")
        rec_rate = get_metric("recovery", "recovery_success")
        race_resilience = get_metric("race_conditions", "lease_mutual_exclusion")
        autonomy_rate = get_metric("autonomy_completion", "completion_rate")
        rate_values = {
            "policy_enforcement": (policy_rate, 1.0, False),
            "convergence": (convergence_rate, 1.0, False),
            "verification_quality": (verif_score, 0.95, False),
            "false_approvals": (false_appr_rate, 0.0, True),
            "false_blocks": (false_block_rate, 0.0, True),
            "recovery": (rec_rate, 1.0, False),
            "race_conditions": (race_resilience, 1.0, False),
            "autonomy_completion": (autonomy_rate, 1.0, False),
        }
        # Average per-iteration summaries, not pooled latency percentiles.
        lat_percentiles = {}
        for key in ("min_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms", "mean_ms"):
            value = get_metric("latency", key, rate=False)
            if value is not None:
                lat_percentiles[key] = value

        statuses = {}
        for dim, matching in by_dimension.items():
            if not matching:
                statuses[dim] = "unrun"
            elif any(not r.passed for r in matching):
                statuses[dim] = "failed"
            elif dim in rate_values:
                value, threshold, lower_is_better = rate_values[dim]
                if value is None:
                    statuses[dim] = "inconclusive"
                else:
                    meets_target = value <= threshold if lower_is_better else value >= threshold
                    statuses[dim] = "passed" if meets_target else "failed"
            elif dim == "latency":
                statuses[dim] = "passed" if len(lat_percentiles) == 7 else "inconclusive"
            elif dim == "cost":
                complete = get_metric("cost", "total_cost_tracked", rate=False) is not None
                halted = all(r.metrics.get("cost_halt_triggered") is True for r in matching)
                statuses[dim] = "passed" if complete and halted else "inconclusive"
            else:
                statuses[dim] = "inconclusive"

        # Cost accumulation
        total_cost = sum(r.cost_dollars for r in results)

        return EvaluationReport(
            timestamp=now_iso,
            total_scenarios=total,
            passed_scenarios=passed,
            failed_scenarios=failed,
            pass_rate_pct=pass_rate,
            policy_enforcement_rate=policy_rate,
            convergence_detection_rate=convergence_rate,
            verification_quality_score=verif_score,
            false_approval_rate=false_appr_rate,
            false_block_rate=false_block_rate,
            recovery_success_rate=rec_rate,
            race_condition_resilience=race_resilience,
            latency_percentiles_ms=lat_percentiles,
            total_cost_dollars=total_cost,
            autonomy_completion_rate=autonomy_rate,
            scenario_results=results,
            dimension_statuses=statuses,
        )


def format_terminal_report(report: EvaluationReport) -> str:
    """Format an EvaluationReport into a high-visibility terminal scorecard."""
    status_labels = {
        "passed": "✅ PASS", "failed": "❌ FAIL",
        "unrun": "UNRUN", "inconclusive": "INCONCLUSIVE",
    }
    overall = status_labels[report.status]
    pass_rate = f"{report.pass_rate_pct:.1f}%" if report.pass_rate_pct is not None else "N/A"
    lines = [
        "AGENTFLOW SYSTEM BENCHMARK & EVALUATION REPORT",
        f"Selected suite: {overall} | {report.passed_scenarios}/{report.total_scenarios} scenarios passed ({pass_rate})",
        f"Timestamp: {report.timestamp}",
        "DIMENSION                          VALUE     TARGET    STATUS",
    ]
    dims = [
        ("policy_enforcement", "Policy Enforcement Accuracy", report.policy_enforcement_rate, "100.0%"),
        ("convergence", "Convergence Detection Rate", report.convergence_detection_rate, "100.0%"),
        ("verification_quality", "Verification Quality Score", report.verification_quality_score, "0.95"),
        ("false_approvals", "False Approval Rate (FP)", report.false_approval_rate, "0.0%"),
        ("false_blocks", "False Block Rate (FN)", report.false_block_rate, "0.0%"),
        ("recovery", "Recovery Success Rate", report.recovery_success_rate, "100.0%"),
        ("race_conditions", "Race Condition Resilience", report.race_condition_resilience, "100.0%"),
        ("autonomy_completion", "Autonomy Completion Rate", report.autonomy_completion_rate, "100.0%"),
    ]
    for dim, name, value, target in dims:
        val = "N/A" if value is None else (f"{value:.2f}" if dim == "verification_quality" else f"{value * 100:.1f}%")
        status = status_labels[report.dimension_statuses.get(dim, "unrun")]
        lines.append(f"{name:<34s} {val:<9s} {target:<9s} {status}")

    lines.extend(["", "LATENCY & COST METRICS"])
    lines.append(f"Latency: {status_labels[report.dimension_statuses.get('latency', 'unrun')]} (mean of iteration summaries)")
    lines.append(f"Cost checks: {status_labels[report.dimension_statuses.get('cost', 'unrun')]}")
    lat = report.latency_percentiles_ms
    p50_str = f"{lat['p50_ms']:.2f}ms" if 'p50_ms' in lat else "N/A"
    p95_str = f"{lat['p95_ms']:.2f}ms" if 'p95_ms' in lat else "N/A"
    p99_str = f"{lat['p99_ms']:.2f}ms" if 'p99_ms' in lat else "N/A"
    mean_str = f"{lat['mean_ms']:.2f}ms" if 'mean_ms' in lat else "N/A"
    lines.append(f"Latency Distribution: p50={p50_str}, p95={p95_str}, p99={p99_str}, mean={mean_str}")
    lines.append(f"Total Cost Tracked: ${report.total_cost_dollars:.4f}")

    lines.extend(["", "SCENARIO DETAILS"])

    for s in report.scenario_results:
        icon = "✅" if s.passed else "❌"
        lines.append(f"{icon} {s.name} [{s.duration_ms:.1f}ms]")
        for d in s.diagnostics[:2]:
            lines.append(f"  {d}")
        if s.error:
            lines.append(f"  ERROR: {s.error}")

    return "\n".join(lines)


def run_all_benchmarks(dimension_filter: Optional[str] = None, iterations: int = 1) -> EvaluationReport:
    """Convenience entrypoint to run benchmarks and return report."""
    runner = EvaluationRunner()
    return runner.run_suite(dimension_filter=dimension_filter, iterations=iterations)
