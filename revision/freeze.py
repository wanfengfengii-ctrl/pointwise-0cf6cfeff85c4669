"""Materialize the exact, coverage-checked reading set for a fixture revision."""

from sqlite3 import Connection

from fixture.store import FixtureStore
from intake.store import IntakeStore
from lab import write_transaction
from revision.coverage import require_complete_coverage
from revision.store import FrozenBranchReading, RevisionStore


def freeze(db: Connection, revision_id: int) -> int:
    revisions = RevisionStore(db)
    with write_transaction(db):
        revision = revisions.load_revision(revision_id)
        original = revisions.find_freeze(revision_id)
        if original is not None:
            return original
        bench = FixtureStore(db).load_bench(revision.bench_id)
        coverage = require_complete_coverage(bench.topology, dict(revision.reading_refs))
        sources = IntakeStore(db).load_readings(ref for _, ref in coverage)
        frozen = []
        for branch, ref in coverage:
            reading = sources[ref]
            value = reading.conductance
            frozen.append(FrozenBranchReading(branch, ref, reading.source, value.raw_value, value.unit, value.si))
        freeze_id = revisions.save_freeze(revision_id, tuple(frozen))
    return freeze_id
