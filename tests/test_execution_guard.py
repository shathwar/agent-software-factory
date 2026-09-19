import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from ship.lifecycle.execution import ActionContext, CapabilityDenied, CapabilityGuard
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.provenance import ProvenanceManager


class TestExecutionGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.change = "guard-change"
        FileLedgerStore.save(self.root, {"version": 1, "active_change_id": self.change, "changes": {self.change: {}}})
        ProvenanceManager(self.root).register_identity("agent-1", role="MAKER", change_id=self.change)
        self.guard = CapabilityGuard(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_denied_action_raises_before_adapter(self):
        with self.assertRaises(CapabilityDenied) as raised:
            self.guard.require(ActionContext("agent-1", "NETWORK_WRITE", "https://evil.example/*", self.change))
        self.assertEqual(raised.exception.decision.violation_code, "NO_CAPABILITY")

    def test_scoped_action_is_allowed(self):
        from ship.lifecycle.capabilities import CapabilityManager
        CapabilityManager(self.root).grant_capability(
            "agent-1", "NETWORK_READ", "https://pypi.org/*", change_id=self.change
        )
        decision = self.guard.require(ActionContext("agent-1", "NETWORK_READ", "https://pypi.org/simple/x", self.change))
        self.assertTrue(decision.allowed)

    def test_mcp_command_is_rejected_before_side_effect(self):
        from ship.mcp.tools import dispatch_tool
        marker = self.root / "should-not-exist"
        with patch.dict("os.environ", {"AGENTFLOW_MCP_ALLOW_MUTATIONS": "1"}):
            with self.assertRaises(PermissionError):
                dispatch_tool("ship_spike_run", {
                    "path": str(self.root), "command": f"touch {marker}",
                })
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
