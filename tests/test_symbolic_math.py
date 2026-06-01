import unittest

from core.symbolic_math import (
    compute_calculus,
    compute_definite_integral,
    compute_derivative_advanced,
    compute_algebra,
    solve_equation,
    detect_sequence_pattern,
)


class TestSymbolicMathCalculus(unittest.TestCase):
    def test_definite_integral_polynomial(self):
        result = compute_definite_integral("integral from 0 to 2 x^2 dx")
        self.assertIsNotNone(result)
        self.assertEqual(result.result, "2.66666667")

    def test_indefinite_integral_polynomial(self):
        result = compute_calculus("integral 3*x^2 dx")
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, "integral")
        self.assertEqual(result.result, "x^3 + C")

    def test_derivative_simple(self):
        result = compute_calculus("d/dx x")
        self.assertIsNotNone(result)
        self.assertEqual(result.result, "1")

    def test_derivative_polynomial(self):
        result = compute_calculus("d/dx x^3 + 2*x")
        self.assertIsNotNone(result)
        self.assertEqual(result.result, "3*x^2 + 2")

    def test_derivative_trigonometric(self):
        result = compute_calculus("d/dx sin(x)")
        self.assertIsNotNone(result)
        self.assertEqual(result.result, "cos(x)")

    def test_derivative_chain_rule(self):
        result = compute_derivative_advanced("d/dx sin(x^2)")
        self.assertIsNotNone(result)
        self.assertIn("cos(x^2)", result.result)

    def test_derivative_product_rule(self):
        result = compute_derivative_advanced("d/dx x*x")
        self.assertIsNotNone(result)
        self.assertIn("+", result.result)

    def test_logarithm_base10(self):
        result = compute_calculus("log 1000")
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, "logarithm")
        self.assertEqual(result.result, "3")

    def test_logarithm_natural(self):
        result = compute_calculus("ln(e)")
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, "logarithm")
        self.assertEqual(result.result, "1")


class TestSymbolicMathAlgebra(unittest.TestCase):
    def test_matrix_determinant_2x2(self):
        result = compute_algebra("det([[1,2],[3,4]])")
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, "determinant")
        self.assertEqual(result.result, "-2")

    def test_matrix_determinant_3x3(self):
        result = compute_algebra("det([[1,2,3],[0,1,4],[5,6,0]])")
        self.assertIsNotNone(result)
        self.assertEqual(result.kind, "determinant")
        self.assertEqual(result.result, "1")

    def test_solve_linear_equation(self):
        result = solve_equation("solve 2*x + 4 = 0")
        self.assertIsNotNone(result)
        self.assertEqual(result.solutions, [-2.0])

    def test_solve_quadratic_equation(self):
        result = solve_equation("solve x^2 - 5*x + 6 = 0")
        self.assertIsNotNone(result)
        self.assertEqual(result.solutions, [2.0, 3.0])

    def test_solve_equation_no_real_solution(self):
        result = solve_equation("solve x^2 + 1 = 0")
        self.assertIsNotNone(result)
        self.assertEqual(result.solutions, [])


class TestSequencePatternDetection(unittest.TestCase):
    def test_arithmetic_sequence(self):
        result = detect_sequence_pattern([2, 4, 6, 8, 10])
        self.assertIsNotNone(result)
        self.assertEqual(result.pattern_type, "arithmetic")
        self.assertEqual(result.next_value, 12)
        self.assertGreaterEqual(result.confidence, 0.9)

    def test_geometric_sequence(self):
        result = detect_sequence_pattern([2, 4, 8, 16, 32])
        self.assertIsNotNone(result)
        self.assertEqual(result.pattern_type, "geometric")
        self.assertEqual(result.next_value, 64)
        self.assertGreaterEqual(result.confidence, 0.9)

    def test_fibonacci_like_sequence(self):
        result = detect_sequence_pattern([3, 6, 9, 15, 24])
        self.assertIsNotNone(result)
        self.assertEqual(result.pattern_type, "fibonacci_like")
        self.assertEqual(result.next_value, 39)
        self.assertGreaterEqual(result.confidence, 0.85)

    def test_quadratic_sequence(self):
        result = detect_sequence_pattern([1, 4, 9, 16, 25])
        self.assertIsNotNone(result)
        self.assertEqual(result.pattern_type, "quadratic")
        self.assertEqual(result.next_value, 36)
        self.assertGreaterEqual(result.confidence, 0.8)

    def test_alternating_sequence(self):
        result = detect_sequence_pattern([1, 10, 2, 9, 3, 8])
        self.assertIsNotNone(result)
        self.assertEqual(result.pattern_type, "alternating")
        self.assertEqual(result.next_value, 4)
        self.assertGreaterEqual(result.confidence, 0.75)

    def test_constant_sequence(self):
        result = detect_sequence_pattern([7, 7, 7, 7, 7])
        self.assertIsNotNone(result)
        self.assertEqual(result.pattern_type, "arithmetic")
        self.assertEqual(result.next_value, 7)

    def test_too_few_numbers(self):
        result = detect_sequence_pattern([1, 2])
        self.assertIsNone(result)

    def test_no_pattern(self):
        result = detect_sequence_pattern([1, 3, 7, 13, 22])
        self.assertIsNone(result)

    def test_to_dict(self):
        result = detect_sequence_pattern([2, 4, 6])
        self.assertIsNotNone(result)
        d = result.to_dict()
        self.assertEqual(d["type"], "arithmetic")
        self.assertEqual(d["next"], "8")
        self.assertIn("steps", d)
        self.assertIn("formula", d)

    def test_negative_numbers_arithmetic(self):
        result = detect_sequence_pattern([-5, -2, 1, 4, 7])
        self.assertIsNotNone(result)
        self.assertEqual(result.pattern_type, "arithmetic")
        self.assertEqual(result.next_value, 10)
        self.assertEqual(result.to_dict()["next"], "10")


if __name__ == "__main__":
    unittest.main()
