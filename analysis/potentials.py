"""Solve the internal node voltages in each referenced local island."""

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from analysis.clamps import ClampSet
from analysis.islands import ConductingIsland
from analysis.linear import solve_linear_system


@dataclass(frozen=True)
class LocalPotentials:
    voltages: dict[str, Fraction]


def solve_potentials(
    islands: tuple[ConductingIsland, ...], conductance: Mapping[str, Fraction], clamps: ClampSet,
) -> LocalPotentials:
    fixed = clamps.by_node()
    voltages = dict(fixed)
    zero = Fraction(0)
    for island in islands:
        unknown = [node for node in island.nodes if node not in fixed]
        if not unknown:
            continue
        index = {node: position for position, node in enumerate(unknown)}
        size = len(unknown)
        matrix = [[zero] * size for _ in unknown]
        rhs = [zero] * size
        for branch in island.branches:
            g = conductance[branch.name]
            for node, neighbor in ((branch.start, branch.end), (branch.end, branch.start)):
                if node not in index:
                    continue
                row = index[node]
                matrix[row][row] += g
                if neighbor in fixed:
                    rhs[row] += g * fixed[neighbor]
                else:
                    matrix[row][index[neighbor]] -= g
        voltages.update(zip(unknown, solve_linear_system(matrix, rhs)))
    return LocalPotentials(voltages)
