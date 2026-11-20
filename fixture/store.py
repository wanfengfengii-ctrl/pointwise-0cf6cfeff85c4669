"""Store fixture identity and reproduce registration order by fixture ID."""

from dataclasses import dataclass
from sqlite3 import Connection

from fixture.terminals import Terminal
from fixture.topology import Branch, Topology
from lab import is_record_id


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS benches (
        id INTEGER PRIMARY KEY,
        experiment TEXT NOT NULL,
        name TEXT NOT NULL,
        UNIQUE (experiment, name)
    )''',
    '''CREATE TABLE IF NOT EXISTS bench_nodes (
        bench_id INTEGER NOT NULL REFERENCES benches(id),
        position INTEGER NOT NULL,
        name TEXT NOT NULL,
        PRIMARY KEY (bench_id, name),
        UNIQUE (bench_id, position)
    )''',
    '''CREATE TABLE IF NOT EXISTS bench_terminals (
        bench_id INTEGER NOT NULL REFERENCES benches(id),
        position INTEGER NOT NULL,
        name TEXT NOT NULL,
        node TEXT NOT NULL,
        PRIMARY KEY (bench_id, name),
        UNIQUE (bench_id, position),
        UNIQUE (bench_id, node),
        FOREIGN KEY (bench_id, node) REFERENCES bench_nodes(bench_id, name)
    )''',
    '''CREATE TABLE IF NOT EXISTS bench_branches (
        bench_id INTEGER NOT NULL REFERENCES benches(id),
        position INTEGER NOT NULL,
        name TEXT NOT NULL,
        start_node TEXT NOT NULL,
        end_node TEXT NOT NULL,
        PRIMARY KEY (bench_id, name),
        UNIQUE (bench_id, position),
        FOREIGN KEY (bench_id, start_node) REFERENCES bench_nodes(bench_id, name),
        FOREIGN KEY (bench_id, end_node) REFERENCES bench_nodes(bench_id, name),
        CHECK (start_node <> end_node)
    )''',
)


@dataclass(frozen=True)
class Bench:
    bench_id: int
    experiment: str
    name: str
    topology: Topology
    terminals: tuple[Terminal, ...]


class FixtureStore:
    def __init__(self, db: Connection):
        self.db = db

    def initialize(self) -> None:
        for statement in _SCHEMA:
            self.db.execute(statement)

    def save_bench(
        self, experiment: str, name: str, topology: Topology, terminals: tuple[Terminal, ...],
    ) -> int:
        existing = self.db.execute(
            'SELECT id FROM benches WHERE experiment = ? AND name = ?', (experiment, name),
        ).fetchone()
        if existing is not None:
            raise ValueError(f'fixture already registered for experiment {experiment!r}: {name!r}')
        bench_id = self.db.execute(
            'INSERT INTO benches(experiment, name) VALUES (?, ?)', (experiment, name),
        ).lastrowid
        self.db.executemany(
            'INSERT INTO bench_nodes(bench_id, position, name) VALUES (?, ?, ?)',
            ((bench_id, position, node) for position, node in enumerate(topology.nodes)),
        )
        self.db.executemany(
            'INSERT INTO bench_terminals(bench_id, position, name, node) VALUES (?, ?, ?, ?)',
            ((bench_id, position, term.name, term.node) for position, term in enumerate(terminals)),
        )
        self.db.executemany(
            '''INSERT INTO bench_branches(bench_id, position, name, start_node, end_node)
               VALUES (?, ?, ?, ?, ?)''',
            ((bench_id, position, branch.name, branch.start, branch.end)
             for position, branch in enumerate(topology.branches)),
        )
        return bench_id

    def load_bench(self, bench_id: int) -> Bench:
        if not is_record_id(bench_id):
            raise KeyError(bench_id)
        header = self.db.execute(
            'SELECT experiment, name FROM benches WHERE id = ?', (bench_id,),
        ).fetchone()
        if header is None:
            raise KeyError(bench_id)
        nodes = tuple(name for (name,) in self.db.execute(
            'SELECT name FROM bench_nodes WHERE bench_id = ? ORDER BY position', (bench_id,),
        ))
        branches = tuple(Branch(*row) for row in self.db.execute(
            '''SELECT name, start_node, end_node FROM bench_branches
               WHERE bench_id = ? ORDER BY position''', (bench_id,),
        ))
        terminals = tuple(Terminal(*row) for row in self.db.execute(
            'SELECT name, node FROM bench_terminals WHERE bench_id = ? ORDER BY position', (bench_id,),
        ))
        experiment, name = header
        return Bench(bench_id, experiment, name, Topology(nodes, branches), terminals)
