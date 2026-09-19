"""Resource & Budget Governance for AgentFlow.

Tracks and enforces ceilings across 7 distinct resource dimensions:
  Change Budget
   ├── tokens
   ├── model calls
   ├── turns
   ├── time
   ├── dollars
   ├── tool executions
   └── network operations

Prevents an otherwise 'valid' autonomous workflow from becoming economically uncontrolled.
Zero external dependencies: 100% Python 3.10+ standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .models import EventType, StagnationType
from .ledger import FileLedgerStore


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


class ResourceMetric(str, Enum):
    """The 7 core resource consumption metrics."""
    TOKENS = "tokens"
    MODEL_CALLS = "model_calls"
    TURNS = "turns"
    TIME = "time"
    DOLLARS = "dollars"
    TOOL_EXECUTIONS = "tool_executions"
    NETWORK_OPERATIONS = "network_operations"


@dataclass
class ResourceUsage:
    """Accrued resource usage for a change."""
    tokens: int = 0
    model_calls: int = 0
    turns: int = 0
    time_seconds: float = 0.0
    dollars: float = 0.0
    tool_executions: int = 0
    network_operations: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tokens": self.tokens,
            "model_calls": self.model_calls,
            "turns": self.turns,
            "time_seconds": round(self.time_seconds, 2),
            "dollars": round(self.dollars, 4),
            "tool_executions": self.tool_executions,
            "network_operations": self.network_operations,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ResourceUsage":
        if not data:
            return cls()
        return cls(
            tokens=int(data.get("tokens", 0) or 0),
            model_calls=int(data.get("model_calls", 0) or 0),
            turns=int(data.get("turns", 0) or 0),
            time_seconds=float(data.get("time_seconds", 0.0) or 0.0),
            dollars=float(data.get("dollars", 0.0) or 0.0),
            tool_executions=int(data.get("tool_executions", 0) or 0),
            network_operations=int(data.get("network_operations", 0) or 0),
        )


@dataclass
class ChangeBudget:
    """Configured resource ceilings for a change."""
    max_tokens: Optional[int] = 1_000_000
    max_model_calls: Optional[int] = 100
    max_turns: Optional[int] = 25
    max_time_seconds: Optional[float] = 1800.0  # 30 minutes
    max_dollars: Optional[float] = 10.0
    max_tool_executions: Optional[int] = 200
    max_network_operations: Optional[int] = 50
    # Remediation / loop limits
    max_remediation_attempts: int = 3
    max_same_failures: int = 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_tokens": self.max_tokens,
            "max_model_calls": self.max_model_calls,
            "max_turns": self.max_turns,
            "max_time_seconds": self.max_time_seconds,
            "max_dollars": self.max_dollars,
            "max_tool_executions": self.max_tool_executions,
            "max_network_operations": self.max_network_operations,
            "max_remediation_attempts": self.max_remediation_attempts,
            "max_same_failures": self.max_same_failures,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ChangeBudget":
        if not data:
            return cls()
        # Check budget block, fallback to convergence block or root
        budget = data.get("budget")
        conv = data.get("convergence", {})
        if not budget:
            budget = conv or data
        
        # Max turns can come from budget.max_turns, or conv.max_total_turns, or budget.max_total_turns
        max_turns_val = budget.get("max_turns")
        if max_turns_val is None:
            max_turns_val = conv.get("max_total_turns") if conv.get("max_total_turns") is not None else budget.get("max_total_turns", 25)
        elif conv.get("max_total_turns") is not None and max_turns_val == 25:
            max_turns_val = conv.get("max_total_turns")

        # Max dollars can come from max_dollars or max_cost_dollars
        max_dollars_val = budget.get("max_dollars")
        if max_dollars_val is None:
            max_dollars_val = conv.get("max_cost_dollars") if conv.get("max_cost_dollars") is not None else budget.get("max_cost_dollars", 10.0)
        elif conv.get("max_cost_dollars") is not None and max_dollars_val == 10.0:
            max_dollars_val = conv.get("max_cost_dollars")

        # Max same failures can come from max_same_failures or max_same_failure_count
        max_same_val = budget.get("max_same_failures")
        if max_same_val is None:
            max_same_val = conv.get("max_same_failure_count") if conv.get("max_same_failure_count") is not None else budget.get("max_same_failure_count", 2)
        elif conv.get("max_same_failure_count") is not None and max_same_val == 2:
            max_same_val = conv.get("max_same_failure_count")

        def _opt_int(v: Any, default: Optional[int]) -> Optional[int]:
            if v is None:
                return default
            try:
                iv = int(v)
                return iv if iv >= 0 else None
            except (ValueError, TypeError):
                return default

        def _opt_float(v: Any, default: Optional[float]) -> Optional[float]:
            if v is None:
                return default
            try:
                fv = float(v)
                return fv if fv >= 0.0 else None
            except (ValueError, TypeError):
                return default

        return cls(
            max_tokens=_opt_int(budget.get("max_tokens"), 1_000_000),
            max_model_calls=_opt_int(budget.get("max_model_calls"), 100),
            max_turns=_opt_int(max_turns_val, 25),
            max_time_seconds=_opt_float(budget.get("max_time_seconds"), 1800.0),
            max_dollars=_opt_float(max_dollars_val, 10.0),
            max_tool_executions=_opt_int(budget.get("max_tool_executions"), 200),
            max_network_operations=_opt_int(budget.get("max_network_operations"), 50),
            max_remediation_attempts=int(budget.get("max_remediation_attempts", 3)),
            max_same_failures=int(max_same_val),
        )


@dataclass
class BudgetStatus:
    """Comprehensive evaluation status across all 7 resource dimensions."""
    is_exceeded: bool = False
    exceeded_metrics: List[str] = field(default_factory=list)
    usage: ResourceUsage = field(default_factory=ResourceUsage)
    budget: ChangeBudget = field(default_factory=ChangeBudget)
    details: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_exceeded": self.is_exceeded,
            "exceeded_metrics": self.exceeded_metrics,
            "usage": self.usage.to_dict(),
            "budget": self.budget.to_dict(),
            "details": self.details,
            "reason": self.reason,
        }


class ResourceGovernor:
    """Evaluates and enforces change resource governance limits."""

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)

    def _resolve_change_id(self, change_id: Optional[str] = None) -> str:
        if change_id:
            return change_id
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        return ledger.get("active_change_id") or "default"

    def get_budget(self, change_id: Optional[str] = None) -> ChangeBudget:
        """Retrieve the effective ChangeBudget for a change."""
        cid = self._resolve_change_id(change_id)
        from .config import ShipConfigManager
        global_cfg = ShipConfigManager.load(self.repo_root)

        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        ch = ledger.get("changes", {}).get(cid, {})
        ch_budget = ch.get("budget", {}).get("limits")

        if ch_budget:
            # Merge change-specific overrides onto global config
            merged = dict(global_cfg.get("budget", global_cfg.get("convergence", {})))
            merged.update(ch_budget)
            return ChangeBudget.from_dict(merged)

        return ChangeBudget.from_dict(global_cfg)

    def set_budget(
        self,
        change_id: str,
        budget: ChangeBudget,
        agent_id: str = "human",
        reason: str = "",
    ) -> None:
        """Set explicit resource limits for a change in the authoritative ledger."""
        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            ch = ledger.setdefault("changes", {}).setdefault(change_id, {})
            b_sec = ch.setdefault("budget", {})
            b_sec["limits"] = budget.to_dict()
            FileLedgerStore.save(self.repo_root, ledger)

        try:
            from .events import EventLogger
            EventLogger(self.repo_root).emit(
                event_type=EventType.BUDGET_UPDATED,
                change_id=change_id,
                agent_id=agent_id,
                session_id=f"sess-{agent_id}",
                target="budget",
                payload={"limits": budget.to_dict(), "reason": reason},
            )
        except Exception:
            pass

    def get_usage(
        self,
        change_id: Optional[str] = None,
        change_entry: Optional[Dict[str, Any]] = None,
    ) -> ResourceUsage:
        """Aggregate total resource consumption from recorded history and turns."""
        cid = self._resolve_change_id(change_id)
        entry = change_entry
        if entry is None:
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            entry = ledger.get("changes", {}).get(cid, {})

        if not isinstance(entry, dict):
            return ResourceUsage()

        # 1. Base consumption from explicit budget accumulator
        consumed_dict = entry.get("budget", {}).get("consumed", {})
        usage = ResourceUsage.from_dict(consumed_dict)

        # 2. Derive turns count and elapsed time if not already recorded
        turns = entry.get("turns", [])
        if len(turns) > usage.turns:
            usage.turns = len(turns)

        # 3. Calculate elapsed wall-clock time from turns or metadata
        if turns and usage.time_seconds <= 0.0:
            time_turns = [t for t in turns if "timestamp" in t]
            if time_turns:
                try:
                    ts_str = time_turns[0]["timestamp"].replace("Z", "+00:00")
                    first_time = datetime.fromisoformat(ts_str).timestamp()
                    now_time = datetime.now(timezone.utc).timestamp()
                    usage.time_seconds = max(0.0, now_time - first_time)
                except Exception:
                    pass

        # 4. Aggregate turn-level metrics (tokens, model_calls, dollars, tools, network)
        turn_tokens = 0
        turn_calls = 0
        turn_dollars = 0.0
        turn_tools = 0
        turn_network = 0

        for t in turns:
            ev = t.get("evidence", {}) if isinstance(t.get("evidence"), dict) else {}
            inp = t.get("inputs", {}) if isinstance(t.get("inputs"), dict) else {}
            met = t.get("metrics", {}) if isinstance(t.get("metrics"), dict) else {}

            # Cost / dollars
            cost_val = ev.get("cost_dollars") or inp.get("cost_dollars") or met.get("cost_dollars") or 0.0
            try:
                turn_dollars += float(cost_val)
            except (ValueError, TypeError):
                pass

            # Tokens
            tok_val = ev.get("tokens") or inp.get("tokens") or met.get("tokens") or 0
            try:
                turn_tokens += int(tok_val)
            except (ValueError, TypeError):
                pass

            # Model calls
            mc_val = ev.get("model_calls") or inp.get("model_calls") or met.get("model_calls") or 0
            try:
                turn_calls += int(mc_val)
            except (ValueError, TypeError):
                pass

            # Tool executions
            te_val = ev.get("tool_executions") or inp.get("tool_executions") or met.get("tool_executions") or 0
            try:
                turn_tools += int(te_val)
            except (ValueError, TypeError):
                pass

            # Network operations
            no_val = ev.get("network_operations") or inp.get("network_operations") or met.get("network_operations") or 0
            try:
                turn_network += int(no_val)
            except (ValueError, TypeError):
                pass

        # Merge turn aggregates: take maximum of explicit accumulator and turn sum
        usage.tokens = max(usage.tokens, turn_tokens)
        usage.model_calls = max(usage.model_calls, turn_calls)
        usage.dollars = max(usage.dollars, turn_dollars)
        usage.tool_executions = max(usage.tool_executions, turn_tools)
        usage.network_operations = max(usage.network_operations, turn_network)

        return usage

    def evaluate(
        self,
        change_id: Optional[str] = None,
        change_entry: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> BudgetStatus:
        """Evaluate resource usage against configured ceilings across all 7 dimensions."""
        cid = self._resolve_change_id(change_id)
        budget = (
            ChangeBudget.from_dict(config)
            if config
            else self.get_budget(cid)
        )
        usage = self.get_usage(change_id=cid, change_entry=change_entry)

        exceeded: List[str] = []
        details: Dict[str, Dict[str, Any]] = {}

        def _check_metric(name: str, current: Union[int, float], limit: Optional[Union[int, float]], unit: str = ""):
            is_exc = False
            pct = 0.0
            if limit is not None and limit > 0:
                pct = round((current / limit) * 100.0, 1)
                if current > limit or (isinstance(current, int) and current >= limit and current > 0):
                    is_exc = True
                    exceeded.append(name)
            details[name] = {
                "current": current,
                "limit": limit,
                "pct_used": pct,
                "exceeded": is_exc,
                "unit": unit,
            }

        _check_metric("tokens", usage.tokens, budget.max_tokens, "tokens")
        _check_metric("model_calls", usage.model_calls, budget.max_model_calls, "calls")
        _check_metric("turns", usage.turns, budget.max_turns, "turns")
        _check_metric("time", round(usage.time_seconds, 1), budget.max_time_seconds, "seconds")
        _check_metric("dollars", round(usage.dollars, 4), budget.max_dollars, "USD")
        _check_metric("tool_executions", usage.tool_executions, budget.max_tool_executions, "executions")
        _check_metric("network_operations", usage.network_operations, budget.max_network_operations, "operations")

        reason = ""
        if exceeded:
            reasons = []
            for m in exceeded:
                m_info = details[m]
                reasons.append(f"{m} limit exceeded ({m_info['current']} >= {m_info['limit']} {m_info['unit']})")
            reason = "; ".join(reasons)

        return BudgetStatus(
            is_exceeded=bool(exceeded),
            exceeded_metrics=exceeded,
            usage=usage,
            budget=budget,
            details=details,
            reason=reason,
        )

    def record_consumption(
        self,
        change_id: str,
        tokens: int = 0,
        model_calls: int = 0,
        dollars: float = 0.0,
        tool_executions: int = 0,
        network_operations: int = 0,
        turns: int = 0,
        time_seconds: float = 0.0,
        agent_id: str = "agent",
        reason: str = "",
    ) -> BudgetStatus:
        """Atomically record resource consumption and enforce halt if ceilings are breached."""
        now_iso = _now_iso()
        delta = {
            "tokens": max(0, tokens),
            "model_calls": max(0, model_calls),
            "dollars": max(0.0, dollars),
            "tool_executions": max(0, tool_executions),
            "network_operations": max(0, network_operations),
            "turns": max(0, turns),
            "time_seconds": max(0.0, time_seconds),
        }

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            ch = ledger.setdefault("changes", {}).setdefault(change_id, {})
            b_sec = ch.setdefault("budget", {})
            consumed = b_sec.setdefault("consumed", {})

            # Accumulate
            consumed["tokens"] = int(consumed.get("tokens", 0) or 0) + delta["tokens"]
            consumed["model_calls"] = int(consumed.get("model_calls", 0) or 0) + delta["model_calls"]
            consumed["dollars"] = round(float(consumed.get("dollars", 0.0) or 0.0) + delta["dollars"], 4)
            consumed["tool_executions"] = int(consumed.get("tool_executions", 0) or 0) + delta["tool_executions"]
            consumed["network_operations"] = int(consumed.get("network_operations", 0) or 0) + delta["network_operations"]
            consumed["turns"] = int(consumed.get("turns", 0) or 0) + delta["turns"]
            consumed["time_seconds"] = round(float(consumed.get("time_seconds", 0.0) or 0.0) + delta["time_seconds"], 2)

            # Record history
            hist = b_sec.setdefault("history", [])
            hist.append({
                "timestamp": now_iso,
                "agent_id": agent_id,
                "delta": delta,
                "reason": reason,
            })
            FileLedgerStore.save(self.repo_root, ledger)

        # Emit consumption event
        try:
            from .events import EventLogger
            EventLogger(self.repo_root).emit(
                event_type=EventType.RESOURCE_CONSUMED,
                change_id=change_id,
                agent_id=agent_id,
                session_id=f"sess-{agent_id}",
                target="budget",
                payload={"delta": delta, "reason": reason},
            )
        except Exception:
            pass

        # Evaluate status
        status = self.evaluate(change_id=change_id)

        # If exceeded, trigger halt
        if status.is_exceeded:
            try:
                from .convergence import halt_autonomy
                halt_autonomy(
                    repo_root=self.repo_root,
                    change_id=change_id,
                    reason=f"Resource ceiling breached: {status.reason}",
                    agent_id="resource-governor",
                )
            except Exception:
                pass

            try:
                from .events import EventLogger
                EventLogger(self.repo_root).emit(
                    event_type=EventType.BUDGET_EXCEEDED,
                    change_id=change_id,
                    agent_id="resource-governor",
                    session_id="sess-resource-governor",
                    target="budget",
                    payload={"reason": status.reason, "exceeded_metrics": status.exceeded_metrics},
                )
            except Exception:
                pass

        return status

    def check_action_budget(
        self,
        change_id: str,
        operation: str,
        target: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Pre-execution check: Verify if requested action is permissible under the active budget."""
        op = operation.upper()
        status = self.evaluate(change_id=change_id)
        budget = status.budget
        usage = status.usage

        # Check if already halted
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        ch = ledger.get("changes", {}).get(change_id, {})
        blockers = ch.get("blockers", [])
        halt_blockers = [b for b in blockers if b.startswith("Halt:")]
        if halt_blockers:
            return False, f"Workflow is halted: {halt_blockers[0].replace('Halt:', '').strip()}"

        # Check specific operation ceilings
        if op in ("NETWORK_READ", "NETWORK_WRITE"):
            if budget.max_network_operations is not None and usage.network_operations >= budget.max_network_operations:
                return False, f"Network operations budget exhausted ({usage.network_operations} >= {budget.max_network_operations})"

        if op in ("EXECUTE", "TEST"):
            if budget.max_tool_executions is not None and usage.tool_executions >= budget.max_tool_executions:
                return False, f"Tool executions budget exhausted ({usage.tool_executions} >= {budget.max_tool_executions})"

        if budget.max_dollars is not None and usage.dollars >= budget.max_dollars:
            return False, f"Financial dollar ceiling exhausted (${usage.dollars:.2f} >= ${budget.max_dollars:.2f})"

        return True, "OK"

    def format_budget_report(self, change_id: Optional[str] = None) -> str:
        """Format an ASCII/Unicode scorecard showing usage across all 7 dimensions."""
        cid = self._resolve_change_id(change_id)
        status = self.evaluate(cid)
        usage = status.usage
        budget = status.budget

        lines = [
            "═" * 78,
            f" 💰 CHANGE RESOURCE BUDGET REPORT: '{cid}'",
            "═" * 78,
            f" Status: {'⛔ EXCEEDED / HALTED' if status.is_exceeded else '✅ WITHIN BUDGET'}",
        ]
        if status.is_exceeded:
            lines.append(f" Halt Trigger: {status.reason}")
        lines.append("─" * 78)
        lines.append(f" {'Resource Dimension':<22} {'Consumed':<16} {'Ceiling':<16} {'% Used':<10} {'Status':<10}")
        lines.append("─" * 78)

        def _fmt_row(name: str, consumed_str: str, limit_str: str, pct: float, exc: bool):
            stat_icon = "❌ EXCEEDED" if exc else "✅ OK"
            lines.append(f" {name:<22} {consumed_str:<16} {limit_str:<16} {f'{pct:.1f}%':<10} {stat_icon:<10}")

        d = status.details
        _fmt_row("1. Tokens", f"{usage.tokens:,}", f"{budget.max_tokens:,}" if budget.max_tokens else "unlimited", d["tokens"]["pct_used"], d["tokens"]["exceeded"])
        _fmt_row("2. Model Calls", f"{usage.model_calls:,}", f"{budget.max_model_calls:,}" if budget.max_model_calls else "unlimited", d["model_calls"]["pct_used"], d["model_calls"]["exceeded"])
        _fmt_row("3. Turns", f"{usage.turns}", f"{budget.max_turns}" if budget.max_turns else "unlimited", d["turns"]["pct_used"], d["turns"]["exceeded"])
        _fmt_row("4. Time (Seconds)", f"{usage.time_seconds:.1f}s", f"{budget.max_time_seconds:.1f}s" if budget.max_time_seconds else "unlimited", d["time"]["pct_used"], d["time"]["exceeded"])
        _fmt_row("5. Dollars (USD)", f"${usage.dollars:.4f}", f"${budget.max_dollars:.2f}" if budget.max_dollars else "unlimited", d["dollars"]["pct_used"], d["dollars"]["exceeded"])
        _fmt_row("6. Tool Executions", f"{usage.tool_executions}", f"{budget.max_tool_executions}" if budget.max_tool_executions else "unlimited", d["tool_executions"]["pct_used"], d["tool_executions"]["exceeded"])
        _fmt_row("7. Network Ops", f"{usage.network_operations}", f"{budget.max_network_operations}" if budget.max_network_operations else "unlimited", d["network_operations"]["pct_used"], d["network_operations"]["exceeded"])

        lines.append("═" * 78)
        return "\n".join(lines)
