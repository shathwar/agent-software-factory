import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/review/scripts/validate_report.py"
if not SCRIPT.exists() or not SCRIPT.is_file():
    SCRIPT = ROOT / "src/ship/tools/review.py"
try:
    SCRIPT.read_bytes()
except (PermissionError, OSError):
    SCRIPT = ROOT / "src/ship/tools/review.py"
spec = importlib.util.spec_from_file_location("validate_report", SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)

FINDING = {
    "id": "FINDING-001", "severity": "MEDIUM", "category": "Correctness",
    "file": "average.py", "line": "L2", "title": "Empty input crashes instead of returning zero",
    "problem": "Empty input divides by zero.", "evidence": "return sum(values) / len(values)",
    "impact": "Empty requests fail.", "recommendation": "Return zero for an empty input.",
    "confidence": 1.0, "fixability": "autonomous",
}


def report():
    return {"reviewer": "correctness", "status": "complete",
            "findings": [copy.deepcopy(FINDING)], "coverage": ["Inspected average.py."],
            "questions": [], "routing_notes": []}


class ReportTests(unittest.TestCase):
    def test_valid_report_and_empty_report(self):
        data = report()
        self.assertEqual(validator.validate_report(data), [])
        data["findings"] = []
        self.assertEqual(validator.validate_report(data), [])

    def test_invalid_finding_fields(self):
        for field, value in [("severity", "P2"), ("category", "Security"),
                             ("fixability", None), ("confidence", True),
                             ("confidence", -0.1), ("confidence", 1.1),
                             ("confidence", float("nan")), ("line", "L0"),
                             ("line", "L5-L2"), ("evidence", ""), ("evidence", "   "),
                             ("title", "   "), ("problem", "\t\n  "),
                             ("file", "   "),
                             ("file", "/tmp/code.py"), ("file", "../code.py"),
                             ("file", "C:\\code.py")]:
            with self.subTest(field=field, value=value):
                data = report()
                data["findings"][0][field] = value
                self.assertTrue(validator.validate_report(data))

    def test_extra_and_missing_keys(self):
        for field in FINDING:
            data = report()
            del data["findings"][0][field]
            self.assertTrue(validator.validate_report(data), field)
        data = report()
        data["findings"][0]["approved"] = True
        self.assertTrue(validator.validate_report(data))
        data = report()
        data["verdict"] = "APPROVE"
        self.assertTrue(validator.validate_report(data))

    def test_duplicate_ids_with_different_contents(self):
        data = report()
        other = dict(FINDING, title="A different issue using the same ID")
        data["findings"].append(other)
        self.assertTrue(validator.validate_report(data))

    def test_parse_rejects_non_json_numbers_and_duplicate_keys(self):
        for text in ['{"status":"incomplete","status":"complete"}',
                     '{"confidence":NaN}', '{"confidence":Infinity}']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                validator.parse_report(text)

    def test_json_fence(self):
        data = report()
        self.assertEqual(validator.parse_report("```json\n" + json.dumps(data) + "\n```"), data)

    def test_cli_valid_and_invalid(self):
        for text, expected in [(json.dumps(report()), 0), ("{}", 1), ("not json", 1)]:
            result = subprocess.run([sys.executable, str(SCRIPT), "-"], input=text,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, expected, result.stderr)
            if expected:
                self.assertTrue(result.stderr)

    def test_zero_dependency_validation(self):
        data = report()
        # Verify validate_report executes and succeeds without any external libraries
        self.assertEqual(validator.validate_report(data), [])

    def test_schema_json_alignment(self):
        schema_path = ROOT / "skills/review/references/agent_report.schema.json"
        if not schema_path.exists() or not schema_path.is_file():
            schema_path = ROOT / "src/ship/references/agent_report.schema.json"
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
        except (PermissionError, OSError):
            schema_path = ROOT / "src/ship/references/agent_report.schema.json"
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
        self.assertEqual(set(schema["required"]), validator.TOP_REQUIRED)
        self.assertEqual(set(schema["properties"]["reviewer"]["enum"]), validator.REVIEWERS)
        self.assertEqual(set(schema["properties"]["status"]["enum"]), validator.STATUSES)

        finding_schema = schema["properties"]["findings"]["items"]
        self.assertEqual(set(finding_schema["required"]), validator.FINDING_REQUIRED)
        self.assertEqual(set(finding_schema["properties"]["severity"]["enum"]), validator.SEVERITIES)
        self.assertEqual(set(finding_schema["properties"]["category"]["enum"]), validator.CATEGORIES)
        self.assertEqual(set(finding_schema["properties"]["fixability"]["enum"]), validator.FIXABILITIES)
        self.assertEqual(finding_schema["properties"]["id"]["pattern"], validator.ID_REGEX.pattern)
        self.assertEqual(finding_schema["properties"]["line"]["pattern"], validator.LINE_REGEX.pattern)

    def test_unhashable_types_do_not_crash_validator(self):
        # Setting enum fields to unhashable types (list, dict) should return errors, not raise TypeError
        data = report()
        data["reviewer"] = ["judge"]
        errors = validator.validate_report(data)
        self.assertTrue(any("reviewer" in e for e in errors))

        data = report()
        data["status"] = {"complete": True}
        errors = validator.validate_report(data)
        self.assertTrue(any("status" in e for e in errors))

        data = report()
        data["findings"][0]["severity"] = ["CRITICAL"]
        errors = validator.validate_report(data)
        self.assertTrue(any("severity" in e for e in errors))

        data = report()
        data["findings"][0]["category"] = ["Correctness"]
        errors = validator.validate_report(data)
        self.assertTrue(any("category" in e for e in errors))

        data = report()
        data["findings"][0]["fixability"] = ["autonomous"]
        errors = validator.validate_report(data)
        self.assertTrue(any("fixability" in e for e in errors))

    def test_verify_source_evidence_hallucination_rejected(self):
        data = report()
        data["findings"][0]["file"] = "nonexistent_file_xyz.py"
        errors = validator.validate_report(data, verify_source=True, repo_root=ROOT)
        self.assertTrue(any("REV-SRC-001" in e for e in errors))

    def test_manufactured_stylistic_finding_rejected(self):
        data = report()
        data["findings"][0]["severity"] = "CRITICAL"
        data["findings"][0]["title"] = "Violates camelCase naming convention"
        errors = validator.validate_report(data)
        self.assertTrue(any("REV-SEV-001" in e for e in errors))

    def test_review_fixtures(self):
        fixtures_dir = ROOT / "tests/fixtures/review"

        # 01-hallucinated-finding
        f1_data = json.loads((fixtures_dir / "01-hallucinated-finding/report.json").read_text())
        errs_1 = validator.validate_report(f1_data, verify_source=True, repo_root=ROOT)
        self.assertTrue(any("REV-SRC-001" in e for e in errs_1))

        # 02-manufactured-low-value-finding
        f2_data = json.loads((fixtures_dir / "02-manufactured-low-value-finding/report.json").read_text())
        errs_2 = validator.validate_report(f2_data)
        self.assertTrue(any("REV-SEV-001" in e for e in errs_2))

        # 03-schema-violation
        f3_data = json.loads((fixtures_dir / "03-schema-violation/report.json").read_text())
        errs_3 = validator.validate_report(f3_data)
        self.assertTrue(len(errs_3) >= 2)

        # 04-silent-downgrade-bypass
        f4_data = json.loads((fixtures_dir / "04-silent-downgrade-bypass/resolution_ledger.json").read_text())
        self.assertEqual(f4_data["review_resolutions"][0]["status"], "DROPPED_WITHOUT_ACTION")

    def test_evaluate_review_rubric(self):
        sys.path.insert(0, str(ROOT / "tests/evaluation"))
        import evaluate_review_rubric

        evaluator = evaluate_review_rubric.ReviewRubricEvaluator(passing_threshold=0.80)

        # 1. Clean review
        clean_rep = {"reviewer": "judge", "status": "complete", "findings": [], "coverage": ["All files inspected."]}
        res_clean = evaluator.evaluate_report(clean_rep, "CleanReport")
        self.assertFalse(res_clean.passed)  # Missing required report fields.
        self.assertEqual(res_clean.status, "FAIL")

        # 2. Material defect report
        mat_rep = {
            "reviewer": "judge", "status": "complete",
            "findings": [
                {
                    "id": "FINDING-001", "severity": "CRITICAL", "category": "Correctness",
                    "file": "src/auth.py", "line": "L10-L15", "title": "SQL injection in query",
                    "problem": "Unescaped user parameter in raw SQL statement.",
                    "evidence": "db.execute(f'SELECT * FROM users WHERE id = {user_id}')",
                    "impact": "Remote code execution or arbitrary data exfiltration.",
                    "recommendation": "Use parameterized query: db.execute('SELECT * FROM users WHERE id = %s', (user_id,))",
                    "confidence": 1.0, "fixability": "autonomous"
                }
            ]
        }
        res_mat = evaluator.evaluate_report(mat_rep, "MaterialReport")
        self.assertFalse(res_mat.passed)  # Plausible prose is not a valid report.
        self.assertEqual(res_mat.status, "FAIL")

        # 3. Bikeshedding report
        bike_rep = {
            "reviewer": "judge", "status": "complete",
            "findings": [
                {
                    "id": "FINDING-001", "severity": "CRITICAL", "category": "Maintainability",
                    "file": "src/auth.py", "line": "L1", "title": "camelCase naming convention",
                    "problem": "Variable name violates camelCase naming convention.",
                    "evidence": "const x = 1;", "impact": "Code style is degraded.",
                    "recommendation": "Rename variable.", "confidence": 0.5, "fixability": "autonomous"
                }
            ]
        }
        res_bike = evaluator.evaluate_report(bike_rep, "BikeshedReport")
        self.assertFalse(res_bike.passed)


if __name__ == "__main__":
    unittest.main()
