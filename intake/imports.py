"""Accept an instrument submission and establish its first revision together."""

from sqlite3 import Connection

from fixture.store import FixtureStore
from fixture.topology import require_name
from intake.identity import submission_key
from intake.readings import prepare_readings
from intake.store import IntakeStore, Submission
from lab import write_transaction
from revision.store import RevisionStore


def ingest(db: Connection, bench_id: int, submission_id: str, source: str, rows: object) -> Submission:
    submission_id = require_name(submission_id, 'submission ID')
    intake = IntakeStore(db)
    with write_transaction(db):
        try:
            bench = FixtureStore(db).load_bench(bench_id)
        except KeyError:
            raise ValueError(f'unknown fixture {bench_id!r}') from None
        readings = prepare_readings(bench_id, bench.topology, source, rows)
        original = intake.load_submission(submission_id)
        if original is not None:
            previous = intake.load_readings(ref for _, ref in original.reading_refs)
            if submission_key(bench_id, source, readings) != submission_key(
                original.bench_id, original.source, previous.values(),
            ):
                raise ValueError(f'conflicting retransmission of {submission_id!r}')
            return original

        batch_id = intake.save_submission(submission_id, bench_id, source)
        refs = intake.record_readings(readings, batch_id)
        revision_id = RevisionStore(db).create_initial(bench_id, batch_id, refs)
    return Submission(batch_id, submission_id, bench_id, source, revision_id, refs)
