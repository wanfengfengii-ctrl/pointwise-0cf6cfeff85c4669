"""Register the fixture described by a work order."""

from sqlite3 import Connection

from fixture.store import FixtureStore
from fixture.terminals import bind_terminals
from fixture.topology import build_topology, require_name
from lab import write_transaction


def register(
    db: Connection, experiment: str, bench_name: str,
    nodes: object, terminals: object, branches: object,
) -> int:
    experiment = require_name(experiment, 'experiment')
    bench_name = require_name(bench_name, 'bench name')
    topology = build_topology(nodes, branches)
    public_terminals = bind_terminals(topology, terminals)
    with write_transaction(db):
        bench_id = FixtureStore(db).save_bench(experiment, bench_name, topology, public_terminals)
    return bench_id
