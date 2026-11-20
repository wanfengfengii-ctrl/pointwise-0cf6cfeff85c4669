"""Published clamp positions for a specific fixture registration."""

from collections.abc import Mapping
from dataclasses import dataclass

from fixture.topology import Topology, ordered_items, require_name


@dataclass(frozen=True)
class Terminal:
    name: str
    node: str


def bind_terminals(topology: Topology, names: object) -> tuple[Terminal, ...]:
    nodes = set(topology.nodes)
    terminals = []
    seen = set()
    for value in ordered_items(names, 'terminals'):
        name = require_name(value, 'terminal')
        if name not in nodes or name in seen:
            raise ValueError(f'unknown or duplicate terminal {name!r}')
        terminals.append(Terminal(name, name))
        seen.add(name)
    return tuple(terminals)


def resolve_terminal(terminals: Mapping[str, Terminal], value: object) -> Terminal:
    name = require_name(value, 'clamp terminal')
    try:
        return terminals[name]
    except KeyError:
        raise ValueError(f'unknown public terminal {name!r}') from None
