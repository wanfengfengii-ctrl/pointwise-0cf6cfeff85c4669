"""Bind the local work order to an ordered set of public clamp positions."""

from dataclasses import dataclass
from fractions import Fraction

from fixture.terminals import Terminal, resolve_terminal
from fixture.topology import ordered_items, row_fields
from intake.units import parse_rational


@dataclass(frozen=True)
class Clamp:
    terminal: str
    node: str
    voltage: Fraction


@dataclass(frozen=True)
class ClampSet:
    clamps: tuple[Clamp, ...]

    def by_node(self) -> dict[str, Fraction]:
        return {clamp.node: clamp.voltage for clamp in self.clamps}


def bind_clamps(terminals: tuple[Terminal, ...], rows: object) -> ClampSet:
    available = {terminal.name: terminal for terminal in terminals}
    clamps = []
    seen = set()
    for row in ordered_items(rows, 'clamps'):
        name, voltage = row_fields(row, 2, 'clamp')
        terminal = resolve_terminal(available, name)
        if terminal.name in seen:
            raise ValueError(f'duplicate clamp {terminal.name!r}')
        clamps.append(Clamp(terminal.name, terminal.node, parse_rational(voltage, 'clamp voltage')))
        seen.add(terminal.name)
    return ClampSet(tuple(clamps))
