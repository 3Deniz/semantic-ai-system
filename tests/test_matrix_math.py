import unittest

from core.matrix_math import matrix_add, matrix_determinant, matrix_multiply


class TestMatrixDeterminant(unittest.TestCase):
    def test_determinant_2x2(self):
        det, steps = matrix_determinant([[1, 2], [3, 4]])
        self.assertEqual(det, -2)
        self.assertGreaterEqual(len(steps), 1)

    def test_determinant_3x3(self):
        det, steps = matrix_determinant([[1, 2, 3], [0, 1, 4], [5, 6, 0]])
        self.assertEqual(det, 1)
        self.assertGreaterEqual(len(steps), 2)

    def test_determinant_identity(self):
        det, _ = matrix_determinant([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        self.assertEqual(det, 1)


class TestMatrixOperations(unittest.TestCase):
    def test_matrix_multiply_2x2(self):
        result, steps = matrix_multiply([[1, 2], [3, 4]], [[2, 0], [1, 2]])
        self.assertEqual(result, [[4.0, 4.0], [10.0, 8.0]])
        self.assertGreaterEqual(len(steps), 1)

    def test_matrix_add(self):
        result, steps = matrix_add([[1, 2], [3, 4]], [[4, 3], [2, 1]])
        self.assertEqual(result, [[5, 5], [5, 5]])
        self.assertIn("Element-wise addition complete.", steps)

    def test_matrix_multiply_invalid_dimensions(self):
        with self.assertRaises(ValueError):
            matrix_multiply([[1, 2]], [[1, 2]])


if __name__ == "__main__":
    unittest.main()
