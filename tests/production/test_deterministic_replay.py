"""Deterministic event stream replay tests.

Verifies that the entire authoritative ledger state of a change can be
reconstructed and verified bit-for-bit from the append-only cryptographic event log.
"""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.events import EventLogger, EventReplayer
from ship.lifecycle.ledger import FileLedgerStore
from ship.cli import main as cli_main


class TestDeterministicReplay(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name).resolve()
        self.change_id = "replay-change"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {
                self.change_id: {
                    "turns": [],
                    "blockers": [],
                    "budget": {
                        "limits": {"max_tokens": 500000},
                        "consumed": {
                            "tokens": 1500,
                            "model_calls": 2,
                            "turns": 0,
                            "time_seconds": 0.0,
                            "dollars": 0.05,
                            "tool_executions": 3,
                            "network_operations": 1,
                        },
                        "history": [],
                    },
                    "provenance": {"identities": {}, "sessions": {}},
                    "capabilities": {},
                    "approvals": {"requests": {}, "authorizations": {}},
                    "coordination": {"leases": {}, "handoffs": []},
                    "checkpoints": {},
                    "verification": {},
                }
            },
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_end_to_end_replay_matches_events(self):
        """Replaying events produces matching state and passes verify_state_matches_events."""
        logger = EventLogger(self.repo_root)

        # 1. Agent started
        logger.emit("AGENT_STARTED", change_id=self.change_id, agent_id="maker-1", payload={"role": "maker"})
        # 2. Session created
        logger.emit("SESSION_CREATED", change_id=self.change_id, agent_id="maker-1", session_id="sess-maker-1")
        # 3. Task claimed
        logger.emit("TASK_CLAIMED", change_id=self.change_id, agent_id="maker-1", task_id="t-01", payload={"lease_token": "tok-1"})
        # 4. Budget updated
        logger.emit("BUDGET_UPDATED", change_id=self.change_id, payload={"limits": {"max_tokens": 500000}})
        # 5. Resource consumed
        logger.emit("RESOURCE_CONSUMED", change_id=self.change_id, agent_id="maker-1", payload={
            "delta": {"tokens": 1500, "model_calls": 2, "dollars": 0.05, "tool_executions": 3, "network_operations": 1}
        })
        # 6. Verification passed
        logger.emit("VERIFICATION_PASSED", change_id=self.change_id, payload={"tier": "execution", "score": 1.0})

        # Replay events
        events = logger.query(change_id=self.change_id)
        replayed = EventReplayer.replay(events, target_change=self.change_id)

        rep_ch = replayed["changes"][self.change_id]
        self.assertIn("maker-1", rep_ch["provenance"]["identities"])
        self.assertIn("t-01", rep_ch["coordination"]["leases"])
        self.assertEqual(rep_ch["budget"]["consumed"]["tokens"], 1500)
        self.assertEqual(rep_ch["budget"]["consumed"]["model_calls"], 2)
        self.assertEqual(rep_ch["budget"]["consumed"]["tool_executions"], 3)
        self.assertEqual(rep_ch["budget"]["consumed"]["network_operations"], 1)
        # Record corresponding lease in ledger so actual matches replayed
        ledger = FileLedgerStore.load(self.repo_root)
        ledger["changes"][self.change_id]["coordination"]["leases"]["t-01"] = {
            "task_id": "t-01",
            "agent_id": "maker-1",
            "status": "ACTIVE",
        }
        FileLedgerStore.save(self.repo_root, ledger)

        # Verify state matches
        matches, msg, diffs = EventReplayer.verify_state_matches_events(self.repo_root, change_id=self.change_id)
        self.assertTrue(matches, f"Verification failed: {msg}, diffs: {diffs}")

    def test_cli_events_replay_subcommand(self):
        """CLI: agentflow events replay --change <id> and agentflow events replay --verify."""
        logger = EventLogger(self.repo_root)
        logger.emit("AGENT_STARTED", change_id=self.change_id, agent_id="maker-1")
        logger.emit("RESOURCE_CONSUMED", change_id=self.change_id, payload={
            "delta": {"tokens": 1500, "model_calls": 2, "dollars": 0.05, "tool_executions": 3, "network_operations": 1}
        })

        # CLI Replay
        code_replay = cli_main(["events", "replay", "--path", str(self.repo_root), "--change", self.change_id])
        self.assertEqual(code_replay, 0)

        # CLI Replay Verify
        code_verify = cli_main(["events", "replay", "--path", str(self.repo_root), "--change", self.change_id, "--verify"])
        self.assertEqual(code_verify, 0)


if __name__ == "__main__":
    unittest.main()
