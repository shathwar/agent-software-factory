"""Convergence control and anti-infinite loop guardrails for AgentFlow."""

from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from .models import StagnationType


@dataclass
class ConvergenceConfig:
    max_remediation_attempts: int = 3
    max_same_failure_count: int = 2
    max_total_turns: int = 25
    max_time_seconds: float = 1800.0  # 30 minutes
    max_cost_dollars: float = 10.0

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ConvergenceConfig":
        if not data:
            return cls()
        conv = data.get("convergence", data)
        return cls(
            max_remediation_attempts=int(conv.get("max_remediation_attempts", 3)),
            max_same_failure_count=int(conv.get("max_same_failure_count", 2)),
            max_total_turns=int(conv.get("max_total_turns", 25)),
            max_time_seconds=float(conv.get("max_time_seconds", 1800.0)),
            max_cost_dollars=float(conv.get("max_cost_dollars", 10.0)),
        )


@dataclass
class ConvergenceStatus:
    is_halted: bool = False
    reason: str = ""
    remediation_attempts: int = 0
    same_failure_count: int = 0
    total_turns: int = 0
    elapsed_seconds: float = 0.0
    total_cost: float = 0.0
    stagnation_type: Optional[str] = None
    details: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_halted": self.is_halted,
            "reason": self.reason,
            "remediation_attempts": self.remediation_attempts,
            "same_failure_count": self.same_failure_count,
            "total_turns": self.total_turns,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "total_cost": round(self.total_cost, 4),
            "stagnation_type": self.stagnation_type,
            "details": self.details,
        }


def _hash_payload(payload: Any) -> str:
    """Deterministically compute SHA-256 digest of arbitrary payload."""
    try:
        norm = json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        norm = str(payload)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _is_passing_evidence(ev: Dict[str, Any]) -> bool:
    """Return True if evidence payload represents a clean passing check (not a failure/remediation loop)."""
    if ev.get("verdict") in ("PASS", "VERIFIED", "APPROVED"):
        if ev.get("critical_or_high_count", 0) == 0 and not ev.get("failed_tests"):
            return True
    if ev.get("tests_passed") is True and ev.get("exit_code", 0) == 0 and not ev.get("failed_tests"):
        return True
    return False


def detect_same_evidence(turns: List[Dict[str, Any]], max_same: int = 2) -> Tuple[bool, str]:
    """Detect if an agent produced identical failing/remediation evidence payloads across consecutive turns."""
    evidence_hashes: List[str] = []
    for t in turns:
        # Only evaluate evidence produced in execution/remediation/verification cycles
        if t.get("skill") in ("design", "human"):
            continue
        ev = t.get("evidence")
        if ev and isinstance(ev, dict) and ev:
            if _is_passing_evidence(ev):
                continue
            evidence_hashes.append(_hash_payload(ev))

    if len(evidence_hashes) < max_same:
        return False, ""

    # Check last N evidence hashes
    recent = evidence_hashes[-max_same:]
    if len(set(recent)) == 1:
        return True, f"Identical evidence payload submitted {max_same} consecutive times (hash: {recent[0][:8]})"
    return False, ""


def detect_same_finding(turns: List[Dict[str, Any]], max_same: int = 2) -> Tuple[bool, str]:
    """Detect if identical review or verification findings recur unresolved across consecutive turns."""
    finding_signatures: List[str] = []
    for t in turns:
        ev = t.get("evidence", {})
        findings_list = []
        if isinstance(ev, dict):
            # Review findings
            if "findings" in ev and isinstance(ev["findings"], list):
                findings_list = ev["findings"]
            elif "judge_report" in ev and isinstance(ev["judge_report"], dict):
                findings_list = ev["judge_report"].get("findings", [])
            # Verification findings
            elif "verification" in ev and isinstance(ev["verification"], dict):
                for v in ev["verification"].values():
                    if isinstance(v, dict) and v.get("findings"):
                        findings_list.extend(v.get("findings"))

        if findings_list:
            sig = _hash_payload(findings_list)
            finding_signatures.append(sig)

    if len(finding_signatures) < max_same:
        return False, ""

    recent = finding_signatures[-max_same:]
    if len(set(recent)) == 1:
        return True, f"Identical defect finding(s) persisted across {max_same} consecutive cycles without resolution"
    return False, ""


def detect_same_patch(turns: List[Dict[str, Any]], max_same: int = 2) -> Tuple[bool, str]:
    """Detect if the workspace diff or patch hash is stagnant across remediation turns."""
    patch_hashes: List[str] = []
    for t in turns:
        if t.get("skill") in ("design", "human"):
            continue
        # Check inputs or state_delta for working tree fingerprint / patch hash
        fp = (
            t.get("inputs", {}).get("tree_fingerprint")
            or t.get("state_delta", {}).get("tree_fingerprint")
            or t.get("evidence", {}).get("patch_hash")
        )
        if fp:
            patch_hashes.append(str(fp))

    if len(patch_hashes) < max_same:
        return False, ""

    recent = patch_hashes[-max_same:]
    if len(set(recent)) == 1:
        return True, f"Identical working tree diff ({recent[0][:8]}) submitted {max_same} times (zero code progress)"
    return False, ""


def detect_same_verifier_failure(turns: List[Dict[str, Any]], max_same: int = 2) -> Tuple[bool, str]:
    """Detect if independent verifier failed with identical reason consecutively."""
    verif_failures: List[str] = []
    for t in turns:
        if t.get("skill") == "verification":
            ev = t.get("evidence", {})
            fails = []
            for tier, rec in ev.items():
                if isinstance(rec, dict) and rec.get("verdict") == "NOT_VERIFIED":
                    fails.append(f"{tier}:{'; '.join(rec.get('findings', []))}")
            if fails:
                verif_failures.append(_hash_payload(fails))

    if len(verif_failures) < max_same:
        return False, ""

    recent = verif_failures[-max_same:]
    if len(set(recent)) == 1:
        return True, f"Independent verification failed with identical reason {max_same} consecutive times"
    return False, ""


def detect_oscillating_state(turns: List[Dict[str, Any]], min_cycle_len: int = 2) -> Tuple[bool, str]:
    """Detect thrashing/oscillation between two states (e.g. A -> B -> A -> B)."""
    skills: List[str] = [t.get("skill", "") for t in turns if t.get("skill")]
    if len(skills) < 4:
        return False, ""

    # Check for period-2 oscillation (e.g. [A, B, A, B])
    if len(skills) >= 4:
        last4 = skills[-4:]
        if last4[0] == last4[2] and last4[1] == last4[3] and last4[0] != last4[1]:
            return True, f"Oscillating state detected ({last4[0]} ⇆ {last4[1]}); conflicting remediation loop"

    return False, ""


def evaluate_convergence(
    active_change: Optional[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    current_fingerprint: Optional[str] = None,
) -> ConvergenceStatus:
    """Evaluate convergence bounds and detect stagnation in active change."""
    if not active_change or not isinstance(active_change, dict):
        return ConvergenceStatus()

    conv_cfg = ConvergenceConfig.from_dict(config)
    turns: List[Dict[str, Any]] = active_change.get("turns", [])
    blockers: List[str] = active_change.get("blockers", [])

    # Check if already halted explicitly
    halt_blockers = [b for b in blockers if b.startswith("Halt:")]
    if halt_blockers:
        return ConvergenceStatus(
            is_halted=True,
            reason=halt_blockers[0].replace("Halt:", "").strip(),
            total_turns=len(turns),
            details=halt_blockers,
        )

    # 1. Count remediation attempts
    # A remediation attempt is a turn initiated after a test failure or verification failure
    remediation_turns = [
        t for t in turns
        if t.get("skill") in ("tdd", "review", "verification")
        and (t.get("inputs", {}).get("failed_tiers") or t.get("state_delta", {}).get("tests_passed") is False)
    ]
    remediation_attempts = len(remediation_turns)

    # 2. Compute elapsed time
    elapsed_seconds = 0.0
    time_turns = remediation_turns if remediation_turns else turns
    if time_turns and time_turns[0].get("timestamp"):
        try:
            from datetime import datetime, timezone
            ts_str = time_turns[0]["timestamp"].replace("Z", "+00:00")
            first_time = datetime.fromisoformat(ts_str).timestamp()
            now_time = datetime.now(timezone.utc).timestamp()
            elapsed_seconds = max(0.0, now_time - first_time)
        except Exception:
            pass

    # 3. Compute total cost
    total_cost = 0.0
    for t in turns:
        cost = t.get("evidence", {}).get("cost_dollars") or t.get("inputs", {}).get("cost_dollars") or 0.0
        try:
            total_cost += float(cost)
        except (ValueError, TypeError):
            pass

    # --- Budget Checks ---
    if len(turns) >= conv_cfg.max_total_turns:
        reason = f"Total turns limit exceeded ({len(turns)} >= {conv_cfg.max_total_turns})"
        return ConvergenceStatus(
            is_halted=True,
            reason=reason,
            stagnation_type=StagnationType.BUDGET_EXCEEDED.value,
            remediation_attempts=remediation_attempts,
            total_turns=len(turns),
            elapsed_seconds=elapsed_seconds,
            total_cost=total_cost,
            details=[reason],
        )

    if remediation_attempts >= conv_cfg.max_remediation_attempts:
        reason = f"Maximum remediation attempts exceeded ({remediation_attempts} >= {conv_cfg.max_remediation_attempts})"
        return ConvergenceStatus(
            is_halted=True,
            reason=reason,
            stagnation_type=StagnationType.BUDGET_EXCEEDED.value,
            remediation_attempts=remediation_attempts,
            total_turns=len(turns),
            elapsed_seconds=elapsed_seconds,
            total_cost=total_cost,
            details=[reason],
        )

    if remediation_attempts > 0 and elapsed_seconds > conv_cfg.max_time_seconds:
        reason = f"Maximum remediation time exceeded ({elapsed_seconds:.0f}s > {conv_cfg.max_time_seconds:.0f}s)"
        return ConvergenceStatus(
            is_halted=True,
            reason=reason,
            stagnation_type=StagnationType.BUDGET_EXCEEDED.value,
            remediation_attempts=remediation_attempts,
            total_turns=len(turns),
            elapsed_seconds=elapsed_seconds,
            total_cost=total_cost,
            details=[reason],
        )

    if total_cost > conv_cfg.max_cost_dollars:
        reason = f"Maximum cost ceiling exceeded (${total_cost:.2f} > ${conv_cfg.max_cost_dollars:.2f})"
        return ConvergenceStatus(
            is_halted=True,
            reason=reason,
            stagnation_type=StagnationType.BUDGET_EXCEEDED.value,
            remediation_attempts=remediation_attempts,
            total_turns=len(turns),
            elapsed_seconds=elapsed_seconds,
            total_cost=total_cost,
            details=[reason],
        )

    # --- Stagnation Checks ---
    same_v, same_v_msg = detect_same_verifier_failure(turns, max_same=conv_cfg.max_same_failure_count)
    if same_v:
        return ConvergenceStatus(
            is_halted=True,
            reason=same_v_msg,
            stagnation_type=StagnationType.SAME_VERIFIER_FAILURE.value,
            remediation_attempts=remediation_attempts,
            same_failure_count=conv_cfg.max_same_failure_count,
            total_turns=len(turns),
            elapsed_seconds=elapsed_seconds,
            total_cost=total_cost,
            details=[same_v_msg],
        )

    same_f, same_f_msg = detect_same_finding(turns, max_same=conv_cfg.max_same_failure_count)
    if same_f:
        return ConvergenceStatus(
            is_halted=True,
            reason=same_f_msg,
            stagnation_type=StagnationType.SAME_FINDING.value,
            remediation_attempts=remediation_attempts,
            same_failure_count=conv_cfg.max_same_failure_count,
            total_turns=len(turns),
            elapsed_seconds=elapsed_seconds,
            total_cost=total_cost,
            details=[same_f_msg],
        )

    same_p, same_p_msg = detect_same_patch(turns, max_same=conv_cfg.max_same_failure_count)
    if same_p:
        return ConvergenceStatus(
            is_halted=True,
            reason=same_p_msg,
            stagnation_type=StagnationType.SAME_PATCH.value,
            remediation_attempts=remediation_attempts,
            same_failure_count=conv_cfg.max_same_failure_count,
            total_turns=len(turns),
            elapsed_seconds=elapsed_seconds,
            total_cost=total_cost,
            details=[same_p_msg],
        )

    same_e, same_e_msg = detect_same_evidence(turns, max_same=conv_cfg.max_same_failure_count)
    if same_e:
        return ConvergenceStatus(
            is_halted=True,
            reason=same_e_msg,
            stagnation_type=StagnationType.SAME_EVIDENCE.value,
            remediation_attempts=remediation_attempts,
            same_failure_count=conv_cfg.max_same_failure_count,
            total_turns=len(turns),
            elapsed_seconds=elapsed_seconds,
            total_cost=total_cost,
            details=[same_e_msg],
        )

    osc, osc_msg = detect_oscillating_state(turns)
    if osc:
        return ConvergenceStatus(
            is_halted=True,
            reason=osc_msg,
            stagnation_type=StagnationType.OSCILLATING_STATE.value,
            remediation_attempts=remediation_attempts,
            total_turns=len(turns),
            elapsed_seconds=elapsed_seconds,
            total_cost=total_cost,
            details=[osc_msg],
        )

    return ConvergenceStatus(
        is_halted=False,
        remediation_attempts=remediation_attempts,
        total_turns=len(turns),
        elapsed_seconds=elapsed_seconds,
        total_cost=total_cost,
    )


class ConvergenceController:
    """Governs and wraps the entire closed-loop Claim -> Evidence -> Verification -> Remediation lifecycle."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = ConvergenceConfig.from_dict(config)

    def evaluate_loop_state(
        self,
        active_change: Optional[Dict[str, Any]],
        current_fingerprint: Optional[str] = None,
    ) -> ConvergenceStatus:
        """Evaluate whether the loop is permitted to continue or if stagnation/budget limits halt autonomy."""
        return evaluate_convergence(
            active_change,
            config={"convergence": self.config.__dict__},
            current_fingerprint=current_fingerprint,
        )

    def certify_convergence(
        self,
        active_change: Optional[Dict[str, Any]],
        verification_records: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """Certify that a verified change has successfully converged within closed-loop bounds.

        Architecture:
            VERIFIED
               ↓
            Convergence Controller (certify_convergence)
               ↓
            Gate Decision
               ↓
            PASS / DELIVERY_READY
        """
        if not active_change or not isinstance(active_change, dict):
            return True, "No active change ledger entry to certify"

        # 1. Check for explicit halt blockers
        blockers = active_change.get("blockers", [])
        halt_b = [b for b in blockers if b.startswith("Halt:")]
        if halt_b:
            return False, halt_b[0].replace("Halt:", "").strip()

        # 2. Check loop status (budgets, attempts, stagnation)
        status = self.evaluate_loop_state(active_change)
        if status.is_halted:
            return False, status.reason

        # 3. Verify no lingering verification failures
        verif = verification_records or active_change.get("verification", {})
        if verif:
            for tier, rec in verif.items():
                if isinstance(rec, dict) and rec.get("verdict") == "NOT_VERIFIED":
                    return False, f"Unresolved verification failure in tier '{tier}'"

        return True, "Convergence certified: change verified cleanly within all operational budgets"

