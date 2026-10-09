"""Check local references and executable examples without accessing the network."""

import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ship.tool_runtime import call_tool


ROOT = Path(__file__).resolve().parents[1]


class DocumentTests(unittest.TestCase):
    def test_relative_link_targets_exist(self):
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT, check=True, capture_output=True)
        paths = {ROOT / path.decode() for path in result.stdout.split(b"\0") if path}
        for path in sorted(paths):
            if path.suffix != ".md":
                continue
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if "://" in target or target.startswith(("/", "#")):
                    continue
                relative = target.split("#")[0].strip()
                with self.subTest(path=path.relative_to(ROOT), target=target):
                    self.assertTrue(bool(relative))
                    self.assertTrue((path.parent / relative).exists())

    def test_schema_document_examples(self):
        path = ROOT / "skills/review/references/finding_schema.md"
        examples = re.findall(r"```json\n(.*?)\n```", path.read_text(), re.DOTALL)
        self.assertTrue(examples)
        for example in examples:
            data = json.loads(example)
            if "reviewer" not in data:
                data = {"reviewer": "judge", "status": "complete", "findings": [data],
                        "coverage": [], "questions": [], "routing_notes": []}
            self.assertEqual(call_tool("review", {"report_data": data})["errors"], [])

    def test_no_legacy_workspace_references(self):
        """Ensure obsolete ledger names never regress; .scratch/ is the spike workspace."""
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT, check=True, capture_output=True)
        tracked_paths = [ROOT / path.decode() for path in result.stdout.split(b"\0") if path]

        for p in tracked_paths:
            if p == ROOT / "tests/test_documents.py" or not p.exists():
                continue
            # 1. .ship.json must never appear in any tracked file
            if p.suffix in (".md", ".py", ".json", ".sh", ".yml", ".yaml", ".toml"):
                content = p.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn(".ship.json", content, f"Found legacy .ship.json reference in {p.relative_to(ROOT)}")

            # 2. .ship/ must never appear in any markdown or workflow file
            if p.suffix in (".md", ".yml", ".yaml"):
                content = p.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn(".ship/", content, f"Found legacy .ship/ reference in {p.relative_to(ROOT)}")

            # Scratch prototypes intentionally use .scratch/. Their compatibility
            # with runtime policy is exercised by test_ship_rollout_fixes.
