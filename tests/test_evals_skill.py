"""Unit tests for the evals skill tooling (score_calibration, sample_traces, serve_review_app)."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/evals/scripts"))

import sample_traces
import score_calibration


class EvalsSkillTests(unittest.TestCase):
    def test_score_calibration_metrics(self):
        """Test TPR, TNR, confusion matrix and accuracy calculations."""
        # 4 TP, 1 FN (total human pass = 5 -> TPR = 4/5 = 0.8)
        # 4 TN, 1 FP (total human fail = 5 -> TNR = 4/5 = 0.8)
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
        # TPR = 0.92, TNR = 0.88, p_obs = 0.80
        # (0.80 + 0.88 - 1.0) / (0.92 + 0.88 - 1.0) = 0.68 / 0.80 = 0.85
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
        # Verify ids are unique
        ids = [t["trace_id"] for t in sample]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
