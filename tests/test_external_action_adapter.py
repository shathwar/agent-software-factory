import tempfile
import unittest
from pathlib import Path

from ship.lifecycle.capabilities import CapabilityManager
from ship.lifecycle.execution import ActionContext, CapabilityDenied, ExternalActionAdapter
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.provenance import ProvenanceManager


class TestExternalActionAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.change = "external-change"
        FileLedgerStore.save(self.root, {"version": 1, "active_change_id": self.change, "changes": {self.change: {}}})
        ProvenanceManager(self.root).register_identity("agent-1", role="MAKER", change_id=self.change)
        self.adapter = ExternalActionAdapter(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_denied_network_never_invokes_provider(self):
        called = []
        with self.assertRaises(CapabilityDenied):
            self.adapter.network(
                ActionContext("agent-1", "NETWORK_WRITE", "https://evil.example/*", self.change),
                lambda: called.append(True),
            )
        self.assertEqual(called, [])

    def test_approved_secret_invokes_provider(self):
        CapabilityManager(self.root).grant_capability(
            "agent-1", "SECRET_READ", "secret:token", change_id=self.change, approval_ref="sec_lead:audit"
        )
        result = self.adapter.secret(
            ActionContext("agent-1", "SECRET_READ", "secret:token", self.change),
            lambda: "value",
        )
        self.assertEqual(result, "value")

    def test_operation_specific_methods_reject_wrong_operation(self):
        with self.assertRaises(ValueError):
            self.adapter.github(ActionContext("agent-1", "NETWORK_WRITE", "github:pr:merge", self.change), lambda: None)


if __name__ == "__main__":
    unittest.main()
