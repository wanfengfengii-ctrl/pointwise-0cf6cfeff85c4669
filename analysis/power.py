"""Calculate branch loss and independently account for net source power."""

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from analysis.clamps import ClampSet
from analysis.currents import LocalCurrents
from analysis.potentials import LocalPotentials
from fixture.topology import Topology


@dataclass(frozen=True)
class PowerBalance:
    branches: dict[str, Fraction]
    total: Fraction
    supplied: Fraction


def calculate_power(
    topology: Topology, conductance: Mapping[str, Fraction], clamps: ClampSet,
    potentials: LocalPotentials, currents: LocalCurrents,
) -> PowerBalance:
    losses = {}
    for branch in topology.branches:
        delta = potentials.voltages[branch.start] - potentials.voltages[branch.end]
        losses[branch.name] = conductance[branch.name] * delta**2
    total = sum(losses.values(), Fraction(0))
    supplied = sum((clamp.voltage * currents.node_net[clamp.node] for clamp in clamps.clamps), Fraction(0))
    return PowerBalance(losses, total, supplied)
