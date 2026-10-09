"""Unit tests for the evals skill tooling (score_calibration, sample_traces, serve_review_app, L5 rubric)."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "skills/evals/scripts"))
sys.path.insert(0, str(ROOT / "tests/evaluation"))

try:
    import score_calibration
except (ImportError, PermissionError):
    from ship.tools import evals as score_calibration

try:
    import sample_traces
except (ImportError, PermissionError):
    from ship.tools import sample_traces
from evaluate_evals_rubric import EvalsRubricEvaluator


class EvalsSkillTests(unittest.TestCase):
    def test_score_calibration_metrics(self):
        """Test TPR, TNR, confusion matrix and accuracy calculations."""
        pairs = [
            ("Pass", "Pass"),
            ("Pass", "Pass"),
            ("Pass", "Pass"),
            ("Pass", "Pass"),
            ("Pass", "Fail"),
            ("Fail", "Fail"),
            ("Fail", "Fail"),
            ("Fail", "Fail"),
            ("Fail", "Fail"),
            ("Fail", "Pass"),
        ]

        metrics = score_calibration.compute_metrics(pairs)
        self.assertEqual(metrics["tp"], 4)
        self.assertEqual(metrics["fn"], 1)
        self.assertEqual(metrics["tn"], 4)
        self.assertEqual(metrics["fp"], 1)
        self.assertAlmostEqual(metrics["tpr"], 0.80)
        self.assertAlmostEqual(metrics["tnr"], 0.80)
        self.assertAlmostEqual(metrics["accuracy"], 0.80)

    def test_rogan_gladen_correction(self):
        """Test Rogan-Gladen formula calculation."""
        theta = score_calibration.rogan_gladen_correction(p_obs=0.80, tpr=0.92, tnr=0.88)
        self.assertIsNotNone(theta)
        self.assertAlmostEqual(theta, 0.85, places=3)

    def test_bootstrap_ci(self):
        """Test bootstrap confidence interval estimation."""
        pairs = [("Pass", "Pass")] * 40 + [("Fail", "Fail")] * 40 + [("Pass", "Fail")] * 10 + [("Fail", "Pass")] * 10
        lower, upper = score_calibration.bootstrap_ci(pairs, p_obs=0.50, n_bootstrap=200, seed=42)
        self.assertIsNotNone(lower)
        self.assertIsNotNone(upper)
        self.assertTrue(0.0 <= lower <= upper <= 1.0)

    def test_load_pairs_jsonl(self):
        """Test loading predictions from a JSONL file."""
        with tempfile.NamedTemporaryFile("w+", suffix=".jsonl", delete=False) as tmp:
            tmp.write(json.dumps({"human": "Pass", "evaluator": "Pass"}) + "\n")
            tmp.write(json.dumps({"ground_truth": "Fail", "prediction": "Fail"}) + "\n")
            tmp.write(json.dumps({"label": "Pass", "judge": "Fail"}) + "\n")
            tmp_path = Path(tmp.name)

        try:
            pairs = score_calibration.load_pairs(tmp_path)
            self.assertEqual(len(pairs), 3)
            self.assertEqual(pairs[0], ("Pass", "Pass"))
            self.assertEqual(pairs[1], ("Fail", "Fail"))
            self.assertEqual(pairs[2], ("Pass", "Fail"))
        finally:
            tmp_path.unlink()

    def test_sample_traces_diversity(self):
        """Test sampling diverse traces across feature buckets."""
        traces = []
        for i in range(50):
            traces.append({
                "trace_id": f"t_{i}",
                "input": f"User question {i}",
                "output": "Short" if i % 2 == 0 else "Long " * 150,
                "tool_calls": [{"name": "search"}] if i % 3 == 0 else [],
                "error": True if i % 5 == 0 else False,
            })

        sample = sample_traces.select_diverse_sample(traces, n_samples=15, seed=42)
        self.assertEqual(len(sample), 15)
        ids = [t["trace_id"] for t in sample]
        self.assertEqual(len(ids), len(set(ids)))

    def test_split_isolation_detection(self):
        """Test detection of data leakage between train and test sets (EVL-LEAK-001)."""
        train_clean = ["id1", "id2", "id3"]
        test_clean = ["id4", "id5", "id6"]
        passed, errors = score_calibration.verify_split_isolation(train_clean, test_clean)
        self.assertTrue(passed)
        self.assertEqual(len(errors), 0)

        train_leaky = ["id1", "id2", "leak_shared"]
        test_leaky = ["leak_shared", "id4", "id5"]
        passed, errors = score_calibration.verify_split_isolation(train_leaky, test_leaky)
        self.assertFalse(passed)
        self.assertTrue(any("EVL-LEAK-001" in err for err in errors))
        self.assertTrue(any("leak_shared" in err for err in errors))

    def test_audit_judge_rubric_clean(self):
        """Test that a rigorous binary rubric with reasoning passes audit."""
        prompt = """
        You are an evaluator assessing factual consistency.
        Model: gpt-4o-2024-08-06

        First provide a step-by-step critique of the claims.
        Then provide your final decision: Pass if completely faithful, Fail if any unsupported claim is made.
        Verdict: [Pass / Fail]
        """
        passed, errors = score_calibration.audit_judge_rubric(prompt)
        self.assertTrue(passed)
        self.assertEqual(len(errors), 0)

    def test_audit_judge_rubric_anti_patterns(self):
        """Test detection of Likert scale, missing reasoning, and unpinned model."""
        # 1. Likert scale (EVL-RUB-001)
        prompt_likert = "Rate the response on a scale of 1 to 5. Explain your reasoning."
        passed, errors = score_calibration.audit_judge_rubric(prompt_likert)
        self.assertFalse(passed)
        self.assertTrue(any("EVL-RUB-001" in err for err in errors))

        # 2. Missing reasoning (EVL-RUB-002)
        prompt_no_critique = "Decide if this is Pass or Fail. Model: gpt-4o-2024-08-06. Output verdict immediately."
        passed, errors = score_calibration.audit_judge_rubric(prompt_no_critique)
        self.assertFalse(passed)
        self.assertTrue(any("EVL-RUB-002" in err for err in errors))

        # 3. Unpinned model (EVL-MOD-001)
        prompt_unpinned = "Critique step-by-step. Pass or Fail. Model: gpt-4o"
        passed, errors = score_calibration.audit_judge_rubric(prompt_unpinned)
        self.assertFalse(passed)
        self.assertTrue(any("EVL-MOD-001" in err for err in errors))

    def test_fixtures(self):
        """Test verification against all 4 adversarial fixtures."""
        fixtures_dir = ROOT / "tests/fixtures/evals"

        # Fixture 1: Data split leakage
        with open(fixtures_dir / "01-data-split-leakage/manifest.json") as f:
            manifest = json.load(f)
        passed, errors = score_calibration.verify_split_isolation(manifest["train"], manifest["test"])
        self.assertFalse(passed)
        self.assertTrue(any("EVL-LEAK-001" in err for err in errors))

        # Fixture 2: Likert scale judge
        with open(fixtures_dir / "02-likert-scale-judge/prompt.md") as f:
            prompt_content = f.read()
        passed, errors = score_calibration.audit_judge_rubric(prompt_content)
        self.assertFalse(passed)
        self.assertTrue(any("EVL-RUB-001" in err for err in errors))

        # Fixture 3: Imbalanced accuracy trap
        pairs = score_calibration.load_pairs(fixtures_dir / "03-imbalanced-accuracy-trap/predictions.jsonl")
        metrics = score_calibration.compute_metrics(pairs)
        self.assertAlmostEqual(metrics["accuracy"], 0.95)
        self.assertAlmostEqual(metrics["tnr"], 0.0)  # Complete failure to detect negative class

        # Fixture 4: Uncalibrated prevalence claim
        with open(fixtures_dir / "04-uncalibrated-prevalence-claim/report.json") as f:
            report_data = json.load(f)
        prod = report_data["production_monitoring"]
        self.assertFalse(prod["rogan_gladen_corrected"])
        self.assertEqual(prod["claimed_success_rate"], prod["observed_pass_rate"])

    def test_l5_rubric_evaluator(self):
        """Test L5 outcome quality rubric evaluator against exemplary and flawed specs."""
        evaluator = EvalsRubricEvaluator()

        exemplary_spec = {
            "evaluators": [
                {"name": "json_validator", "type": "code"},
                {"name": "tool_call_schema", "type": "code"},
                {
                    "name": "faithfulness_judge",
                    "type": "llm_judge",
                    "model": "gpt-4o-2024-08-06",
                    "prompt": "First critique step-by-step. Output Pass or Fail.",
                },
            ],
            "splits": {
                "train": ["tr_1", "tr_2"],
                "test": ["te_3", "te_4"],
            },
            "calibration": {
                "tpr": 0.92,
                "tnr": 0.90,
            },
            "production_monitoring": {
                "observed_pass_rate": 0.88,
                "claimed_success_rate": 0.9512195121951219,
                "corrected_rate": 0.9512195121951219,
                "rogan_gladen_corrected": True,
                "ci_95": [0.90, 0.99],
            },
        }

        report = evaluator.evaluate_eval_suite(exemplary_spec)
        self.assertTrue(report.passed)
        self.assertGreaterEqual(report.overall_score, 0.85)

        flawed_spec = {
            "evaluators": [
                {
                    "name": "check_json_validity",
                    "type": "llm_judge",
                    "model": "gpt-4o-latest",
                    "prompt": "Rate how valid the json is on a scale of 1 to 5.",
                }
            ],
            "splits": {
                "train": ["dup_1"],
                "test": ["dup_1"],
            },
            "calibration": {
                "accuracy_only": True,
                "accuracy": 0.95,
            },
            "production_monitoring": {
                "observed_pass_rate": 0.95,
                "claimed_success_rate": 0.95,
                "rogan_gladen_corrected": False,
            },
        }

        report_bad = evaluator.evaluate_eval_suite(flawed_spec)
        self.assertFalse(report_bad.passed)
        self.assertLess(report_bad.overall_score, 0.50)

    def test_pydantic_judge_template(self):
        """Test that the 1-click Pydantic judge template is present and contains required fields."""
        tmpl = score_calibration.PYDANTIC_JUDGE_TEMPLATE
        self.assertIn("class JudgeVerdict(BaseModel):", tmpl)
        self.assertIn("reasoning: str", tmpl)
        self.assertIn("passed: bool", tmpl)
        self.assertIn("gpt-4o-2024-08-06", tmpl)

    def test_infer_p_obs_calculation(self):
        """Test that infer_p_obs automatically calculates sample pass rate when p_obs is None."""
        pairs = [("Pass", "Pass")] * 8 + [("Fail", "Fail")] * 2
        # Evaluator judged 8 passes out of 10 -> 80% pass rate
        res = score_calibration.evaluate_calibration(pairs, p_obs=None, infer_p_obs=True, n_bootstrap=100)
        self.assertIn("bias_correction", res)
        bc = res["bias_correction"]
        self.assertTrue(bc["inferred"])
        self.assertAlmostEqual(bc["p_obs"], 0.80)
        self.assertIsNotNone(bc["corrected_rate"])

    def test_micro_tier_split_isolation(self):
        """Test 2-way split verification for micro tier (<50 traces)."""
        few_shots = ["seed_trace_1", "seed_trace_2", "seed_trace_3"]
        held_out_test = ["test_trace_1", "test_trace_2", "test_trace_3", "test_trace_4"]
        passed, errors = score_calibration.verify_split_isolation(few_shots, held_out_test)
        self.assertTrue(passed)
        self.assertEqual(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
