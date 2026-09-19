"""Git failure scenarios: detached HEAD, index.lock, dirty tree, merge conflicts."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from ship.lifecycle.vcs import GitClient
from ship.lifecycle.gates import validate_delivery_readiness


class TestGitFailures(unittest.TestCase):
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
            subprocess.run(["git", *args], cwd=self.repo_root, capture_output=True, check=True)

        # Initial commit
        (self.repo_root / "README.md").write_text("# Test Repo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.repo_root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=self.repo_root, capture_output=True, check=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_detached_head_detected(self):
        """Detached HEAD is diagnosed cleanly by GitClient."""
        # Detach HEAD to current commit
        head_commit = GitClient().get_output(self.repo_root, "rev-parse", "HEAD")
        subprocess.run(["git", "checkout", head_commit], cwd=self.repo_root, capture_output=True, check=True)

        info = GitClient().get_info(self.repo_root)
        self.assertTrue(info["is_detached"])
        self.assertEqual(info["commit"], head_commit)

    def test_stale_index_lock_detected(self):
        """Abandoned .git/index.lock is flagged by GitClient diagnostics."""
        git_dir = GitClient().get_git_common_dir(self.repo_root)
        index_lock = git_dir / "index.lock"
        index_lock.write_text("abandoned lock", encoding="utf-8")

        info = GitClient().get_info(self.repo_root)
        self.assertTrue(info["is_index_locked"])

    def test_dirty_working_tree_blocks_delivery(self):
        """Uncommitted changes strictly block delivery gate clearance."""
        (self.repo_root / "dirty_file.py").write_text("print('dirty')\n", encoding="utf-8")

        info = GitClient().get_info(self.repo_root)
        self.assertFalse(info["is_clean"])
        self.assertIn("dirty_file.py", info["modified_source_files"])

        # Stale fingerprint due to dirty tree blocks delivery
        gate, status_label, reason = validate_delivery_readiness(
            review_report={
                "is_judge": True,
                "status": "complete",
                "verdict": "PASS",
                "change": "c1",
                "commit": info.get("head_sha"),
                "critical_or_high_count": 0,
                "questions": [],
                "findings": [],
                "test_evidence_passed": True,
                "judge_report_valid": True,
                "snapshot_fingerprint": info.get("working_tree_fingerprint"),
            },
            active_pkg={
                "change": "c1",
                "has_tasks": True,
                "total_tasks": 1,
                "completed_tasks": 1,
                "pending_tasks": 0,
            },
            git_info=info,
            active_change={"verification": {"execution": {"verdict": "VERIFIED", "metadata": {"snapshot_fingerprint": "clean_fp"}}}},
            repo_root=self.repo_root,
        )
        self.assertNotEqual(gate, "delivery")
        self.assertEqual(status_label, "VERIFICATION_FAILED")
        self.assertIn("stale", reason.lower())

    def test_merge_conflict_detected(self):
        """Merge conflicts (UU status) are detected and flagged in GitInfo."""
        info = GitClient().get_info(self.repo_root)
        self.assertFalse(info.get("has_conflicts", False))


if __name__ == "__main__":
    unittest.main()
