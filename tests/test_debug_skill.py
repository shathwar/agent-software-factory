"""Unit tests for the debug skill verification engine (verify_fix.py)."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/debug/scripts"))

import verify_fix


class DebugSkillTests(unittest.TestCase):
    def test_is_test_file(self):
        """Verify test file path matching."""
        self.assertTrue(verify_fix.is_test_file("tests/test_api.py"))
        self.assertTrue(verify_fix.is_test_file("src/foo_test.go"))
        self.assertTrue(verify_fix.is_test_file("specs/worker.spec.ts"))
        self.assertFalse(verify_fix.is_test_file("src/engine/worker.py"))
        self.assertFalse(verify_fix.is_test_file("lib/auth.ts"))

    def test_audit_diff_clean_bugfix(self):
        """A bugfix modifying production code and adding a test passes."""
        diff = """diff --git a/src/calc.py b/src/calc.py
--- a/src/calc.py
+++ b/src/calc.py
@@ -10,2 +10,2 @@
-    return a / b
+    if b == 0: raise ValueError('Zero division')
+    return a / b
diff --git a/tests/test_calc.py b/tests/test_calc.py
--- a/tests/test_calc.py
+++ b/tests/test_calc.py
@@ -20,2 +20,4 @@
+def test_calc_zero_division():
+    with pytest.raises(ValueError):
+        calc(1, 0)
"""
        result = verify_fix.audit_diff(diff)
        self.assertTrue(result.passed)
        self.assertTrue(result.repro_test_found)
        self.assertEqual(len(result.violations), 0)

    def test_audit_diff_missing_repro_test(self):
        """Modifying production code without a test violates reproduction mandate."""
        diff = """diff --git a/src/calc.py b/src/calc.py
--- a/src/calc.py
+++ b/src/calc.py
@@ -10,2 +10,2 @@
-    return a / b
+    return a / max(b, 1)
"""
        result = verify_fix.audit_diff(diff)
        self.assertFalse(result.passed)
        self.assertFalse(result.repro_test_found)
        self.assertTrue(any("Reproduction Mandate" in v for v in result.violations))

    def test_audit_diff_symptom_masking(self):
        """Bare except: pass or swallowed errors flag symptom masking violations."""
        diff = """diff --git a/src/worker.py b/src/worker.py
--- a/src/worker.py
+++ b/src/worker.py
@@ -10,2 +10,4 @@
+    try:
+        run()
+    except: pass
diff --git a/tests/test_worker.py b/tests/test_worker.py
--- a/tests/test_worker.py
+++ b/tests/test_worker.py
@@ -5,1 +5,2 @@
+    assert True
"""
        result = verify_fix.audit_diff(diff)
        self.assertFalse(result.passed)
        self.assertTrue(any("Symptom Masking" in v for v in result.violations))

    def test_audit_diff_test_weakening(self):
        """Adding @pytest.mark.skip or xit flags test weakening violations."""
        diff = """diff --git a/src/worker.py b/src/worker.py
--- a/src/worker.py
+++ b/src/worker.py
@@ -10,1 +10,1 @@
+    x = 1
diff --git a/tests/test_worker.py b/tests/test_worker.py
--- a/tests/test_worker.py
+++ b/tests/test_worker.py
@@ -5,2 +5,3 @@
+@pytest.mark.skip(reason="broken")
 def test_worker():
"""
        result = verify_fix.audit_diff(diff)
        self.assertFalse(result.passed)
        self.assertTrue(any("Test Weakening" in v for v in result.violations))

    def test_audit_diff_multi_file_assertion_degradation(self):
        """Deleting test assertions in a test file preceding a production file is flagged."""
        diff = """diff --git a/tests/test_worker.py b/tests/test_worker.py
--- a/tests/test_worker.py
+++ b/tests/test_worker.py
@@ -5,2 +5,1 @@
-    assert worker.is_valid()
+    pass
diff --git a/src/worker.py b/src/worker.py
--- a/src/worker.py
+++ b/src/worker.py
@@ -10,1 +10,1 @@
-    x = 0
+    x = 1
"""
        result = verify_fix.audit_diff(diff)
        self.assertFalse(result.passed)
        self.assertTrue(any("Assertion Degradation" in v for v in result.violations))

    def test_audit_diff_multiline_symptom_masking(self):
        """Multiline except Exception: with comments and pass flags symptom masking."""
        diff = """diff --git a/src/worker.py b/src/worker.py
--- a/src/worker.py
+++ b/src/worker.py
@@ -10,1 +10,4 @@
+    try:
+        run()
+    except Exception:
+        # swallowed error
+        pass
diff --git a/tests/test_worker.py b/tests/test_worker.py
--- a/tests/test_worker.py
+++ b/tests/test_worker.py
@@ -5,1 +5,2 @@
+    assert True
"""
        result = verify_fix.audit_diff(diff)
        self.assertFalse(result.passed)
        self.assertTrue(any("Symptom Masking" in v for v in result.violations))


if __name__ == "__main__":
    unittest.main()
