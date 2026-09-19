"""Unit and attack tests for Resource & Budget Governance in AgentFlow.

Tests all 7 core resource dimensions:
  1. Tokens
  2. Model calls
  3. Turns
  4. Time
  5. Dollars
  6. Tool executions
  7. Network operations
"""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.capabilities import CapabilityManager
from ship.lifecycle.convergence import evaluate_convergence
from ship.lifecycle.events import EventLogger
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.models import EventType
from ship.lifecycle.resources import (
    ChangeBudget,
    ResourceGovernor,
)
from ship.cli import main as cli_main


class TestResourceGovernance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "test-budget-change"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {
                self.change_id: {
                    "turns": [],
                    "blockers": [],
                    "budget": {
                        "limits": {},
                        "consumed": {},
                        "history": [],
                    },
                    "provenance": {
                        "identities": {
                            "agent-worker": {"agent_id": "agent-worker", "role": "maker"},
                        },
                        "sessions": {
                            "sess-1": {"session_id": "sess-1", "agent_id": "agent-worker", "active": True},
                        },
                    },
                    "capabilities": {},
                    "coordination": {"leases": {}},
                }
            },
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_budget_initialization(self):
        """Verifies standard default ceilings across all 7 dimensions."""
        budget = ChangeBudget()
        self.assertEqual(budget.max_tokens, 1_000_000)
        self.assertEqual(budget.max_model_calls, 100)
        self.assertEqual(budget.max_turns, 25)
        self.assertEqual(budget.max_time_seconds, 1800.0)
        self.assertEqual(budget.max_dollars, 10.0)
        self.assertEqual(budget.max_tool_executions, 200)
        self.assertEqual(budget.max_network_operations, 50)
        self.assertEqual(budget.max_remediation_attempts, 3)
        self.assertEqual(budget.max_same_failures, 2)

    def test_record_consumption_and_accrual(self):
        """Verifies that record_consumption accumulates metrics and records audit history."""
        gov = ResourceGovernor(self.repo_root)
        status = gov.record_consumption(
            change_id=self.change_id,
            tokens=1500,
            model_calls=2,
            dollars=0.03,
            tool_executions=4,
            network_operations=1,
            agent_id="agent-worker",
            reason="Step 1 implementation",
        )
        self.assertFalse(status.is_exceeded)
        self.assertEqual(status.usage.tokens, 1500)
        self.assertEqual(status.usage.model_calls, 2)
        self.assertAlmostEqual(status.usage.dollars, 0.03, places=4)
        self.assertEqual(status.usage.tool_executions, 4)
        self.assertEqual(status.usage.network_operations, 1)

        # Record secondary consumption
        status2 = gov.record_consumption(
            change_id=self.change_id,
            tokens=3500,
            model_calls=1,
            dollars=0.07,
            tool_executions=2,
            network_operations=3,
            agent_id="agent-worker",
            reason="Step 2 testing",
        )
        self.assertFalse(status2.is_exceeded)
        self.assertEqual(status2.usage.tokens, 5000)
        self.assertEqual(status2.usage.model_calls, 3)
        self.assertAlmostEqual(status2.usage.dollars, 0.10, places=4)
        self.assertEqual(status2.usage.tool_executions, 6)
        self.assertEqual(status2.usage.network_operations, 4)

        # Verify event stream
        logger = EventLogger(self.repo_root)
        events = logger.tail(n=10, change_id=self.change_id)
        consumed_events = [e for e in events if e.event_type == EventType.RESOURCE_CONSUMED.value]
        self.assertEqual(len(consumed_events), 2)

    def test_token_ceiling_halts_autonomy(self):
        """Verifies that exceeding max_tokens halts autonomy with BUDGET_EXCEEDED."""
        gov = ResourceGovernor(self.repo_root)
        gov.set_budget(self.change_id, ChangeBudget(max_tokens=10_000))

        # Record below ceiling
        s1 = gov.record_consumption(self.change_id, tokens=9_000)
        self.assertFalse(s1.is_exceeded)

        # Breach ceiling
        s2 = gov.record_consumption(self.change_id, tokens=2_000)
        self.assertTrue(s2.is_exceeded)
        self.assertIn("tokens", s2.exceeded_metrics)

        # Verify ledger has halt blocker
        ledger = FileLedgerStore.load(self.repo_root)
        ch = ledger["changes"][self.change_id]
        halt_blockers = [b for b in ch["blockers"] if b.startswith("Halt:")]
        self.assertTrue(len(halt_blockers) > 0)
        self.assertIn("Resource ceiling breached", halt_blockers[0])

        # Verify convergence evaluation halts
        conv_status = evaluate_convergence(ch)
        self.assertTrue(conv_status.is_halted)

    def test_model_calls_ceiling_halts_autonomy(self):
        """Verifies that exceeding max_model_calls halts autonomy."""
        gov = ResourceGovernor(self.repo_root)
        gov.set_budget(self.change_id, ChangeBudget(max_model_calls=5))

        gov.record_consumption(self.change_id, model_calls=5)
        status = gov.evaluate(self.change_id)
        self.assertTrue(status.is_exceeded)
        self.assertIn("model_calls", status.exceeded_metrics)

    def test_tool_executions_ceiling_halts_autonomy(self):
        """Verifies that exceeding max_tool_executions halts autonomy."""
        gov = ResourceGovernor(self.repo_root)
        gov.set_budget(self.change_id, ChangeBudget(max_tool_executions=10))

        gov.record_consumption(self.change_id, tool_executions=12)
        status = gov.evaluate(self.change_id)
        self.assertTrue(status.is_exceeded)
        self.assertIn("tool_executions", status.exceeded_metrics)

    def test_network_operations_ceiling_halts_autonomy(self):
        """Verifies that exceeding max_network_operations halts autonomy."""
        gov = ResourceGovernor(self.repo_root)
        gov.set_budget(self.change_id, ChangeBudget(max_network_operations=3))

        gov.record_consumption(self.change_id, network_operations=4)
        status = gov.evaluate(self.change_id)
        self.assertTrue(status.is_exceeded)
        self.assertIn("network_operations", status.exceeded_metrics)

    def test_dollars_cost_ceiling_halts_autonomy(self):
        """Verifies that financial cost ceiling halts autonomy."""
        gov = ResourceGovernor(self.repo_root)
        gov.set_budget(self.change_id, ChangeBudget(max_dollars=5.00))

        gov.record_consumption(self.change_id, dollars=6.50)
        status = gov.evaluate(self.change_id)
        self.assertTrue(status.is_exceeded)
        self.assertIn("dollars", status.exceeded_metrics)

    def test_capability_denial_when_budget_exhausted(self):
        """Attack: Agent attempts network/tool operations when resource budget is exhausted."""
        gov = ResourceGovernor(self.repo_root)
        gov.set_budget(self.change_id, ChangeBudget(max_network_operations=2, max_tool_executions=5))

        cap_mgr = CapabilityManager(self.repo_root)
        # Grant network capability
        cap_mgr.grant_capability(
            agent_id="agent-worker",
            operation="NETWORK_READ",
            target="https://api.github.com/*",
            approval_ref="human:sec_lead",
            change_id=self.change_id,
        )

        # Before budget breach: allowed
        dec1 = cap_mgr.evaluate_access(
            agent_id="agent-worker",
            operation="NETWORK_READ",
            target="https://api.github.com/repos",
            change_id=self.change_id,
        )
        self.assertTrue(dec1.allowed)

        # Exhaust network operations budget
        gov.record_consumption(self.change_id, network_operations=2)

        # After budget breach: mechanically denied
        dec2 = cap_mgr.evaluate_access(
            agent_id="agent-worker",
            operation="NETWORK_READ",
            target="https://api.github.com/repos",
            change_id=self.change_id,
        )
        self.assertFalse(dec2.allowed)
        self.assertEqual(dec2.violation_code, "BUDGET_EXCEEDED")
        self.assertTrue("budget" in dec2.reason.lower() or "limit exceeded" in dec2.reason.lower())

    def test_cli_budget_commands(self):
        """Verifies CLI subcommands: agentflow budget show, set, record, check."""
        # 1. Budget set
        code_set = cli_main([
            "budget", "set",
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--tokens", "50000",
            "--dollars", "2.50",
            "--network", "10",
        ])
        self.assertEqual(code_set, 0)

        # 2. Budget record
        code_rec = cli_main([
            "budget", "record",
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--tokens", "12000",
            "--dollars", "0.50",
            "--network", "2",
            "--reason", "Test run",
        ])
        self.assertEqual(code_rec, 0)

        # 3. Budget check (should pass)
        code_chk = cli_main([
            "budget", "check",
            "--path", str(self.repo_root),
            "--change", self.change_id,
        ])
        self.assertEqual(code_chk, 0)

        # 4. Budget show
        code_show = cli_main([
            "budget", "show",
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--json",
        ])
        self.assertEqual(code_show, 0)

        # 5. Overspend via CLI record
        code_over = cli_main([
            "budget", "record",
            "--path", str(self.repo_root),
            "--change", self.change_id,
            "--tokens", "45000",  # Total 57000 > 50000
        ])
        self.assertEqual(code_over, 1)

        # 6. Budget check (should now fail with exit code 1)
        code_chk_fail = cli_main([
            "budget", "check",
            "--path", str(self.repo_root),
            "--change", self.change_id,
        ])
        self.assertEqual(code_chk_fail, 1)

    def test_backward_compatibility_with_convergence_config(self):
        """Verifies that legacy convergence dict without budget block is seamlessly parsed."""
        legacy_data = {
            "convergence": {
                "max_total_turns": 15,
                "max_cost_dollars": 8.50,
                "max_same_failure_count": 3,
            }
        }
        b = ChangeBudget.from_dict(legacy_data)
        self.assertEqual(b.max_turns, 15)
        self.assertEqual(b.max_dollars, 8.50)
        self.assertEqual(b.max_same_failures, 3)
        # Default ceilings retained
        self.assertEqual(b.max_tokens, 1_000_000)
        self.assertEqual(b.max_tool_executions, 200)
        self.assertEqual(b.max_network_operations, 50)


if __name__ == "__main__":
    unittest.main()
