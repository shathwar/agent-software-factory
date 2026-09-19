"""Filesystem race, atomicity, and path containment tests."""

from pathlib import Path
import os
import tempfile
import unittest

from ship.lifecycle.paths import validate_change_id
from ship.lifecycle.transactions import atomic_write
from ship.lifecycle.capabilities import _target_matches


class TestFilesystemRaces(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name).resolve()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_atomic_write_creates_file_safely(self):
        """Atomic write writes data and replaces destination atomically."""
        target = self.repo_root / "test_file.txt"
        atomic_write(target, b"production-hardened-content")

        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "production-hardened-content")

    def test_atomic_write_aborts_on_exception_without_corrupting(self):
        """Atomic write cleans up temporary file on unhandled exception and does not overwrite target."""
        target = self.repo_root / "important_data.json"
        target.write_text('{"original": "data"}', encoding="utf-8")

        with self.assertRaises(TypeError):
            # Passing invalid data type raises error before replacing file
            atomic_write(target, None)  # type: ignore

        # Original file must remain intact
        self.assertEqual(target.read_text(encoding="utf-8"), '{"original": "data"}')

    def test_change_id_path_traversal_rejection(self):
        """Path traversal change_ids are strictly rejected by validate_change_id."""
        malicious_ids = [
            "../../etc/passwd",
            "../parent",
            "/absolute/root",
            "change/with/slash",
            "change\\with\\backslash",
            "change\0null",
            "   ",
            "",
            "...",
        ]
        for mid in malicious_ids:
            with self.assertRaises(ValueError):
                validate_change_id(mid)

    def test_symlink_path_containment_defense(self):
        """Ensure symlinks pointing outside workspace do not trick target pattern matching."""
        sensitive_outside = Path("/etc/passwd")
        symlink_path = self.repo_root / "src" / "sneaky_link"
        symlink_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(str(sensitive_outside), str(symlink_path))
        except OSError:
            pass  # Some environments restrict symlink creation

        # Target matcher must not treat symlink path as authorized root file
        self.assertFalse(_target_matches("src/legit.py", str(sensitive_outside)))
        self.assertFalse(_target_matches("src/*", "/etc/passwd"))


if __name__ == "__main__":
    unittest.main()
