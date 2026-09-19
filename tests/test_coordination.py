"""Unit tests for Multi-Agent Coordination Engine (coordination.py, models.py, cli.py)."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.models import (
    LeaseStatus,
    CoordinationConflictType,
    TaskLease,
    TaskHandoff,
)
from ship.lifecycle.coordination import (
    CoordinationConfig,
    CoordinationResult,
    CoordinationManager,
    is_lease_expired,
)
from ship.lifecycle.ledger import FileLedgerStore
from ship.cli import main as cli_main


class TestTaskLeaseModels(unittest.TestCase):
    def test_lease_serialization(self):
        lease = TaskLease(
            task_id="1.1",
            change_id="change-test",
            owner_id="agent-maker-1",
            lease_token="token-abc",
            acquired_at="2026-09-19T10:00:00Z",
            expires_at="2026-09-19T10:10:00Z",
            files=["src/auth.py"],
            status=LeaseStatus.ACTIVE,
        )
        data = lease.to_dict()
        self.assertEqual(data["task_id"], "1.1")
        self.assertEqual(data["status"], "ACTIVE")

        restored = TaskLease.from_dict(data)
        self.assertEqual(restored.task_id, "1.1")
        self.assertEqual(restored.owner_id, "agent-maker-1")
        self.assertEqual(restored.status, LeaseStatus.ACTIVE)
        self.assertEqual(restored.files, ["src/auth.py"])

    def test_handoff_serialization(self):
        handoff = TaskHandoff(
            task_id="1.1",
            from_owner="agent-maker",
            to_owner="agent-checker",
            handed_off_at="2026-09-19T10:05:00Z",
            verification_checklist=["unit tests pass", "clean diff"],
            notes="Ready for independent verification",
        )
        data = handoff.to_dict()
        self.assertEqual(data["to_owner"], "agent-checker")

        restored = TaskHandoff.from_dict(data)
        self.assertEqual(restored.from_owner, "agent-maker")
        self.assertEqual(restored.to_owner, "agent-checker")
        self.assertEqual(len(restored.verification_checklist), 2)

    def test_lease_expired_calculation(self):
        self.assertFalse(is_lease_expired(None))
        self.assertTrue(is_lease_expired("2020-01-01T00:00:00Z"))
        self.assertFalse(is_lease_expired("2099-01-01T00:00:00Z"))


class TestCoordinationManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tmp_dir.name)
        self.change_id = "test-change-001"
        self.change_dir = self.repo_root / ".ship" / "changes" / self.change_id
        self.change_dir.mkdir(parents=True, exist_ok=True)

        # Create OpenSpec tasks.md
        self.tasks_file = self.change_dir / "tasks.md"
        self.tasks_file.write_text(
            "# Tasks\n\n- [ ] 1.1 Implement token auth\n- [ ] 1.2 Write verifier tests\n"
        )

        self.manager = CoordinationManager(self.repo_root, self.change_id)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_claim_task_grants_lease_with_token(self):
        result = self.manager.claim_task(
            task_id="1.1",
            owner_id="agent-maker-1",
            files=["src/auth.py"],
            ttl_seconds=300,
        )
        self.assertTrue(result.success)
        self.assertIsNotNone(result.lease)
        self.assertEqual(result.lease.owner_id, "agent-maker-1")
        self.assertIn(result.lease.status, (LeaseStatus.ACQUIRED, LeaseStatus.ACTIVE, "ACQUIRED", "ACTIVE"))
        self.assertTrue(len(result.lease.lease_token) > 0)

        # Verify persisted in ledger coordination state
        store = FileLedgerStore()
        coord = store.get_coordination(self.repo_root, self.change_id)
        self.assertIn("1.1", coord["leases"])
        self.assertEqual(coord["leases"]["1.1"]["owner_id"], "agent-maker-1")

    def test_concurrent_claim_rejected_when_lease_active(self):
        # First agent claims task
        res1 = self.manager.claim_task(
            task_id="1.1",
            owner_id="agent-maker-1",
            files=["src/auth.py"],
            ttl_seconds=300,
        )
        self.assertTrue(res1.success)

        # Second agent attempts to claim same task
        res2 = self.manager.claim_task(
            task_id="1.1",
            owner_id="agent-maker-2",
            files=["src/auth.py"],
            ttl_seconds=300,
        )
        self.assertFalse(res2.success)
        self.assertEqual(res2.conflict_type, CoordinationConflictType.CONCURRENT_LEASE)
        self.assertIn("already leased", res2.message)

    def test_idempotent_renew_by_same_owner(self):
        res1 = self.manager.claim_task(
            task_id="1.1",
            owner_id="agent-maker-1",
            files=["src/auth.py"],
            ttl_seconds=300,
        )
        self.assertTrue(res1.success)
        token1 = res1.lease.lease_token

        # Same owner claims again
        res2 = self.manager.claim_task(
            task_id="1.1",
            owner_id="agent-maker-1",
            files=["src/auth.py"],
            ttl_seconds=600,
        )
        self.assertTrue(res2.success)
        self.assertEqual(res2.lease.lease_token, token1)
        self.assertEqual(res2.lease.status, LeaseStatus.RENEWED)

    def test_file_conflict_detection_prevents_overlap(self):
        # Agent 1 claims task 1.1 editing auth.py
        res1 = self.manager.claim_task(
            task_id="1.1",
            owner_id="agent-maker-1",
            files=["src/auth.py", "src/models.py"],
            ttl_seconds=300,
        )
        self.assertTrue(res1.success)

        # Agent 2 claims task 1.2 editing auth.py as well
        res2 = self.manager.claim_task(
            task_id="1.2",
            owner_id="agent-maker-2",
            files=["src/auth.py", "src/utils.py"],
            ttl_seconds=300,
        )
        self.assertFalse(res2.success)
        self.assertEqual(res2.conflict_type, CoordinationConflictType.FILE_OVERLAP)
        self.assertIn("Resource file conflict", res2.message)
        self.assertIn("src/auth.py", res2.message)

    def test_heartbeat_extends_expiration(self):
        res1 = self.manager.claim_task(
            task_id="1.1",
            owner_id="agent-maker-1",
            ttl_seconds=60,
        )
        self.assertTrue(res1.success)
        old_expiry = res1.lease.expires_at

        # Heartbeat with valid token extends expiry
        res2 = self.manager.heartbeat_lease(
            task_id="1.1",
            lease_token=res1.lease.lease_token,
            ttl_seconds=600,
        )
        self.assertTrue(res2.success)
        self.assertGreater(res2.lease.expires_at, old_expiry)

        # Heartbeat with invalid token fails
        res3 = self.manager.heartbeat_lease(
            task_id="1.1",
            lease_token="invalid-token",
            ttl_seconds=600,
        )
        self.assertFalse(res3.success)
        self.assertIn("Invalid lease token", res3.message)

    def test_stale_agent_reaper_expires_abandoned_lease(self):
        # Claim with expired timestamp
        res1 = self.manager.claim_task(
            task_id="1.1",
            owner_id="agent-stale",
            ttl_seconds=300,
        )
        self.assertTrue(res1.success)

        # Force expiration in the ledger
        store = FileLedgerStore()
        with store.lock(self.repo_root):
            ledger = store.load(self.repo_root, auto_sync=False)
            ledger["changes"][self.change_id]["coordination"]["leases"]["1.1"]["expires_at"] = "2020-01-01T00:00:00Z"
            store.save(self.repo_root, ledger)

        # Reap stale leases
        reaped = self.manager.reap_stale_leases()
        self.assertEqual(len(reaped), 1)
        self.assertEqual(reaped[0].task_id, "1.1")
        self.assertEqual(reaped[0].status, LeaseStatus.EXPIRED)

        # Now agent 2 can claim it successfully
        res2 = self.manager.claim_task(
            task_id="1.1",
            owner_id="agent-fresh",
            ttl_seconds=300,
        )
        self.assertTrue(res2.success)
        self.assertEqual(res2.lease.owner_id, "agent-fresh")

    def test_orderly_handoff_maker_to_checker(self):
        res1 = self.manager.claim_task(
            task_id="1.1",
            owner_id="agent-maker",
            ttl_seconds=300,
        )
        self.assertTrue(res1.success)
        maker_token = res1.lease.lease_token

        # Handoff from maker to checker
        checklist = ["Unit tests passing (100%)", "No invariant regressions"]
        res_handoff = self.manager.handoff_task(
            task_id="1.1",
            from_owner="agent-maker",
            lease_token=maker_token,
            to_owner="agent-checker",
            verification_checklist=checklist,
            notes="Passing over to independent verifier",
            new_ttl_seconds=400,
        )
        self.assertTrue(res_handoff.success)
        new_lease = res_handoff.lease
        self.assertEqual(new_lease.owner_id, "agent-checker")
        self.assertNotEqual(new_lease.lease_token, maker_token)

        # Old maker token can no longer heartbeat
        res_hb = self.manager.heartbeat_lease(
            task_id="1.1",
            lease_token=maker_token,
        )
        self.assertFalse(res_hb.success)

        # New checker token can heartbeat
        res_hb2 = self.manager.heartbeat_lease(
            task_id="1.1",
            lease_token=new_lease.lease_token,
        )
        self.assertTrue(res_hb2.success)

    def test_release_task_updates_tasks_md_and_ledger(self):
        res1 = self.manager.claim_task(
            task_id="1.1",
            owner_id="agent-maker",
            ttl_seconds=300,
        )
        token = res1.lease.lease_token

        res_rel = self.manager.release_task(
            task_id="1.1",
            lease_token=token,
            completed=True,
            summary="Implemented authentication tokens successfully",
        )
        self.assertTrue(res_rel.success)
        self.assertEqual(res_rel.lease.status, LeaseStatus.RELEASED)

        # Check tasks.md updated
        content = self.tasks_file.read_text()
        self.assertIn("- [x] 1.1 Implement token auth", content)
        self.assertIn("- [ ] 1.2 Write verifier tests", content)


class TestCLICoordination(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tmp_dir.name)
        self.change_id = "cli-change-001"
        self.change_dir = self.repo_root / ".ship" / "changes" / self.change_id
        self.change_dir.mkdir(parents=True, exist_ok=True)
        (self.change_dir / "tasks.md").write_text("# Tasks\n- [ ] 2.1 Build API\n")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_cli_lease_lifecycle(self):
        # 1. Claim task
        ret = cli_main([
            "lease", "claim",
            "--change", self.change_id,
            "--repo-root", str(self.repo_root),
            "--task", "2.1",
            "--owner", "agent-cli",
            "--ttl", "300",
            "--files", "api.py,models.py",
        ])
        self.assertEqual(ret, 0)

        # Check coordination state
        store = FileLedgerStore()
        coord = store.get_coordination(self.repo_root, self.change_id)
        token = coord["leases"]["2.1"]["lease_token"]
        self.assertIsNotNone(token)

        # 2. List leases
        ret_list = cli_main([
            "lease", "list",
            "--change", self.change_id,
            "--repo-root", str(self.repo_root),
        ])
        self.assertEqual(ret_list, 0)

        # 3. Heartbeat
        ret_hb = cli_main([
            "lease", "heartbeat",
            "--change", self.change_id,
            "--repo-root", str(self.repo_root),
            "--task", "2.1",
            "--token", token,
            "--ttl", "600",
        ])
        self.assertEqual(ret_hb, 0)

        # 4. Handoff
        ret_handoff = cli_main([
            "lease", "handoff",
            "--change", self.change_id,
            "--repo-root", str(self.repo_root),
            "--task", "2.1",
            "--from", "agent-cli",
            "--to", "agent-verifier",
            "--token", token,
            "--checklist", "Passes specs,Clean syntax",
        ])
        self.assertEqual(ret_handoff, 0)

        # Get new token
        coord2 = store.get_coordination(self.repo_root, self.change_id)
        new_token = coord2["leases"]["2.1"]["lease_token"]
        self.assertNotEqual(new_token, token)

        # 5. Release
        ret_rel = cli_main([
            "lease", "release",
            "--change", self.change_id,
            "--repo-root", str(self.repo_root),
            "--task", "2.1",
            "--token", new_token,
            "--completed",
        ])
        self.assertEqual(ret_rel, 0)

        # 6. Reap
        ret_reap = cli_main([
            "lease", "reap",
            "--change", self.change_id,
            "--repo-root", str(self.repo_root),
        ])
        self.assertEqual(ret_reap, 0)


if __name__ == "__main__":
    unittest.main()
