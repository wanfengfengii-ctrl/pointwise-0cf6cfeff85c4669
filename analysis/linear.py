"""Exact elimination for a square, uniquely solvable system."""

from collections.abc import Sequence
from fractions import Fraction


def solve_linear_system(
    matrix: Sequence[Sequence[int | Fraction]], rhs: Sequence[int | Fraction],
) -> tuple[Fraction, ...]:
    size = len(rhs)
    if len(matrix) != size or any(len(row) != size for row in matrix):
        raise ValueError('matrix and right-hand side do not form a square system')
    rows = [[Fraction(value) for value in row] + [Fraction(target)]
            for row, target in zip(matrix, rhs)]

    for column in range(size):
        pivot = next((row for row in range(column, size) if rows[row][column]), None)
        if pivot is None:
            raise ValueError('singular linear system')
        rows[column], rows[pivot] = rows[pivot], rows[column]
        pivot_row = rows[column]
        for row in rows[column + 1:]:
            if row[column] == 0:
                continue
            factor = row[column] / pivot_row[column]
            row[column] = Fraction(0)
            for offset in range(column + 1, size + 1):
                row[offset] -= factor * pivot_row[offset]

    solution = [Fraction(0)] * size
    for index in range(size - 1, -1, -1):
        row = rows[index]
        known = sum((row[column] * solution[column] for column in range(index + 1, size)), Fraction(0))
        solution[index] = (row[size] - known) / row[index]
    return tuple(solution)
