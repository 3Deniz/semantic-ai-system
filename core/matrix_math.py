from __future__ import annotations

import math


def matrix_determinant(matrix: list[list[float]]) -> tuple[float, list[str]]:
    steps: list[str] = []
    n = len(matrix)

    if n == 2 and len(matrix[0]) == 2:
        a, b = matrix[0]
        c, d = matrix[1]
        det = a * d - b * c
        steps.append(f"2x2 determinant: ({a})*({d}) - ({b})*({c}) = {_format_number(det)}")
        return det, steps

    if n == 3 and len(matrix[0]) == 3:
        a, b, c = matrix[0]
        d, e, f = matrix[1]
        g, h, i = matrix[2]
        term1 = a * (e * i - f * h)
        term2 = b * (d * i - f * g)
        term3 = c * (d * h - e * g)
        det = term1 - term2 + term3
        steps.append(f"3x3 determinant: {_format_number(a)}*({_format_number(e)}*{_format_number(i)} - {_format_number(f)}*{_format_number(h)})")
        steps.append(f"  - {_format_number(b)}*({_format_number(d)}*{_format_number(i)} - {_format_number(f)}*{_format_number(g)})")
        steps.append(f"  + {_format_number(c)}*({_format_number(d)}*{_format_number(h)} - {_format_number(e)}*{_format_number(g)})")
        steps.append(f"Result = {_format_number(det)}")
        return det, steps

    raise ValueError(f"Unsupported matrix size: {n}x{len(matrix[0])}")


def matrix_multiply(A: list[list[float]], B: list[list[float]]) -> tuple[list[list[float]], list[str]]:
    steps: list[str] = []
    rows_a, cols_a = len(A), len(A[0])
    rows_b, cols_b = len(B), len(B[0])

    if cols_a != rows_b:
        raise ValueError(f"Incompatible dimensions: {rows_a}x{cols_a} * {rows_b}x{cols_b}")

    result = [[0.0] * cols_b for _ in range(rows_a)]
    steps.append(f"Matrix multiply {rows_a}x{cols_a} * {rows_b}x{cols_b}")

    for i in range(rows_a):
        for j in range(cols_b):
            total = 0.0
            terms: list[str] = []
            for k in range(cols_a):
                prod = A[i][k] * B[k][j]
                total += prod
                terms.append(f"{_format_number(A[i][k])}*{_format_number(B[k][j])}")
            result[i][j] = total
            steps.append(f"  C[{i+1},{j+1}] = {' + '.join(terms)} = {_format_number(total)}")

    return result, steps


def matrix_add(A: list[list[float]], B: list[list[float]]) -> tuple[list[list[float]], list[str]]:
    steps: list[str] = []
    rows, cols = len(A), len(A[0])
    result = [[0.0] * cols for _ in range(rows)]
    steps.append(f"Matrix add {rows}x{cols}")
    for i in range(rows):
        for j in range(cols):
            result[i][j] = A[i][j] + B[i][j]
    steps.append("Element-wise addition complete.")
    return result, steps


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")
