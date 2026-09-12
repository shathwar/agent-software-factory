"""Unit tests for skills installation script (scripts/install.sh)."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = ROOT / "scripts" / "install.sh"


class TestInstallScript(unittest.TestCase):
    def setUp(self):
        self.temp_target = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_target.cleanup)
        self.target_dir = Path(self.temp_target.name)

    def run_installer(self, *args, check=True):
        cmd = ["bash", str(INSTALL_SCRIPT), *args]
        res = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
        if check:
            self.assertEqual(res.returncode, 0, f"Installer failed ({res.returncode}):\n{res.stderr}\n{res.stdout}")
        return res

    def test_help_and_usage(self):
        for flag in ["-h", "--help"]:
            with self.subTest(flag=flag):
                res = self.run_installer(flag)
                self.assertIn("Usage: ./scripts/install.sh [options]", res.stdout)
                self.assertIn("--target", res.stdout)
                self.assertIn("--mode", res.stdout)

    def test_list_skills(self):
        res = self.run_installer("--list")
        self.assertIn("Available skills", res.stdout)
        self.assertIn("adversarial-review", res.stdout)
        self.assertIn("ship", res.stdout)
        self.assertIn("ponytail", res.stdout)
        self.assertIn("prototype", res.stdout)
        self.assertIn("tdd", res.stdout)
        self.assertIn("adversarial-design", res.stdout)

    def test_dry_run_makes_no_changes(self):
        dest_dir = self.target_dir / "skills_test"
        res = self.run_installer("--target", str(dest_dir), "--dry-run")
        self.assertIn("DRY-RUN enabled", res.stdout)
        self.assertFalse(dest_dir.exists())

    def test_symlink_mode_creates_symlinks(self):
        dest_dir = self.target_dir / "symlinks"
        res = self.run_installer("--target", str(dest_dir), "--mode", "symlink")
        self.assertIn("Successfully installed", res.stdout)
        self.assertTrue(dest_dir.is_dir())

        # Verify symlinks
        installed = [p for p in dest_dir.iterdir() if p.name in {"ship", "adversarial-review"}]
        self.assertTrue(len(installed) >= 2)
        for p in installed:
            self.assertTrue(p.is_symlink())
            self.assertTrue((p / "SKILL.md").exists())

    def test_copy_mode_copies_directories(self):
        dest_dir = self.target_dir / "copies"
        res = self.run_installer("--target", str(dest_dir), "--mode", "copy")
        self.assertIn("Successfully installed", res.stdout)
        self.assertTrue(dest_dir.is_dir())

        # Verify copied directories are real directories, not symlinks
        installed = [p for p in dest_dir.iterdir() if p.name in {"ship", "adversarial-review"}]
        self.assertTrue(len(installed) >= 2)
        for p in installed:
            self.assertFalse(p.is_symlink())
            self.assertTrue(p.is_dir())
            self.assertTrue((p / "SKILL.md").exists())

    def test_existing_directory_preserved_by_default(self):
        dest_dir = self.target_dir / "preserve"
        dest_dir.mkdir(parents=True)
        ship_dir = dest_dir / "ship"
        ship_dir.mkdir()
        canary_file = ship_dir / "canary.txt"
        canary_file.write_text("pre-existing content\n")

        res = self.run_installer("--target", str(dest_dir), "--mode", "symlink")
        self.assertIn("Preserving existing directory", res.stdout)
        self.assertTrue(canary_file.exists())
        self.assertEqual(canary_file.read_text().strip(), "pre-existing content")

    def test_overwrite_mode_replaces_existing_directory(self):
        dest_dir = self.target_dir / "overwrite"
        dest_dir.mkdir(parents=True)
        ship_dir = dest_dir / "ship"
        ship_dir.mkdir()
        canary_file = ship_dir / "canary.txt"
        canary_file.write_text("old content\n")

        res = self.run_installer("--target", str(dest_dir), "--mode", "symlink", "--overwrite")
        self.assertIn("Overwriting existing directory", res.stdout)
        self.assertTrue(ship_dir.is_symlink())
        self.assertFalse(canary_file.exists())

    def test_backup_mode_creates_timestamped_backup(self):
        dest_dir = self.target_dir / "backup"
        dest_dir.mkdir(parents=True)
        ship_dir = dest_dir / "ship"
        ship_dir.mkdir()
        canary_file = ship_dir / "canary.txt"
        canary_file.write_text("backup me\n")

        res = self.run_installer("--target", str(dest_dir), "--mode", "symlink", "--backup")
        self.assertIn("Backing up existing directory", res.stdout)
        self.assertTrue(ship_dir.is_symlink())

        # Verify backup directory was created
        backups = list(dest_dir.glob("ship.bak.*"))
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "canary.txt").exists())

    def test_invalid_mode_fails(self):
        res = self.run_installer("--mode", "invalid_mode", check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("--mode must be either 'symlink' or 'copy'", res.stderr)

    def test_unknown_option_fails(self):
        res = self.run_installer("--unknown-flag", check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Unknown option", res.stderr)


if __name__ == "__main__":
    unittest.main()
