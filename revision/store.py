"""Immutable measurement revisions and the frozen evidence used at issue time."""

import json
from dataclasses import dataclass
from fractions import Fraction
from sqlite3 import Connection

from intake.units import rational_text
from lab import is_record_id


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS measurement_revisions (
        id INTEGER PRIMARY KEY,
        bench_id INTEGER NOT NULL REFERENCES benches(id),
        batch_id INTEGER NOT NULL REFERENCES intake_batches(id),
        parent_id INTEGER UNIQUE REFERENCES measurement_revisions(id)
    )''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS initial_revision_per_batch
       ON measurement_revisions(batch_id) WHERE parent_id IS NULL''',
    '''CREATE TABLE IF NOT EXISTS revision_heads (
        batch_id INTEGER PRIMARY KEY REFERENCES intake_batches(id),
        revision_id INTEGER NOT NULL UNIQUE REFERENCES measurement_revisions(id)
    )''',
    '''CREATE TABLE IF NOT EXISTS revision_choices (
        revision_id INTEGER NOT NULL REFERENCES measurement_revisions(id),
        branch TEXT NOT NULL,
        reading_ref INTEGER NOT NULL REFERENCES intake_readings(id),
        PRIMARY KEY (revision_id, branch)
    )''',
    '''CREATE TABLE IF NOT EXISTS frozen_revisions (
        id INTEGER PRIMARY KEY,
        revision_id INTEGER NOT NULL UNIQUE REFERENCES measurement_revisions(id)
    )''',
    '''CREATE TABLE IF NOT EXISTS frozen_branch_readings (
        freeze_id INTEGER NOT NULL REFERENCES frozen_revisions(id),
        position INTEGER NOT NULL,
        branch TEXT NOT NULL,
        reading_ref INTEGER NOT NULL REFERENCES intake_readings(id),
        source TEXT NOT NULL,
        raw_value TEXT NOT NULL,
        unit TEXT NOT NULL,
        si TEXT NOT NULL,
        PRIMARY KEY (freeze_id, position),
        UNIQUE (freeze_id, branch)
    )''',
)


@dataclass(frozen=True)
class MeasurementRevision:
    revision_id: int
    bench_id: int
    batch_id: int
    parent_id: int | None
    reading_refs: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class FrozenBranchReading:
    branch: str
    reading_ref: int
    source: str
    raw_value: int | str
    unit: str
    si: Fraction


@dataclass(frozen=True)
class FrozenRevision:
    freeze_id: int
    revision_id: int
    bench_id: int
    readings: tuple[FrozenBranchReading, ...]


class RevisionStore:
    def __init__(self, db: Connection):
        self.db = db

    def initialize(self) -> None:
        for statement in _SCHEMA:
            self.db.execute(statement)

    def _insert_revision(
        self, bench_id: int, batch_id: int, parent_id: int | None,
        reading_refs: tuple[tuple[str, int], ...],
    ) -> int:
        revision_id = self.db.execute(
            'INSERT INTO measurement_revisions(bench_id, batch_id, parent_id) VALUES (?, ?, ?)',
            (bench_id, batch_id, parent_id),
        ).lastrowid
        self.db.executemany(
            'INSERT INTO revision_choices(revision_id, branch, reading_ref) VALUES (?, ?, ?)',
            ((revision_id, branch, ref) for branch, ref in reading_refs),
        )
        return revision_id

    def create_initial(self, bench_id: int, batch_id: int, refs: tuple[tuple[str, int], ...]) -> int:
        revision = self._insert_revision(bench_id, batch_id, None, refs)
        self.db.execute(
            'INSERT INTO revision_heads(batch_id, revision_id) VALUES (?, ?)', (batch_id, revision),
        )
        return revision

    def load_revision(self, revision_id: int) -> MeasurementRevision:
        if not is_record_id(revision_id):
            raise KeyError(revision_id)
        row = self.db.execute(
            'SELECT bench_id, batch_id, parent_id FROM measurement_revisions WHERE id = ?',
            (revision_id,),
        ).fetchone()
        if row is None:
            raise KeyError(revision_id)
        bench_id, batch_id, parent_id = row
        refs = tuple(self.db.execute(
            'SELECT branch, reading_ref FROM revision_choices WHERE revision_id = ? ORDER BY branch',
            (revision_id,),
        ))
        return MeasurementRevision(revision_id, bench_id, batch_id, parent_id, refs)

    def append_amendment(
        self, parent: MeasurementRevision, replacements: tuple[tuple[str, int], ...],
    ) -> int:
        head = self.db.execute(
            'SELECT revision_id FROM revision_heads WHERE batch_id = ?', (parent.batch_id,),
        ).fetchone()
        if head != (parent.revision_id,):
            raise ValueError(f'stale parent revision {parent.revision_id}')
        refs = dict(parent.reading_refs)
        refs.update(replacements)
        child = self._insert_revision(parent.bench_id, parent.batch_id, parent.revision_id,
                                      tuple(refs.items()))
        self.db.execute(
            'UPDATE revision_heads SET revision_id = ? WHERE batch_id = ?', (child, parent.batch_id),
        )
        return child

    def find_freeze(self, revision_id: int) -> int | None:
        row = self.db.execute(
            'SELECT id FROM frozen_revisions WHERE revision_id = ?', (revision_id,),
        ).fetchone()
        return None if row is None else row[0]

    def save_freeze(self, revision_id: int, readings: tuple[FrozenBranchReading, ...]) -> int:
        freeze_id = self.db.execute(
            'INSERT INTO frozen_revisions(revision_id) VALUES (?)', (revision_id,),
        ).lastrowid
        self.db.executemany(
            '''INSERT INTO frozen_branch_readings(
                   freeze_id, position, branch, reading_ref, source, raw_value, unit, si
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            ((freeze_id, position, reading.branch, reading.reading_ref, reading.source,
              json.dumps(reading.raw_value), reading.unit, rational_text(reading.si))
             for position, reading in enumerate(readings)),
        )
        return freeze_id

    def load_frozen(self, freeze_id: int) -> FrozenRevision:
        if not is_record_id(freeze_id):
            raise KeyError(freeze_id)
        row = self.db.execute(
            '''SELECT f.revision_id, r.bench_id FROM frozen_revisions AS f
               JOIN measurement_revisions AS r ON r.id = f.revision_id WHERE f.id = ?''', (freeze_id,),
        ).fetchone()
        if row is None:
            raise KeyError(freeze_id)
        revision_id, bench_id = row
        records = self.db.execute(
            '''SELECT branch, reading_ref, source, raw_value, unit, si
               FROM frozen_branch_readings WHERE freeze_id = ? ORDER BY position''', (freeze_id,),
        )
        readings = tuple(
            FrozenBranchReading(branch, ref, source, json.loads(raw), unit, Fraction(si))
            for branch, ref, source, raw, unit, si in records
        )
        return FrozenRevision(freeze_id, revision_id, bench_id, readings)
