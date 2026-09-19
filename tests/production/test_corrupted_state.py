"""Corrupted state, damaged ledger, and broken hash chain recovery tests."""

import json
from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.events import EventLogger
from ship.lifecycle.ledger import FileLedgerStore, read_ledger_file
from ship.lifecycle.paths import get_state_file, get_event_log_file


class TestCorruptedState(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name).resolve()
        self.ledger_file = get_state_file(self.repo_root)
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_syntactically_invalid_json_ledger_raises_error(self):
        """Corrupted JSON with syntax errors is never silently parsed or overwritten."""
        self.ledger_file.write_text('{"version": 1, "changes": { "incomplete": ', encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            read_ledger_file(self.ledger_file)
        self.assertIn("Cannot read ledger", str(ctx.exception))
        self.assertIn("preserved unchanged", str(ctx.exception))

    def test_schema_violation_in_ledger_raises_error(self):
        """Ledger with wrong data types or schema corruption is caught and rejected."""
        corruptions = [
            '{"version": 2, "changes": {}}',  # Unsupported future version
            '{"version": 1, "changes": "not_a_dict"}',  # changes must be dict
            '{"version": 1, "changes": {"c1": {"blockers": "not_a_list"}}}',  # blockers must be list
            '{"version": 1, "changes": {"c1": {"revision_counter": -5}}}',  # negative revision
            '{"version": 1, "changes": {"c1": {"turns": ["not_a_dict"]}}}',  # turns must be dicts
        ]
        for c in corruptions:
            self.ledger_file.write_text(c, encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                read_ledger_file(self.ledger_file)
            self.assertIn("Invalid ledger schema", str(ctx.exception))

    def test_corrupted_event_stream_detected(self):
        """Any modified byte or deleted line in event log is caught by verify_integrity."""
        logger = EventLogger(self.repo_root)
        logger.emit("AGENT_STARTED", change_id="c1", agent_id="maker-1")
        logger.emit("TASK_CLAIMED", change_id="c1", agent_id="maker-1", task_id="t1")
        logger.emit("FILE_MODIFIED", change_id="c1", agent_id="maker-1", target="src/a.py")

        # Baseline: valid
        valid, msg, _ = logger.verify_integrity()
        self.assertTrue(valid)

        # Mutate event 2
        event_file = get_event_log_file(self.repo_root)
        lines = event_file.read_text(encoding="utf-8").splitlines()
        d = json.loads(lines[1])
        d["payload"]["tampered"] = True
        lines[1] = json.dumps(d)
        event_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Verification must catch tampering
        valid, msg, broken_id = logger.verify_integrity()
        self.assertFalse(valid)
        self.assertIn("Tampered event payload", msg)
        self.assertEqual(broken_id, d["event_id"])


if __name__ == "__main__":
    unittest.main()
