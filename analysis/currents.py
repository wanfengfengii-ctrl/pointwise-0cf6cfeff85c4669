"""Account for signed branch current and net fixture input at each clamp."""

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from analysis.clamps import ClampSet
from analysis.potentials import LocalPotentials
from fixture.topology import Topology


@dataclass(frozen=True)
class LocalCurrents:
    branches: dict[str, Fraction]
    node_net: dict[str, Fraction]
    supplies: tuple[tuple[str, Fraction], ...]


def calculate_currents(
    topology: Topology, conductance: Mapping[str, Fraction],
    clamps: ClampSet, potentials: LocalPotentials,
) -> LocalCurrents:
    branch_currents = {}
    node_net = dict.fromkeys(topology.nodes, Fraction(0))
    voltage = potentials.voltages
    for branch in topology.branches:
        current = conductance[branch.name] * (voltage[branch.start] - voltage[branch.end])
        branch_currents[branch.name] = current
        node_net[branch.start] += current
        node_net[branch.end] -= current
    supplies = tuple((clamp.terminal, node_net[clamp.node]) for clamp in clamps.clamps)
    return LocalCurrents(branch_currents, node_net, supplies)
