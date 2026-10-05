"""Unit tests for UX audit tool (audit_ux.py / ux.py)."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ship.tools import ux


class TestAuditUX(unittest.TestCase):
    def test_clickable_div_lacking_keyboard(self):
        # div with click but no keyboard handler -> UX-001 ERROR
        bad_html = '<div onClick={() => submit()}>Click me</div>'
        violations = ux.audit_content(bad_html, "test.tsx")
        rule_ids = [v.rule_id for v in violations]
        self.assertIn("UX-001", rule_ids)
        self.assertEqual(violations[0].severity, "ERROR")

        # div with role="button" and tabIndex BUT missing keyboard handler -> UX-001 ERROR
        aria_div_without_keys = '<div role="button" tabIndex={0} onClick={() => submit()}>Click me</div>'
        violations = ux.audit_content(aria_div_without_keys, "test.tsx")
        self.assertIn("UX-001", [v.rule_id for v in violations])

        # Good: native button
        good_html = '<button onClick={() => submit()}>Click me</button>'
        violations = ux.audit_content(good_html, "test.tsx")
        self.assertNotIn("UX-001", [v.rule_id for v in violations])

        # Good: div with click AND keyboard handler
        accessible_div = '<div role="button" tabIndex={0} onClick={() => submit()} onKeyDown={(e) => handle(e)}>Click me</div>'
        violations = ux.audit_content(accessible_div, "test.tsx")
        self.assertNotIn("UX-001", [v.rule_id for v in violations])

    def test_focus_indicators(self):
        # outline-none without replacement -> UX-002 ERROR
        bad_html = '<button className="outline-none py-2 px-4">Submit</button>'
        violations = ux.audit_content(bad_html, "test.tsx")
        rule_ids = [v.rule_id for v in violations]
        self.assertIn("UX-002", rule_ids)
        self.assertEqual(violations[0].severity, "ERROR")

        # Good: outline-none paired with focus:ring
        good_ring = '<button className="outline-none focus-visible:ring-2 focus-visible:ring-blue-500 py-2">Submit</button>'
        violations = ux.audit_content(good_ring, "test.tsx")
        self.assertNotIn("UX-002", [v.rule_id for v in violations])

        # Good: box-shadow / focus-ring replacement
        good_shadow = '<button style={{ outline: "none", boxShadow: "0 0 0 2px var(--focus-ring)" }}>Submit</button>'
        violations = ux.audit_content(good_shadow, "test.tsx")
        self.assertNotIn("UX-002", [v.rule_id for v in violations])

    def test_icon_buttons_and_title(self):
        # Completely unlabelled icon button -> UX-003 ERROR
        bad_html = '<button className="p-2"><svg className="w-5 h-5" /></button>'
        violations = ux.audit_content(bad_html, "test.tsx")
        rule_ids = [v.rule_id for v in violations]
        self.assertIn("UX-003", rule_ids)
        self.assertEqual(violations[0].severity, "ERROR")

        # Icon button with title attribute -> UX-031 INFO (not ERROR)
        title_html = '<button title="Close dialog" className="p-2"><svg className="w-5 h-5" /></button>'
        violations = ux.audit_content(title_html, "test.tsx")
        rule_ids = [v.rule_id for v in violations]
        self.assertNotIn("UX-003", rule_ids)
        self.assertIn("UX-031", rule_ids)
        self.assertEqual(violations[0].severity, "INFO")

        # Good: button with aria-label
        good_html = '<button aria-label="Close dialog" className="p-2"><svg className="w-5 h-5" /></button>'
        violations = ux.audit_content(good_html, "test.tsx")
        self.assertNotIn("UX-003", [v.rule_id for v in violations])
        self.assertNotIn("UX-031", [v.rule_id for v in violations])

        # Good: button with sr-only text
        sr_html = '<button className="p-2"><svg /><span className="sr-only">Close</span></button>'
        violations = ux.audit_content(sr_html, "test.tsx")
        self.assertNotIn("UX-003", [v.rule_id for v in violations])

    def test_form_labels(self):
        # Input with no label -> UX-014 ERROR
        bad_html = '<input type="text" name="username" />'
        violations = ux.audit_content(bad_html, "test.tsx")
        rule_ids = [v.rule_id for v in violations]
        self.assertIn("UX-014", rule_ids)
        self.assertEqual(violations[0].severity, "ERROR")

        # Good: aria-label
        good_html = '<input type="text" aria-label="Username" />'
        violations = ux.audit_content(good_html, "test.tsx")
        self.assertNotIn("UX-014", [v.rule_id for v in violations])

        # Good: label htmlFor match
        good_label = '<label htmlFor="user-in">User</label><input id="user-in" type="text" />'
        violations = ux.audit_content(good_label, "test.tsx")
        self.assertNotIn("UX-014", [v.rule_id for v in violations])

        # Hidden input should be ignored
        hidden_html = '<input type="hidden" name="csrf_token" value="abc" />'
        violations = ux.audit_content(hidden_html, "test.tsx")
        self.assertNotIn("UX-014", [v.rule_id for v in violations])

    def test_arbitrary_tokens_and_allowlist(self):
        # Arbitrary p-[17px] -> UX-021 WARNING
        bad_html = '<div className="p-[17px] text-sm">Content</div>'
        violations = ux.audit_content(bad_html, "test.tsx")
        rule_ids = [v.rule_id for v in violations]
        self.assertIn("UX-021", rule_ids)
        self.assertEqual(violations[0].severity, "WARNING")

        # Standard allowed arbitrary values (1px, 100%, 0) are NOT flagged
        allowed_html = '<div className="w-[100%] border-[1px] m-[0]">Full width</div>'
        violations = ux.audit_content(allowed_html, "test.tsx")
        self.assertNotIn("UX-021", [v.rule_id for v in violations])

        # Custom allowlist permits 17px
        violations = ux.audit_content(bad_html, "test.tsx", allowed_arbitrary={"17px", "0", "1px"})
        self.assertNotIn("UX-021", [v.rule_id for v in violations])

    def test_dead_end_error_detection(self):
        bad_html = '<p className="text-red-500">An error occurred</p>'
        violations = ux.audit_content(bad_html, "test.tsx")
        rule_ids = [v.rule_id for v in violations]
        self.assertIn("UX-005", rule_ids)
        self.assertEqual(violations[0].severity, "WARNING")

        # Good: error with recovery CTA
        good_html = '<p className="text-red-500">Something went wrong. Please click retry to continue.</p>'
        violations = ux.audit_content(good_html, "test.tsx")
        self.assertNotIn("UX-005", [v.rule_id for v in violations])

    def test_cli_fail_on_thresholds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # File with only WARNING (arbitrary token p-[17px])
            warn_file = tmppath / "Warn.tsx"
            warn_file.write_text('<div className="p-[17px]">Warn</div>', encoding="utf-8")

            # Default fail-on is error -> exit code 0
            exit_code = ux.main([str(warn_file), "--quiet", "--fail-on", "error"])
            self.assertEqual(exit_code, 0)

            # fail-on warning -> exit code 1
            exit_code = ux.main([str(warn_file), "--quiet", "--fail-on", "warning"])
            self.assertEqual(exit_code, 1)

            # File with ERROR (unlabelled input)
            err_file = tmppath / "Err.tsx"
            err_file.write_text('<input type="text" />', encoding="utf-8")
            exit_code = ux.main([str(err_file), "--quiet", "--fail-on", "error"])
            self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
