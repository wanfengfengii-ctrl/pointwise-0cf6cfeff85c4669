"""Partition the measured topology using only conducting branches."""

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from analysis.clamps import ClampSet
from fixture.topology import Branch, Topology


@dataclass(frozen=True)
class ConductingIsland:
    nodes: tuple[str, ...]
    branches: tuple[Branch, ...]


def find_islands(topology: Topology, conductance: Mapping[str, Fraction]) -> tuple[ConductingIsland, ...]:
    neighbors = {node: [] for node in topology.nodes}
    conducting = []
    for branch in topology.branches:
        if conductance[branch.name] > 0:
            neighbors[branch.start].append(branch.end)
            neighbors[branch.end].append(branch.start)
            conducting.append(branch)

    membership = {}
    node_groups = []
    for root in topology.nodes:
        if root in membership:
            continue
        island = len(node_groups)
        node_groups.append([])
        membership[root] = island
        pending = [root]
        while pending:
            node = pending.pop()
            for neighbor in neighbors[node]:
                if neighbor not in membership:
                    membership[neighbor] = island
                    pending.append(neighbor)

    branch_groups = [[] for _ in node_groups]
    for node in topology.nodes:
        node_groups[membership[node]].append(node)
    for branch in conducting:
        branch_groups[membership[branch.start]].append(branch)
    return tuple(ConductingIsland(tuple(nodes), tuple(branches))
                 for nodes, branches in zip(node_groups, branch_groups))


def require_clamped_islands(islands: tuple[ConductingIsland, ...], clamps: ClampSet) -> None:
    fixed = clamps.by_node()
    for island in islands:
        if not any(node in fixed for node in island.nodes):
            raise ValueError(f'conducting island containing {island.nodes[0]!r} has no clamp')
