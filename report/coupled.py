"""Bind a cross-fixture request and solve the actual conducting components.

Every station terminal is one node.  The station block is the exact reduced
terminal response matrix of its piece; positive jumpers add symmetric edges
between the two slots.  Net injection is checked on each conducting component
of that combined network, and all listed conductances are reported exactly.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from analysis.linear import solve_linear_system
from fixture.topology import ordered_items, require_name, row_fields
from intake.units import parse_rational
from report.piece import TerminalPiece


@dataclass(frozen=True)
class Endpoint:
    slot: int
    terminal: str


@dataclass(frozen=True)
class Jumper:
    name: str
    start: Endpoint
    end: Endpoint
    conductance: Fraction


@dataclass(frozen=True)
class CoupledRequest:
    pieces: tuple[TerminalPiece, ...]
    jumpers: tuple[Jumper, ...]
    injections: tuple[tuple[Endpoint, Fraction], ...]


@dataclass(frozen=True)
class CoupledResult:
    feasible: bool
    jumper_currents: tuple[Fraction, ...] | None
    dissipation: tuple[Fraction, ...] | None


def _endpoint(value: object, pieces: Sequence[TerminalPiece], field: str) -> Endpoint:
    slot, name = row_fields(value, 2, field)
    if type(slot) is not int or slot not in (0, 1):
        raise ValueError(f'{field} slot must be integer 0 or 1')
    terminal = require_name(name, f'{field} terminal')
    if terminal not in pieces[slot].terminals:
        raise ValueError(f'{field} terminal {terminal!r} is not listed on slot {slot}')
    return Endpoint(slot, terminal)


def _feasibility_components(
    pieces: tuple[TerminalPiece, ...], jumpers: tuple[Jumper, ...],
) -> list[list[tuple[int, int]]]:
    nodes = [(slot, index) for slot, piece in enumerate(pieces)
             for index in range(len(piece.terminals))]
    parent = {node: node for node in nodes}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left, right):
        left = find(left)
        right = find(right)
        if left != right:
            parent[right] = left

    for slot, piece in enumerate(pieces):
        for group in piece.islands:
            anchor = (slot, group[0])
            for index in group[1:]:
                union(anchor, (slot, index))
    for jumper in jumpers:
        if jumper.conductance > 0:
            left = (jumper.start.slot, pieces[jumper.start.slot].terminals.index(jumper.start.terminal))
            right = (jumper.end.slot, pieces[jumper.end.slot].terminals.index(jumper.end.terminal))
            union(left, right)

    groups = {}
    for node in nodes:
        groups.setdefault(find(node), []).append(node)
    return list(groups.values())


def build_request(pieces: object, jumper_rows: object, injection_rows: object) -> CoupledRequest:
    slots = ordered_items(pieces, 'pieces')
    if len(slots) != 2:
        raise ValueError('a cross-fixture request selects exactly two pieces')
    for piece in slots:
        if not isinstance(piece, TerminalPiece):
            raise ValueError('a cross-fixture request requires accepted terminal pieces')
    left, right = slots

    jumpers = []
    names = set()
    for row in ordered_items(jumper_rows, 'jumpers'):
        name, start, end, conductance = row_fields(row, 4, 'jumper')
        name = require_name(name, 'jumper name')
        if name in names:
            raise ValueError(f'duplicate jumper {name!r}')
        names.add(name)
        start = _endpoint(start, slots, 'jumper start')
        end = _endpoint(end, slots, 'jumper end')
        if start.slot == end.slot:
            raise ValueError(f'jumper {name!r} must connect the two slots')
        value = parse_rational(conductance, 'jumper conductance')
        if value < 0:
            raise ValueError(f'jumper {name!r} conductance must be nonnegative')
        jumpers.append(Jumper(name, start, end, value))

    injections = []
    seen = set()
    for row in ordered_items(injection_rows, 'injections'):
        endpoint, amount = row_fields(row, 2, 'injection')
        endpoint = _endpoint(endpoint, slots, 'injection')
        if (endpoint.slot, endpoint.terminal) in seen:
            raise ValueError(f'duplicate injection for {endpoint.slot}:{endpoint.terminal}')
        seen.add((endpoint.slot, endpoint.terminal))
        injections.append((endpoint, parse_rational(amount, 'injection')))
    return CoupledRequest((left, right), tuple(jumpers), tuple(injections))


def solve_request(request: CoupledRequest) -> CoupledResult:
    pieces = request.pieces
    positions = {}
    for slot, piece in enumerate(pieces):
        for index, terminal in enumerate(piece.terminals):
            positions[(slot, terminal)] = (slot, index)
    nodes = list(positions.values())
    lookup = {node: offset for offset, node in enumerate(nodes)}
    size = len(nodes)
    zero = Fraction(0)

    net = [zero] * size
    for endpoint, amount in request.injections:
        net[lookup[positions[(endpoint.slot, endpoint.terminal)]]] += amount

    laplacian = [[zero] * size for _ in range(size)]
    for slot, piece in enumerate(pieces):
        for row in range(len(piece.terminals)):
            for column in range(len(piece.terminals)):
                laplacian[lookup[(slot, row)]][lookup[(slot, column)]] += piece.matrix[row][column]
    for jumper in request.jumpers:
        if jumper.conductance == 0:
            continue
        start = lookup[positions[(jumper.start.slot, jumper.start.terminal)]]
        end = lookup[positions[(jumper.end.slot, jumper.end.terminal)]]
        laplacian[start][start] += jumper.conductance
        laplacian[end][end] += jumper.conductance
        laplacian[start][end] -= jumper.conductance
        laplacian[end][start] -= jumper.conductance

    components = _feasibility_components(pieces, request.jumpers)
    for group in components:
        if sum((net[lookup[node]] for node in group), zero) != 0:
            return CoupledResult(False, None, None)

    voltage = [zero] * size
    for group in components:
        ordered = sorted(group, key=lookup.__getitem__)
        reference = ordered[0]
        unknown = ordered[1:]
        if not unknown:
            continue
        matrix = [[laplacian[lookup[node]][lookup[other]] for other in unknown] for node in unknown]
        rhs = [net[lookup[node]] for node in unknown]
        solved = solve_linear_system(matrix, rhs)
        for node, value in zip(unknown, solved):
            voltage[lookup[node]] = value

    currents = []
    for jumper in request.jumpers:
        if jumper.conductance == 0:
            currents.append(zero)
            continue
        start = lookup[positions[(jumper.start.slot, jumper.start.terminal)]]
        end = lookup[positions[(jumper.end.slot, jumper.end.terminal)]]
        currents.append(jumper.conductance * (voltage[start] - voltage[end]))

    dissipation = []
    for slot, piece in enumerate(pieces):
        widths = len(piece.terminals)
        values = [voltage[lookup[(slot, index)]] for index in range(widths)]
        total = zero
        for row in range(widths):
            for column in range(widths):
                total += values[row] * piece.matrix[row][column] * values[column]
        dissipation.append(total)
    return CoupledResult(True, tuple(currents), tuple(dissipation))
