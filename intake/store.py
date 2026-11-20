"""Persist instrument submissions and raw readings, including amendments."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from sqlite3 import Connection

from intake.readings import Reading
from intake.units import Conductance, rational_text


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS intake_batches (
        id INTEGER PRIMARY KEY,
        submission_id TEXT NOT NULL UNIQUE,
        bench_id INTEGER NOT NULL REFERENCES benches(id),
        source TEXT NOT NULL
    )''',
    '''CREATE TABLE IF NOT EXISTS intake_readings (
        id INTEGER PRIMARY KEY,
        batch_id INTEGER REFERENCES intake_batches(id),
        bench_id INTEGER NOT NULL REFERENCES benches(id),
        branch TEXT NOT NULL,
        source TEXT NOT NULL,
        raw_value TEXT NOT NULL,
        unit TEXT NOT NULL,
        si TEXT NOT NULL,
        FOREIGN KEY (bench_id, branch) REFERENCES bench_branches(bench_id, name),
        UNIQUE (batch_id, branch)
    )''',
)


@dataclass(frozen=True)
class Submission:
    batch_id: int
    submission_id: str
    bench_id: int
    source: str
    revision_id: int
    reading_refs: tuple[tuple[str, int], ...]


class IntakeStore:
    def __init__(self, db: Connection):
        self.db = db

    def initialize(self) -> None:
        for statement in _SCHEMA:
            self.db.execute(statement)

    def load_submission(self, submission_id: str) -> Submission | None:
        row = self.db.execute(
            '''SELECT b.id, b.bench_id, b.source, r.id
               FROM intake_batches AS b
               JOIN measurement_revisions AS r ON r.batch_id = b.id AND r.parent_id IS NULL
               WHERE b.submission_id = ?''', (submission_id,),
        ).fetchone()
        if row is None:
            return None
        batch_id, bench_id, source, revision_id = row
        refs = tuple(self.db.execute(
            'SELECT branch, id FROM intake_readings WHERE batch_id = ? ORDER BY id', (batch_id,),
        ))
        return Submission(batch_id, submission_id, bench_id, source, revision_id, refs)

    def save_submission(self, submission_id: str, bench_id: int, source: str) -> int:
        return self.db.execute(
            'INSERT INTO intake_batches(submission_id, bench_id, source) VALUES (?, ?, ?)',
            (submission_id, bench_id, source),
        ).lastrowid

    def record_readings(
        self, readings: Iterable[Reading], batch_id: int | None = None,
    ) -> tuple[tuple[str, int], ...]:
        refs = []
        for reading in readings:
            value = reading.conductance
            ref = self.db.execute(
                '''INSERT INTO intake_readings(batch_id, bench_id, branch, source, raw_value, unit, si)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (batch_id, reading.bench_id, reading.branch, reading.source,
                 json.dumps(value.raw_value), value.unit, rational_text(value.si)),
            ).lastrowid
            refs.append((reading.branch, ref))
        return tuple(refs)

    def load_readings(self, refs: Iterable[int]) -> dict[int, Reading]:
        readings = {}
        for ref in refs:
            row = self.db.execute(
                '''SELECT bench_id, branch, source, raw_value, unit, si
                   FROM intake_readings WHERE id = ?''', (ref,),
            ).fetchone()
            if row is None:
                raise KeyError(ref)
            bench_id, branch, source, raw_value, unit, si = row
            readings[ref] = Reading(bench_id, branch, source,
                                    Conductance(json.loads(raw_value), unit, Fraction(si)))
        return readings
