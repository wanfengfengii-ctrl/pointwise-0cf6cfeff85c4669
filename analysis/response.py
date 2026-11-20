"""Reduce a station's measured network to the exact response at chosen terminals.

The reduced matrix is the Dirichlet-to-Neumann (Schur complement) map of the
station's conducting islands onto the selected public terminals.  For terminal
potentials ``v`` the net supply current vector into the fixture is ``Y v`` and
the fixture's total dissipation is ``v^T Y v``.  Unselected nodes carry zero
net current, and islands without a selected terminal are dropped because they
can only have zero injection and zero dissipation.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from analysis.islands import find_islands
from analysis.linear import solve_linear_system
from fixture.terminals import Terminal
from fixture.topology import Topology


@dataclass(frozen=True)
class TerminalResponse:
    matrix: tuple[tuple[Fraction, ...], ...]
    islands: tuple[tuple[int, ...], ...]


def _island_block(
    island, conductance: Mapping[str, Fraction], selected: Sequence[str],
) -> tuple[tuple[Fraction, ...], ...]:
    position = {node: index for index, node in enumerate(island.nodes)}
    size = len(island.nodes)
    zero = Fraction(0)
    laplacian = [[zero] * size for _ in range(size)]
    for branch in island.branches:
        g = conductance[branch.name]
        start = position[branch.start]
        end = position[branch.end]
        laplacian[start][start] += g
        laplacian[end][end] += g
        laplacian[start][end] -= g
        laplacian[end][start] -= g

    terminals = [position[node] for node in selected]
    terminal_set = set(terminals)
    internal = [index for index in range(size) if index not in terminal_set]
    width = len(terminals)
    if internal:
        internal_matrix = [[laplacian[row][column] for column in internal] for row in internal]
        solved_columns = []
        for terminal in terminals:
            rhs = [-laplacian[row][terminal] for row in internal]
            solved_columns.append(solve_linear_system(internal_matrix, rhs))
        rows = []
        for source in terminals:
            row = []
            for column, terminal in enumerate(terminals):
                value = laplacian[source][terminal]
                for offset, node in enumerate(internal):
                    value += laplacian[source][node] * solved_columns[column][offset]
                row.append(value)
            rows.append(tuple(row))
        return tuple(rows)
    return tuple(tuple(laplacian[source][terminal] for terminal in terminals) for source in terminals)


def terminal_response(
    topology: Topology, conductance: Mapping[str, Fraction],
    terminals: Sequence[Terminal],
) -> TerminalResponse:
    """Return the reduced conductance matrix and terminal island partition."""
    selected_nodes = [terminal.node for terminal in terminals]
    width = len(selected_nodes)
    zero = Fraction(0)
    matrix = [[zero] * width for _ in range(width)]
    groups = []
    for island in find_islands(topology, conductance):
        members = set(island.nodes)
        selected = [index for index, node in enumerate(selected_nodes) if node in members]
        if not selected:
            continue
        block = _island_block(island, conductance, [selected_nodes[index] for index in selected])
        for row, source in enumerate(selected):
            for column, target in enumerate(selected):
                matrix[source][target] = block[row][column]
        groups.append(tuple(selected))
    groups.sort(key=lambda group: group[0])
    return TerminalResponse(tuple(tuple(row) for row in matrix), tuple(groups))
