"""Check local references and executable examples without accessing the network."""

import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_validate_report import validator


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
        path = ROOT / "skills/adversarial-review/references/finding_schema.md"
        examples = re.findall(r"```json\n(.*?)\n```", path.read_text(), re.DOTALL)
        self.assertTrue(examples)
        for example in examples:
            data = json.loads(example)
            if "reviewer" not in data:
                data = {"reviewer": "judge", "status": "complete", "findings": [data],
                        "coverage": [], "questions": [], "routing_notes": []}
            self.assertEqual(validator.validate_report(data), [])
