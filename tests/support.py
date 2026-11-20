import json
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from fixture.catalog import register
from intake.imports import ingest
from lab import connect, initialize
from revision.freeze import freeze


MEASUREMENT_TABLES = ('intake_batches', 'intake_readings', 'measurement_revisions', 'revision_choices', 'revision_heads')
REPORT_TABLES = ('local_reports', 'report_receipts')


def counts(db, tables):
    return tuple(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in tables)


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'shift.sqlite3'
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        initialize(self.db)

    def observed_counts(self, tables):
        with closing(connect(self.path)) as observer:
            return counts(observer, tables)

    def reopen(self):
        self.db.close()
        self.db = connect(self.path)
        self.addCleanup(self.db.close)

    def single_branch(self, value=1, source='meter-M1'):
        bench = register(self.db, 'T1', 'bench', ['a', 'b'], ['a', 'b'], [('lead', 'a', 'b')])
        batch = ingest(self.db, bench, 'batch-1', source, [('lead', value, 'S')])
        return bench, batch, freeze(self.db, batch.revision_id)


@contextmanager
def fail_initial_revision(db):
    db.execute('''CREATE TRIGGER test_reject_initial BEFORE INSERT ON measurement_revisions
                  WHEN NEW.parent_id IS NULL AND EXISTS (
                      SELECT 1 FROM intake_readings WHERE batch_id = NEW.batch_id
                  )
                  BEGIN SELECT RAISE(ABORT, 'initial revision write blocked'); END''')
    try:
        yield
    finally:
        db.execute('DROP TRIGGER test_reject_initial')


@contextmanager
def fail_report_commit(db):
    db.execute('CREATE TABLE test_commit_parent (id INTEGER PRIMARY KEY)')
    db.execute('''CREATE TABLE test_commit_child (
        missing_id INTEGER REFERENCES test_commit_parent(id) DEFERRABLE INITIALLY DEFERRED
    )''')
    db.execute('''CREATE TRIGGER test_reject_receipt_commit AFTER INSERT ON report_receipts
                  BEGIN INSERT INTO test_commit_child(missing_id) VALUES (1); END''')
    try:
        yield
    finally:
        db.execute('DROP TRIGGER test_reject_receipt_commit')
        db.execute('DROP TABLE test_commit_child')
        db.execute('DROP TABLE test_commit_parent')


def scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id,
        'input': inputs,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': paths,
        'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))
