"""Migration and schema version compatibility tests."""

import json
from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.config import ShipConfigManager
from ship.lifecycle.ledger import FileLedgerStore, read_ledger_file
from ship.lifecycle.resources import ResourceGovernor, ChangeBudget
from ship.lifecycle.paths import get_state_file


class TestMigrationCompatibility(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name).resolve()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_legacy_v0_minimal_ledger_loads_cleanly(self):
        """Minimal legacy ledger (without budget, coordination, approvals, capabilities) loads without error."""
        legacy_data = {
            "version": 1,
            "active_change_id": "legacy-change",
            "changes": {
                "legacy-change": {
                    "phase": "INITIAL_PROPOSAL",
                    "turns": [],
                    "blockers": [],
                }
            }
        }
        ledger_path = get_state_file(self.repo_root)
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json.dumps(legacy_data), encoding="utf-8")

        loaded = FileLedgerStore.load(self.repo_root, auto_sync=False)
        self.assertEqual(loaded["version"], 1)
        self.assertEqual(loaded["active_change_id"], "legacy-change")

        # Resource governor resolves safe defaults for legacy change
        gov = ResourceGovernor(self.repo_root)
        budget = gov.get_budget("legacy-change")
        self.assertEqual(budget.max_tokens, 1_000_000)
        self.assertEqual(budget.max_turns, 25)

        usage = gov.get_usage("legacy-change")
        self.assertEqual(usage.tokens, 0)
        self.assertEqual(usage.model_calls, 0)

    def test_legacy_agentflow_json_manifest_compatibility(self):
        """Legacy .agentflow.json without budget block falls back to convergence defaults."""
        manifest = {
            "version": 1,
            "project": {"name": "legacy-app"},
            "convergence": {
                "max_total_turns": 30,
                "max_cost_dollars": 15.0,
            }
        }
        cfg_file = self.repo_root / ".agentflow.json"
        cfg_file.write_text(json.dumps(manifest), encoding="utf-8")

        cfg = ShipConfigManager.load(self.repo_root)
        self.assertEqual(cfg["convergence"]["max_total_turns"], 30)
        self.assertEqual(cfg["convergence"]["max_cost_dollars"], 15.0)

        budget = ChangeBudget.from_dict(cfg)
        self.assertEqual(budget.max_turns, 30)
        self.assertEqual(budget.max_dollars, 15.0)

    def test_future_unsupported_version_rejected(self):
        """Ledger with future unsupported schema version (e.g. version 2) is rejected cleanly."""
        future_data = {
            "version": 2,
            "changes": {},
        }
        ledger_path = get_state_file(self.repo_root)
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json.dumps(future_data), encoding="utf-8")

        with self.assertRaises(ValueError) as ctx:
            read_ledger_file(ledger_path)
        self.assertIn("Invalid ledger schema", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
