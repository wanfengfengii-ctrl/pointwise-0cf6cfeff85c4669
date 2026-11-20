"""Ordered nodes and named, directed candidate branches."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Branch:
    name: str
    start: str
    end: str


@dataclass(frozen=True)
class Topology:
    nodes: tuple[str, ...]
    branches: tuple[Branch, ...]


def require_name(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonempty name')
    return value


def ordered_items(value: object, field: str) -> Sequence:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f'{field} must be an ordered sequence')
    return value


def row_fields(value: object, size: int, field: str) -> Sequence:
    row = ordered_items(value, field)
    if len(row) != size:
        raise ValueError(f'{field} must contain {size} fields')
    return row


def build_topology(nodes: object, branches: object) -> Topology:
    ordered_nodes = tuple(require_name(node, 'node') for node in ordered_items(nodes, 'nodes'))
    node_set = set(ordered_nodes)
    if not ordered_nodes or len(node_set) != len(ordered_nodes):
        raise ValueError('nodes must be nonempty and distinct')

    ordered_branches = []
    seen = set()
    for row in ordered_items(branches, 'branches'):
        name, start, end = row_fields(row, 3, 'branch')
        name = require_name(name, 'branch name')
        start = require_name(start, 'branch start')
        end = require_name(end, 'branch end')
        if name in seen:
            raise ValueError(f'duplicate branch {name!r}')
        if start not in node_set or end not in node_set or start == end:
            raise ValueError(f'invalid endpoints for branch {name!r}')
        ordered_branches.append(Branch(name, start, end))
        seen.add(name)
    return Topology(ordered_nodes, tuple(ordered_branches))
