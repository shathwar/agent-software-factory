"""Unit tests validating nano rule sets and AGENTS.md density constraints."""

from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
NANO_DIR = ROOT / "nano"

EXPECTED_FILES = [
    "AGENTS.md",
    "review.nano.md",
    "simplify.nano.md",
    "tdd.nano.md",
    "design.nano.md",
    "spike.nano.md",
    "ship.nano.md",
    "evals.nano.md",
    "debug.nano.md",
    "ux.nano.md",
]


class TestNanoRules(unittest.TestCase):
    def test_all_nano_files_exist(self):
        self.assertTrue(NANO_DIR.is_dir(), f"Missing nano directory at {NANO_DIR}")
        for filename in EXPECTED_FILES:
            file_path = NANO_DIR / filename
            self.assertTrue(file_path.is_file(), f"Missing nano rule file: {filename}")

    def test_individual_nano_file_density_budgets(self):
        """Individual nano files must remain under 60 lines and 4,000 bytes."""
        for filename in EXPECTED_FILES:
            if filename == "AGENTS.md":
                continue
            path = NANO_DIR / filename
            text = path.read_text(encoding="utf-8")
            line_count = len(text.splitlines())
            byte_count = len(text.encode("utf-8"))

            self.assertLessEqual(
                line_count, 60,
                f"{filename} exceeds nano line budget ({line_count} lines > 60)"
            )
            self.assertLessEqual(
                byte_count, 4000,
                f"{filename} exceeds nano byte budget ({byte_count} bytes > 4000)"
            )

    def test_universal_agents_md_density_budget(self):
        """The combined AGENTS.md must remain under 100 lines and 6,000 bytes."""
        path = NANO_DIR / "AGENTS.md"
        text = path.read_text(encoding="utf-8")
        line_count = len(text.splitlines())
        byte_count = len(text.encode("utf-8"))

        self.assertLessEqual(
            line_count, 100,
            f"AGENTS.md exceeds line budget ({line_count} lines > 100)"
        )
        self.assertLessEqual(
            byte_count, 6000,
            f"AGENTS.md exceeds byte budget ({byte_count} bytes > 6000)"
        )

    def test_literature_grounding_present(self):
        """Ensure canonical literature concepts are properly embedded."""
        agents_text = (NANO_DIR / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Kleppmann", agents_text)
        self.assertIn("Nygard", agents_text)
        self.assertIn("Ousterhout", agents_text)
        self.assertIn("Deep Modules", agents_text)
        self.assertIn("Define Errors Out of Existence", agents_text)


if __name__ == "__main__":
    unittest.main()
