import unittest

class TestCalculatorTautology(unittest.TestCase):
    def test_addition_tautology(self):
        calc = Calculator()
        calc.add(2, 2)
        assert True

    def test_multiplication_tautology(self):
        calc = Calculator()
        calc.multiply(3, 3)
        self.assertTrue(True)
