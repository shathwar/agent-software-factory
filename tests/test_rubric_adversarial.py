"""Lifecycle rubric control; specialist controls are now Bun migration contracts."""
import unittest
from tests.evaluation.evaluate_ship_rubric import ShipRubricEvaluator


class RubricAdversarialTests(unittest.TestCase):
    def test_empty_ship_artifact_never_passes(self):
        self.assertFalse(ShipRubricEvaluator().evaluate_delivery("").passed)
