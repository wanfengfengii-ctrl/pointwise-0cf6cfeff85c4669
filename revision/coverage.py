"""Check that a revision accounts for each registered candidate branch."""

from collections.abc import Mapping

from fixture.topology import Topology


def require_complete_coverage(
    topology: Topology, reading_refs: Mapping[str, int],
) -> tuple[tuple[str, int], ...]:
    missing = [branch.name for branch in topology.branches if branch.name not in reading_refs]
    if missing:
        raise ValueError(f'missing readings for branches: {", ".join(missing)}')
    return tuple((branch.name, reading_refs[branch.name]) for branch in topology.branches)
