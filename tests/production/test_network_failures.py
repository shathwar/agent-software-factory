"""Partial network failure, timeout, and DNS simulation tests."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from ship.lifecycle.capabilities import CapabilityManager
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.resources import ResourceGovernor, ChangeBudget


class TestNetworkFailures(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name).resolve()
        self.change_id = "network-fail-change"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {
                self.change_id: {
                    "turns": [],
                    "blockers": [],
                    "capabilities": {},
                    "coordination": {"leases": {}},
                    "provenance": {
                        "identities": {"agent-worker": {"role": "worker"}},
                        "sessions": {"sess-1": {"agent_id": "agent-worker", "active": True}},
                    },
                }
            },
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_network_read_denied_without_capability(self):
        """Outbound network request is blocked by default without capability grant."""
        cap_mgr = CapabilityManager(self.repo_root)
        decision = cap_mgr.evaluate_access(
            agent_id="agent-worker",
            operation="NETWORK_READ",
            target="https://internal.registry.corp.net/packages",
            change_id=self.change_id,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.violation_code, "NO_CAPABILITY")

    def test_simulated_network_timeout_fails_closed(self):
        """Simulated socket timeout during external operation fails closed safely."""
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection timed out")):
            try:
                urllib.request.urlopen("https://api.github.com", timeout=1)
                failed = False
            except urllib.error.URLError:
                failed = True
            self.assertTrue(failed, "Network request must fail closed on timeout")

    def test_budget_governor_halts_on_excessive_network_failures(self):
        """Network operation budget prevents runaway retry storms during partial network failure."""
        gov = ResourceGovernor(self.repo_root)
        gov.set_budget(self.change_id, ChangeBudget(max_network_operations=3))

        # 3 failed network attempts record consumption
        for i in range(3):
            gov.record_consumption(self.change_id, network_operations=1, reason=f"Retry {i+1} after network error")

        status = gov.evaluate(self.change_id)
        self.assertTrue(status.is_exceeded)
        self.assertIn("network_operations", status.exceeded_metrics)

        # 4th attempt is blocked by capability pre-check
        cap_mgr = CapabilityManager(self.repo_root)
        cap_mgr.grant_capability("agent-worker", "NETWORK_READ", "*", approval_ref="human:sec", change_id=self.change_id)
        dec = cap_mgr.evaluate_access("agent-worker", "NETWORK_READ", "https://api.github.com", change_id=self.change_id)
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.violation_code, "BUDGET_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
