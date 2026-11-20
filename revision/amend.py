"""Append a correction while preserving the selected parent's evidence."""

from sqlite3 import Connection

from fixture.store import FixtureStore
from intake.readings import prepare_readings
from intake.store import IntakeStore
from lab import write_transaction
from revision.store import RevisionStore


def amend(db: Connection, bench_id: int, parent_id: int, source: str, rows: object) -> int:
    revisions = RevisionStore(db)
    with write_transaction(db):
        try:
            bench = FixtureStore(db).load_bench(bench_id)
            parent = revisions.load_revision(parent_id)
        except KeyError as error:
            raise ValueError(f'unknown fixture or parent revision: {error}') from error
        if parent.bench_id != bench_id:
            raise ValueError('parent revision belongs to another fixture')
        readings = prepare_readings(bench_id, bench.topology, source, rows)
        if not readings:
            raise ValueError('an amendment requires at least one branch reading')
        replacements = IntakeStore(db).record_readings(readings)
        child = revisions.append_amendment(parent, replacements)
    return child
