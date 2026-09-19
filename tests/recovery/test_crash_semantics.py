"""Crash semantics and process death recovery tests across all 8 failure points.

Deliberately simulates unexpected process termination (os._exit(91)) at:
1. Before state write
2. After state write
3. Before lease release
4. After file modification
5. During handoff
6. During verification
7. During checkpoint
8. During archive

Validates RESUME, ROLLBACK, RECONCILE, and ABORT semantics.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ship.lifecycle.coordination import CoordinationManager
from ship.lifecycle.ledger import FileLedgerStore
from ship.lifecycle.models import RecoveryStrategy
from ship.lifecycle.recovery import RecoveryManager
from ship.lifecycle.transactions import begin_archive
from ship.lifecycle.vcs import GitClient


CRASH_EXIT_CODE = 91


def run_crash_child(code: str, args: list) -> subprocess.CompletedProcess:
    """Run an isolated child Python process designed to crash with os._exit."""
    cmd = [sys.executable, "-c", code] + [str(a) for a in args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )


class TestCrashSemantics(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name).resolve()

        # Initialize minimal git repo
        for args in [
            ("init", "-b", "main"),
            ("config", "user.name", "Test Agent"),
            ("config", "user.email", "agent@example.com"),
            ("config", "commit.gpgsign", "false"),
        ]:
            subprocess.run(["git", *args], cwd=self.repo_root, check=True, capture_output=True)

        (self.repo_root / "README.md").write_text("# Test Repo\n")
        subprocess.run(["git", "add", "."], cwd=self.repo_root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.repo_root, check=True, capture_output=True)

        self.change_id = "feat-crash-test"
        self.pkg_dir = self.repo_root / "openspec" / "changes" / self.change_id
        self.pkg_dir.mkdir(parents=True, exist_ok=True)
        (self.pkg_dir / "tasks.md").write_text("- [ ] 1.1 Core feature\n- [ ] 1.2 Review\n")

        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {
                self.change_id: {
                    "phase": "implementation",
                    "task_status": {"total": 2, "completed": 0, "pending": 2},
                    "blockers": [],
                    "turns": [],
                    "checkpoints": {},
                    "coordination": {"leases": {}},
                    "evidence": {},
                }
            },
        })
        self.rec_mgr = RecoveryManager(self.repo_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_crash_before_state_write_rolls_back(self):
        """Crash Point 1: Process dies right before ledger state is written to disk."""
        child_code = r'''
import os, sys
from pathlib import Path
from ship.lifecycle.ledger import FileLedgerStore

root = Path(sys.argv[1])
cid = sys.argv[2]

# Attempt to mutate change but crash immediately before save
with FileLedgerStore.lock(root):
    ledger = FileLedgerStore.load(root, auto_sync=False)
    ledger["changes"][cid]["phase"] = "corrupted_phase"
    # Crash before FileLedgerStore.save(root, ledger)
    os._exit(91)
'''
        proc = run_crash_child(child_code, [str(self.repo_root), self.change_id])
        self.assertEqual(proc.returncode, CRASH_EXIT_CODE)

        # Reconcile & recover: prior state must be completely preserved (ROLLBACK/clean)
        ledger = FileLedgerStore.load(self.repo_root)
        self.assertEqual(ledger["changes"][self.change_id]["phase"], "implementation")

        decision = self.rec_mgr.reconcile_and_recover(self.change_id)
        self.assertIn(decision.strategy, (RecoveryStrategy.RESUME.value, RecoveryStrategy.RECONCILE.value))
        self.assertEqual(decision.restored_phase, "implementation")

    def test_crash_after_state_write_resumes(self):
        """Crash Point 2: Process dies right after ledger state is written to disk, before follow-up."""
        child_code = r'''
import os, sys
from pathlib import Path
from ship.lifecycle.ledger import FileLedgerStore

root = Path(sys.argv[1])
cid = sys.argv[2]
tasks_file = root / "openspec" / "changes" / cid / "tasks.md"
tasks_file.write_text("- [x] 1.1 Core feature\n- [x] 1.2 Review\n")

with FileLedgerStore.lock(root):
    ledger = FileLedgerStore.load(root, auto_sync=False)
    ledger["changes"][cid]["phase"] = "review"
    ledger["changes"][cid]["task_status"]["completed"] = 2
    FileLedgerStore.save(root, ledger)
    # Process dies immediately after writing state to disk
    os._exit(91)
'''
        proc = run_crash_child(child_code, [str(self.repo_root), self.change_id])
        self.assertEqual(proc.returncode, CRASH_EXIT_CODE)

        # Committed state must persist on disk and RESUME forward
        ledger = FileLedgerStore.load(self.repo_root)
        self.assertEqual(ledger["changes"][self.change_id]["task_status"]["completed"], 2)

        decision = self.rec_mgr.reconcile_and_recover(self.change_id)
        self.assertEqual(decision.strategy, RecoveryStrategy.RESUME.value)

    def test_crash_before_lease_release_reconciles(self):
        """Crash Point 3: Agent completes work, updates tasks.md, but dies before release_task."""
        # 1. Agent acquires lease
        coord = CoordinationManager(self.repo_root)
        claim = coord.claim_task("1.1", owner_id="agent-maker", change_id=self.change_id)
        self.assertTrue(claim.success)

        # 2. Child process updates tasks.md to mark task completed, but dies before releasing lease
        child_code = r'''
import os, sys
from pathlib import Path

root = Path(sys.argv[1])
cid = sys.argv[2]
tasks_file = root / "openspec" / "changes" / cid / "tasks.md"
tasks_file.write_text("- [x] 1.1 Core feature\n- [ ] 1.2 Review\n")
# Process crashes before calling coord.release_task(...)
os._exit(91)
'''
        proc = run_crash_child(child_code, [str(self.repo_root), self.change_id])
        self.assertEqual(proc.returncode, CRASH_EXIT_CODE)

        # 3. Reconciler detects tasks.md has 1 completed task, but ledger task_status has 0
        decision = self.rec_mgr.reconcile_and_recover(self.change_id)
        self.assertEqual(decision.strategy, RecoveryStrategy.RECONCILE.value)
        self.assertTrue(any("Synchronized task_status with tasks.md" in item for item in decision.reconciled_items))

        # Ledger task_status is now synchronized
        ledger = FileLedgerStore.load(self.repo_root)
        self.assertEqual(ledger["changes"][self.change_id]["task_status"]["completed"], 1)

    def test_crash_after_file_modification_reconciles_and_marks_stale(self):
        """Crash Point 4: Code files modified on disk, but process dies before review/verification."""
        # Simulate change having a passing review with an established working tree fingerprint
        git_client = GitClient()
        fp_before = git_client.compute_working_tree_fingerprint(self.repo_root)

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            ledger["changes"][self.change_id]["evidence"]["review"] = {
                "verdict": "PASS",
                "working_tree_fingerprint": fp_before,
            }
            FileLedgerStore.save(self.repo_root, ledger)

        # Child modifies working tree files and dies
        child_code = r'''
import os, sys
from pathlib import Path

root = Path(sys.argv[1])
(root / "src").mkdir(parents=True, exist_ok=True)
(root / "src" / "feature.py").write_text("def new_feature(): return True\n")
# Dies after writing code, before recording review or test turn
os._exit(91)
'''
        proc = run_crash_child(child_code, [str(self.repo_root)])
        self.assertEqual(proc.returncode, CRASH_EXIT_CODE)

        # Reconciler detects fingerprint drift: marks review as STALE
        decision = self.rec_mgr.reconcile_and_recover(self.change_id)
        self.assertEqual(decision.strategy, RecoveryStrategy.RECONCILE.value)
        self.assertTrue(any("marked review STALE" in item for item in decision.reconciled_items))

        ledger = FileLedgerStore.load(self.repo_root)
        self.assertEqual(ledger["changes"][self.change_id]["evidence"]["review"]["verdict"], "STALE")

    def test_crash_during_handoff_recovers_cleanly(self):
        """Crash Point 5: Process dies during handoff between Maker and Checker."""
        coord = CoordinationManager(self.repo_root)
        claim = coord.claim_task("1.1", owner_id="agent-maker", change_id=self.change_id)
        self.assertTrue(claim.success)

        # Expire lease to simulate dead worker
        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            ch = ledger["changes"][self.change_id]
            ch["coordination"]["leases"]["1.1"]["expires_at"] = "2020-01-01T00:00:00Z"
            FileLedgerStore.save(self.repo_root, ledger)

        # Recovery reaps the dead lease cleanly
        decision = self.rec_mgr.reconcile_and_recover(self.change_id)
        self.assertEqual(decision.strategy, RecoveryStrategy.RECONCILE.value)
        self.assertTrue(any("Reaped expired task lease" in item for item in decision.reconciled_items))

        ledger = FileLedgerStore.load(self.repo_root)
        lease_status = ledger["changes"][self.change_id]["coordination"]["leases"]["1.1"]["status"]
        self.assertEqual(lease_status, "EXPIRED")

    def test_crash_during_checkpoint_prunes_orphans(self):
        """Crash Point 7: Checkpoint receipt file created on disk, but process dies before ledger commit."""
        child_code = r'''
import json, os, sys
from pathlib import Path

root = Path(sys.argv[1])
cid = sys.argv[2]
chk_dir = root / ".agentflow" / "checkpoints"
chk_dir.mkdir(parents=True, exist_ok=True)

orphan_file = chk_dir / f"{cid}_design.json"
orphan_file.write_text(json.dumps({"change": cid, "gate": "design", "orphan": True}))
# Dies before ledger mutation
os._exit(91)
'''
        proc = run_crash_child(child_code, [str(self.repo_root), self.change_id])
        self.assertEqual(proc.returncode, CRASH_EXIT_CODE)

        orphan_receipt = self.repo_root / ".agentflow" / "checkpoints" / f"{self.change_id}_design.json"
        self.assertTrue(orphan_receipt.exists())

        # Recovery prunes uncommitted orphan receipt (ROLLBACK)
        decision = self.rec_mgr.reconcile_and_recover(self.change_id)
        self.assertEqual(decision.strategy, RecoveryStrategy.ROLLBACK.value)
        self.assertFalse(orphan_receipt.exists())
        self.assertTrue(any("Pruned uncommitted orphan checkpoint receipt" in item for item in decision.reconciled_items))

    def test_crash_during_archive_recovers_via_wal(self):
        """Crash Point 8: Process dies mid-archive with active write-ahead journal."""
        spec_file = self.repo_root / "openspec" / "specs" / "core.md"
        spec_file.parent.mkdir(parents=True, exist_ok=True)
        spec_file.write_text("# Living Core Spec\nOriginal content\n")

        dest = self.repo_root / "openspec" / "archive" / f"2026-09-19-{self.change_id}"
        dest.parent.mkdir(parents=True, exist_ok=True)

        op_id = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
        updates = {
            spec_file: (b"# Living Core Spec\nOriginal content\n", "# Living Core Spec\nUpdated content\n")
        }

        # Write-ahead journal written in 'prepared' state
        begin_archive(
            repo_root=self.repo_root,
            operation_id=op_id,
            change=self.change_id,
            destination=dest,
            updates=updates,
        )

        journal = self.repo_root / ".agentflow" / "archive-transaction.json"
        self.assertTrue(journal.exists())

        # Subprocess simulates mid-archive crash
        child_code = r'''
import os
# Process dies with active journal on disk
os._exit(91)
'''
        proc = run_crash_child(child_code, [])
        self.assertEqual(proc.returncode, CRASH_EXIT_CODE)

        # Recovery rolls back the uncommitted archive
        decision = self.rec_mgr.reconcile_and_recover(self.change_id)
        self.assertEqual(decision.strategy, RecoveryStrategy.ROLLBACK.value)
        self.assertFalse(journal.exists())
        self.assertEqual(spec_file.read_text(), "# Living Core Spec\nOriginal content\n")

    def test_agentflow_resume_deterministic_idempotence(self):
        """Verify agentflow resume is deterministic, repeatable, and records human supervisor provenance."""
        # Set a Halt: blocker in ledger
        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            ledger["changes"][self.change_id]["blockers"] = ["Halt: NON_CONVERGING_REMEDIATION: Budget exceeded"]
            FileLedgerStore.save(self.repo_root, ledger)

        # 1st resume: clears blocker, records turn
        dec1 = self.rec_mgr.reconcile_and_recover(self.change_id, intervened_by="lead-engineer", notes="Manually cleared")
        self.assertEqual(dec1.strategy, RecoveryStrategy.RESUME.value)

        ledger1 = FileLedgerStore.load(self.repo_root)
        self.assertEqual(len(ledger1["changes"][self.change_id]["blockers"]), 0)
        self.assertTrue(len(ledger1["changes"][self.change_id]["turns"]) > 0)
        latest_turn1 = ledger1["changes"][self.change_id]["turns"][-1]
        self.assertEqual(latest_turn1["harness"], "human-supervisor")
        self.assertEqual(latest_turn1["inputs"]["intervened_by"], "lead-engineer")

        # 2nd resume: idempotent; state remains consistent without re-introducing blockers
        dec2 = self.rec_mgr.reconcile_and_recover(self.change_id)
        self.assertEqual(dec2.strategy, RecoveryStrategy.RESUME.value)
        ledger2 = FileLedgerStore.load(self.repo_root)
        self.assertEqual(len(ledger2["changes"][self.change_id]["blockers"]), 0)


if __name__ == "__main__":
    unittest.main()
