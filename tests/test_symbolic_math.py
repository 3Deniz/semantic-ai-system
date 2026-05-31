import unittest

from core.symbolic_math import (
    compute_calculus,
    compute_definite_integral,
    compute_derivative_advanced,
    compute_algebra,
    solve_equation,
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


if __name__ == "__main__":
    unittest.main()
