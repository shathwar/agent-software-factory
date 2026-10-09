"""Unit tests for the debug skill verification engine (verify_fix.py) and L5 outcome rubric."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "skills/debug/scripts"))
sys.path.insert(0, str(ROOT / "tests/evaluation"))

try:
    import verify_fix
except (ImportError, PermissionError):
    from ship.tools import debug as verify_fix
from evaluate_debug_rubric import DebugRubricEvaluator


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
+    assert worker.status == "OK"
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
+    assert worker.done is True
"""
        result = verify_fix.audit_diff(diff)
        self.assertFalse(result.passed)
        self.assertTrue(any("Symptom Masking" in v for v in result.violations))

    def test_audit_diff_tautological_repro_test(self):
        """Tautological assertions like assert True are flagged as hollow repro tests."""
        diff = """diff --git a/src/calc.py b/src/calc.py
--- a/src/calc.py
+++ b/src/calc.py
@@ -1,1 +1,1 @@
+x = 1
diff --git a/tests/test_calc.py b/tests/test_calc.py
--- a/tests/test_calc.py
+++ b/tests/test_calc.py
@@ -1,1 +1,2 @@
+def test_repro():
+    assert True
"""
        result = verify_fix.audit_diff(diff)
        self.assertFalse(result.passed)
        self.assertTrue(any("Hollow Repro Test" in v for v in result.violations))

    def test_audit_diff_defensive_null_guard(self):
        """Defensive null guard returning early at point of impact is flagged."""
        diff = """diff --git a/src/service.py b/src/service.py
--- a/src/service.py
+++ b/src/service.py
@@ -10,1 +10,2 @@
+    if item is None: return None
     return item.price
diff --git a/tests/test_service.py b/tests/test_service.py
--- a/tests/test_service.py
+++ b/tests/test_service.py
@@ -1,1 +1,2 @@
+def test_service():
+    assert service(None) is None
"""
        result = verify_fix.audit_diff(diff)
        self.assertFalse(result.passed)
        self.assertTrue(any("Defensive null guard" in v for v in result.violations))

    def test_audit_diff_defensive_null_guard_with_comment(self):
        """Null guard tagged with # root-cause-guard is exempted from symptom masking violation."""
        diff = """diff --git a/src/service.py b/src/service.py
--- a/src/service.py
+++ b/src/service.py
@@ -10,1 +10,2 @@
+    if item is None: return None  # root-cause-guard
     return item.price
diff --git a/tests/test_service.py b/tests/test_service.py
--- a/tests/test_service.py
+++ b/tests/test_service.py
@@ -1,1 +1,2 @@
+def test_service():
+    assert service(None) is None
"""
        result = verify_fix.audit_diff(diff)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.violations), 0)

    def test_fixtures(self):
        """Test verification against all 4 adversarial fixtures."""
        fixtures_dir = ROOT / "tests/fixtures/debug"

        # Fixture 1: Symptom masking null guard
        diff_1 = (fixtures_dir / "01-symptom-masking-null-guard/patch.diff").read_text(encoding="utf-8")
        res_1 = verify_fix.audit_diff(diff_1)
        self.assertFalse(res_1.passed)
        self.assertTrue(any("Defensive null guard" in v for v in res_1.violations))

        # Fixture 2: Hollow reproduction test
        diff_2 = (fixtures_dir / "02-hollow-reproduction-test/patch.diff").read_text(encoding="utf-8")
        res_2 = verify_fix.audit_diff(diff_2)
        self.assertFalse(res_2.passed)
        self.assertTrue(any("Hollow Repro Test" in v for v in res_2.violations))

        # Fixture 3: Test assertion weakening
        diff_3 = (fixtures_dir / "03-test-assertion-weakening/patch.diff").read_text(encoding="utf-8")
        res_3 = verify_fix.audit_diff(diff_3)
        self.assertFalse(res_3.passed)
        self.assertTrue(any("Test Weakening" in v for v in res_3.violations))

        # Fixture 4: Excessive scope creep
        diff_4 = (fixtures_dir / "04-excessive-scope-creep/patch.diff").read_text(encoding="utf-8")
        res_4 = verify_fix.audit_diff(diff_4)
        self.assertFalse(res_4.passed)
        self.assertTrue(any("Excessive Scope" in v for v in res_4.violations))

    def test_l5_rubric_evaluator(self):
        """Test L5 outcome quality rubric evaluator against exemplary and flawed records."""
        evaluator = DebugRubricEvaluator()

        exemplary_record = {
            "hypothesis": "NullPointerException occurs because invoice generator assumes user.account is populated, but OAuth signup does not initialize account record.",
            "causal_trace": ["billing.py:45", "user_service.py:112", "oauth_handler.py:28"],
            "point_of_impact": "billing.py:45",
            "root_cause_origin": "oauth_handler.py:28",
            "repro_test_found": True,
            "reproduction_test": {
                "red_proven": True,
                "assertions": ["assert user.account is not None", "assert invoice.amount == 100"],
            },
            "prod_files_modified": ["src/oauth_handler.py"],
            "total_prod_lines_added": 8,
            "violations": [],
        }

        report = evaluator.evaluate_bugfix(exemplary_record)
        self.assertTrue(report.passed)
        self.assertGreaterEqual(report.overall_score, 0.85)

        flawed_record = {
            "hypothesis": "",
            "causal_trace": [],
            "point_of_impact": "billing.py:45",
            "root_cause_origin": "billing.py:45",
            "repro_test_found": True,
            "reproduction_test": {
                "red_proven": False,
                "assertions": ["assert True"],
            },
            "prod_files_modified": ["src/a.py", "src/b.py", "src/c.py", "src/d.py", "src/e.py", "src/f.py"],
            "total_prod_lines_added": 200,
            "violations": [
                "[billing.py] Symptom Masking Anti-Pattern: Defensive null guard returning early at point of impact."
            ],
        }

        report_bad = evaluator.evaluate_bugfix(flawed_record)
        self.assertFalse(report_bad.passed)
        self.assertLess(report_bad.overall_score, 0.50)


if __name__ == "__main__":
    unittest.main()
