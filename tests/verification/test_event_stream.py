"""Comprehensive tests for the Execution/Event Log forensic audit trail and cryptographic hash chaining."""

import json
from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.capabilities import CapabilityManager
from ship.lifecycle.events import EventLogger, GENESIS_PREV_HASH, compute_event_hash
from ship.lifecycle.models import CapabilityOperation, EventType, ExecutionEvent
from ship.lifecycle.paths import get_event_log_file


class TestExecutionEventStream(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.event_file = get_event_log_file(self.repo_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_genesis_event_and_hash_chaining(self):
        """Test that events are appended with correct prev_event_hash and SHA-256 event_hash chaining."""
        logger = EventLogger(self.repo_root)

        e1 = logger.emit(
            event_type=EventType.AGENT_STARTED,
            agent_id="agent-007",
            session_id="sess-007",
            payload={"role": "maker"},
        )
        self.assertEqual(e1.prev_event_hash, GENESIS_PREV_HASH)
        self.assertEqual(len(e1.event_hash), 64)
        self.assertEqual(e1.event_hash, compute_event_hash(e1))

        e2 = logger.emit(
            event_type=EventType.TASK_CLAIMED,
            change_id="feat-auth",
            agent_id="agent-007",
            task_id="task-1",
            payload={"task_name": "Implement JWT"},
        )
        self.assertEqual(e2.prev_event_hash, e1.event_hash)
        self.assertEqual(e2.event_hash, compute_event_hash(e2))

        e3 = logger.emit(
            event_type=EventType.TEST_EXECUTED,
            change_id="feat-auth",
            agent_id="engine",
            target="pytest tests/",
            payload={"exit_code": 0, "passed": True},
        )
        self.assertEqual(e3.prev_event_hash, e2.event_hash)
        self.assertEqual(e3.event_hash, compute_event_hash(e3))

        # Check file contents
        self.assertTrue(self.event_file.exists())
        events = logger.read_all()
        self.assertEqual(len(events), 3)
        self.assertEqual([e.event_type for e in events], [
            EventType.AGENT_STARTED.value,
            EventType.TASK_CLAIMED.value,
            EventType.TEST_EXECUTED.value,
        ])

        # Verify integrity succeeds
        valid, msg, broken_idx = logger.verify_integrity()
        self.assertTrue(valid)
        self.assertIn("verified successfully", msg)
        self.assertIsNone(broken_idx)

    def test_query_and_tail(self):
        """Test filtering events by change, type, agent, and tailing."""
        logger = EventLogger(self.repo_root)

        logger.emit(EventType.AGENT_STARTED, agent_id="agent-1", change_id="c1")
        logger.emit(EventType.TASK_CLAIMED, agent_id="agent-1", change_id="c1", task_id="t1")
        logger.emit(EventType.AGENT_STARTED, agent_id="agent-2", change_id="c2")
        logger.emit(EventType.TEST_EXECUTED, agent_id="engine", change_id="c1")

        # Query by change_id
        c1_events = logger.query(change_id="c1")
        self.assertEqual(len(c1_events), 3)

        # Query by agent_id
        a2_events = logger.query(agent_id="agent-2")
        self.assertEqual(len(a2_events), 1)
        self.assertEqual(a2_events[0].change_id, "c2")

        # Query by event_type
        start_events = logger.query(event_type=EventType.AGENT_STARTED)
        self.assertEqual(len(start_events), 2)

        # Tail
        tail_2 = logger.tail(2)
        self.assertEqual(len(tail_2), 2)
        self.assertEqual(tail_2[-1].event_type, EventType.TEST_EXECUTED.value)

    def test_tamper_detection_modified_payload(self):
        """Adversarial Attack: Malicious agent alters an event line in events.jsonl to hide test failure."""
        logger = EventLogger(self.repo_root)

        logger.emit(EventType.AGENT_STARTED, agent_id="agent-1")
        logger.emit(EventType.TEST_EXECUTED, agent_id="engine", payload={"exit_code": 1, "passed": False})
        logger.emit(EventType.VERIFICATION_FAILED, agent_id="verifier", payload={"verdict": "NOT_VERIFIED"})

        # Tamper with the 2nd line: change exit_code from 1 to 0 and passed to True
        lines = self.event_file.read_text(encoding="utf-8").strip().splitlines()
        tampered_data = json.loads(lines[1])
        tampered_data["payload"]["exit_code"] = 0
        tampered_data["payload"]["passed"] = True
        lines[1] = json.dumps(tampered_data)
        self.event_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Verify integrity must detect tampering at event index 1 (evt-000002)
        valid, msg, broken_idx = logger.verify_integrity()
        self.assertFalse(valid)
        self.assertEqual(broken_idx, "evt-000002")
        self.assertIn("Tampered event payload", msg)

    def test_tamper_detection_deleted_event(self):
        """Adversarial Attack: Malicious agent deletes an incriminating event line."""
        logger = EventLogger(self.repo_root)

        logger.emit(EventType.AGENT_STARTED, agent_id="agent-1")
        logger.emit(EventType.ACTION_DENIED, agent_id="agent-1", payload={"blocked": "Ring 0 violation"})
        logger.emit(EventType.AGENT_STOPPED, agent_id="agent-1")

        # Delete line 1 (the ACTION_DENIED event)
        lines = self.event_file.read_text(encoding="utf-8").strip().splitlines()
        del lines[1]
        self.event_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Verify integrity must detect broken chain linkage at line that followed
        valid, msg, broken_idx = logger.verify_integrity()
        self.assertFalse(valid)
        self.assertEqual(broken_idx, "evt-000003")
        self.assertIn("Hash chain broken", msg)

    def test_tamper_detection_inserted_fake_event(self):
        """Adversarial Attack: Malicious agent injects an unauthorized event into the stream."""
        logger = EventLogger(self.repo_root)

        logger.emit(EventType.AGENT_STARTED, agent_id="agent-1")
        logger.emit(EventType.VERIFICATION_PASSED, agent_id="verifier")

        # Inject fake event
        fake_event = ExecutionEvent(
            event_id="evt-fake",
            event_type=EventType.APPROVAL_GRANTED.value,
            timestamp="2026-01-01T00:00:00Z",
            change_id="c-test",
            agent_id="human-boss",
            payload={"override": True},
            prev_event_hash="fakehash",
            event_hash="fakehash2",
        )
        lines = self.event_file.read_text(encoding="utf-8").strip().splitlines()
        lines.insert(1, json.dumps(fake_event.to_dict()))
        self.event_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Verify integrity must detect broken hash
        valid, msg, broken_idx = logger.verify_integrity()
        self.assertFalse(valid)
        self.assertEqual(broken_idx, "evt-fake")

    def test_ring0_protects_event_log(self):
        """Verify that .agentflow/events.jsonl is categorized as Ring 0 (system immutable)."""
        from ship.lifecycle.provenance import ProvenanceManager

        prov_mgr = ProvenanceManager(self.repo_root)
        prov_mgr.register_identity(agent_id="agent-rogue", role="maker")

        manager = CapabilityManager(self.repo_root)

        # Autonomous WRITE or DELETE to .agentflow/events.jsonl must be denied under Ring 0
        decision = manager.evaluate_access(
            agent_id="agent-rogue",
            operation=CapabilityOperation.WRITE,
            target=".agentflow/events.jsonl",
        )
        self.assertFalse(decision.allowed)
        self.assertIn("Ring 0", decision.reason)

        decision = manager.evaluate_access(
            agent_id="agent-rogue",
            operation=CapabilityOperation.DELETE,
            target=".agentflow/events.jsonl",
        )
        self.assertFalse(decision.allowed)
        self.assertIn("Ring 0", decision.reason)

    def test_cli_events_integration(self):
        """Test agentflow events CLI list, tail, and verify commands."""
        from ship.cli import main as cli_main

        logger = EventLogger(self.repo_root)
        logger.emit(EventType.AGENT_STARTED, agent_id="agent-test", change_id="c-test")
        logger.emit(EventType.TASK_CLAIMED, agent_id="agent-test", change_id="c-test", task_id="t-1")

        # 1. agentflow events verify -> exit 0
        exit_code = cli_main(["events", "verify", "--path", str(self.repo_root)])
        self.assertEqual(exit_code, 0)

        # 2. agentflow events list -> exit 0
        exit_code = cli_main(["events", "list", "--path", str(self.repo_root)])
        self.assertEqual(exit_code, 0)

        # 3. agentflow events tail -n 1 -> exit 0
        exit_code = cli_main(["events", "tail", "-n", "1", "--path", str(self.repo_root)])
        self.assertEqual(exit_code, 0)

        # 4. Tamper and check verify exits 1
        lines = self.event_file.read_text(encoding="utf-8").strip().splitlines()
        lines[0] = lines[0].replace("agent-test", "agent-tampered")
        self.event_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        exit_code = cli_main(["events", "verify", "--path", str(self.repo_root)])
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
