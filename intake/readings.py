"""Bind every input reading to the fixture and to its instrument origin."""

from dataclasses import dataclass

from fixture.topology import Topology, ordered_items, require_name, row_fields
from intake.units import Conductance, parse_conductance


@dataclass(frozen=True)
class Reading:
    bench_id: int
    branch: str
    source: str
    conductance: Conductance


def prepare_readings(
    bench_id: int, topology: Topology, source: str, rows: object,
) -> tuple[Reading, ...]:
    source = require_name(source, 'instrument source')
    candidates = {branch.name for branch in topology.branches}
    seen = set()
    readings = []
    for row in ordered_items(rows, 'readings'):
        branch, value, unit = row_fields(row, 3, 'reading')
        branch = require_name(branch, 'reading branch')
        if branch not in candidates:
            raise ValueError(f'unknown branch {branch!r} on fixture {bench_id}')
        if branch in seen:
            raise ValueError(f'duplicate reading for branch {branch!r}')
        readings.append(Reading(bench_id, branch, source, parse_conductance(value, unit)))
        seen.add(branch)
    return tuple(readings)
