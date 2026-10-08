"""Tests for the Audit Trail Anchoring, Rotation, and Tamper-Evidence Engine."""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.anchoring import (
    AuditAnchorManager,
)
from ship.lifecycle.events import EventLogger


class TestAuditTrailAnchoring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.logger = EventLogger(self.root)
        self.anchor_mgr = AuditAnchorManager(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_anchor_creation_and_file_verification(self):
        """Emit events, create an anchor, and verify it successfully against the event file."""
        self.logger.emit(event_type="SKILL_RUN_STARTED", payload={"skill": "ship"})
        self.logger.emit(event_type="STEP_STARTED", payload={"step": "design"})
        self.logger.emit(event_type="STEP_COMPLETED", payload={"step": "design"})

        anchor = self.anchor_mgr.create_anchor(metadata={"env": "test"})
        self.assertIsNotNone(anchor.anchor_id)
        self.assertEqual(anchor.event_count, 3)
        self.assertTrue(len(anchor.file_sha256) == 64)

        # Verification should pass
        valid, msg, rec = self.anchor_mgr.verify_latest_anchor()
        self.assertTrue(valid, msg)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.anchor_id, anchor.anchor_id)

    def test_anchor_detects_tampered_event_log(self):
        """Modifying the events.jsonl file causes anchor verification to fail."""
        self.logger.emit(event_type="SKILL_RUN_STARTED", payload={"skill": "review"})
        self.logger.emit(event_type="STEP_COMPLETED", payload={"step": "review"})

        self.anchor_mgr.create_anchor()
        self.assertTrue(self.anchor_mgr.verify_latest_anchor()[0])

        # Tamper with the event log by appending or modifying a character
        event_file = self.root / ".agentflow" / "events.jsonl"
        with event_file.open("a", encoding="utf-8") as f:
            f.write("tampered\n")

        valid, msg, rec = self.anchor_mgr.verify_latest_anchor()
        self.assertFalse(valid)
        self.assertIn("Anchor verification failed", msg)

    def test_log_rotation_and_archive_chain(self):
        """Log rotation archives old log, publishes anchor, and creates chained rotation checkpoint."""
        for i in range(10):
            self.logger.emit(event_type="STEP_COMPLETED", payload={"step": f"step-{i}"})

        # Rotate with max_events=5
        archive_path = self.anchor_mgr.rotate_event_log(max_events=5)
        self.assertIsNotNone(archive_path)
        self.assertTrue(archive_path.exists())

        # Old log is moved into archive
        self.assertTrue("events." in archive_path.name)

        # New event log exists and starts with CHECKPOINT_CREATED referencing archive
        events = self.logger.read_all()
        self.assertEqual(len(events), 1)
        first = events[0]
        self.assertEqual(first.event_type, "CHECKPOINT_CREATED")
        self.assertTrue(first.payload.get("rotation"))
        self.assertEqual(first.payload.get("archived_events_count"), 10)


if __name__ == "__main__":
    unittest.main()
