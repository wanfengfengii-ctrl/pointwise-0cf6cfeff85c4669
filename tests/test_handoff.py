import json
import sqlite3
from fractions import Fraction
from hashlib import sha256

from fixture.catalog import register
from intake.imports import ingest
from intake.store import IntakeStore
from lab import initialize
from report.export import export
from report.issue import issue
from report.read import read
from revision.amend import amend
from revision.freeze import freeze
from revision.store import RevisionStore
from tests.support import DatabaseCase, MEASUREMENT_TABLES, REPORT_TABLES, fail_report_commit, scenario


CLAMPS = [('a', 1), ('b', 0)]


class HandoffTests(DatabaseCase):
    def corrected(self):
        bench, batch, old_freeze = self.single_branch()
        child = amend(self.db, bench, batch.revision_id, 'meter-M2', [('lead', '2/1', 'S')])
        return bench, batch, old_freeze, child, freeze(self.db, child)

    def test_amend_and_reopen(self):
        bench, batch, old_freeze = self.single_branch()
        old = issue(self.db, old_freeze, CLAMPS)
        original_bytes = export(self.db, old.report_id)
        child = amend(self.db, bench, batch.revision_id, 'meter-M2', [('lead', 2, 'S')])
        new_freeze = freeze(self.db, child)
        new = issue(self.db, new_freeze, CLAMPS)
        self.reopen()
        old_saved = read(self.db, old.report_id)
        new_saved = read(self.db, new.report_id)
        self.assertEqual((old_saved, new_saved), (old, new))
        self.assertEqual((old_saved.body['revision_id'], new_saved.body['revision_id']), (batch.revision_id, child))
        self.assertEqual((old_saved.body['freeze_id'], new_saved.body['freeze_id']), (old_freeze, new_freeze))
        self.assertEqual((old_saved.body['total_dissipation'], new_saved.body['total_dissipation']), (Fraction(1), Fraction(2)))
        sources = [record.body['branches'][0]['source'] for record in (old_saved, new_saved)]
        self.assertEqual(sources, ['meter-M1', 'meter-M2'])
        self.assertNotEqual(old_saved.body['branches'][0]['reading_ref'], new_saved.body['branches'][0]['reading_ref'])
        reopened_bytes = export(self.db, old.report_id)
        self.assertEqual(reopened_bytes, original_bytes)
        self.assertEqual(json.loads(reopened_bytes)['total_dissipation'], '1/1')
        self.assertEqual(old_saved.receipt['body_sha256'], sha256(reopened_bytes).hexdigest())
        scenario('v7', {'conductance_S': [1, 2], 'clamps_V': CLAMPS},
                 {'issued_W': ['1', '2']},
                 {'issued_W': [str(record.body['total_dissipation']) for record in (old, new)]},
                 {'read_W': ['1', '2'], 'origins': ['meter-M1', 'meter-M2'], 'stable_bytes': True},
                 {'read_W': [str(record.body['total_dissipation']) for record in (old_saved, new_saved)],
                  'origins': sources, 'stable_bytes': reopened_bytes == original_bytes},
                 ['revision/amend.py', 'revision/freeze.py', 'report/issue.py', 'report/read.py', 'report/export.py'],
                 'At a 1 V drop the single-branch dissipation in W equals the measured conductance in S')

    def test_amend_history(self):
        bench = register(self.db, 'T1', 'bench', ['a', 'x', 'b'], ['a', 'b'],
                         [('ax', 'a', 'x'), ('xb', 'x', 'b')])
        other = register(self.db, 'T2', 'bench', ['a', 'b'], ['a', 'b'], [('ax', 'a', 'b')])
        rows = [('ax', 2, 'S'), ('xb', 2, 'S')]
        batch = ingest(self.db, bench, 'S1', 'M1', rows)
        other_batch = ingest(self.db, bench, 'S2', 'M3', rows)
        old_freeze = freeze(self.db, batch.revision_id)
        child = amend(self.db, bench, batch.revision_id, 'M2', [('ax', 6, 'S')])
        revised_freeze = freeze(self.db, child)
        store = RevisionStore(self.db)
        self.assertEqual(store.load_revision(child).parent_id, batch.revision_id)
        original, revised = [store.load_frozen(number).readings for number in (old_freeze, revised_freeze)]
        self.assertEqual(original[1], revised[1])
        self.assertEqual(original[1].reading_ref, dict(batch.reading_refs)['xb'])
        self.assertEqual((original[0].source, original[0].si, revised[0].source, revised[0].si), ('M1', 2, 'M2', 6))
        self.assertNotEqual(original[0].reading_ref, revised[0].reading_ref)
        before = self.observed_counts(MEASUREMENT_TABLES)
        for fixture, parent, changes in ((other, child, [('ax', 5, 'S')]),
                                         (bench, batch.revision_id, [('ax', 5, 'S')]),
                                         (bench, child, [('ax', 5, 'S'), ('xb', -1, 'S')]),
                                         (bench, child + 100, [('ax', 5, 'S')])):
            with self.subTest(fixture=fixture, parent=parent, changes=changes):
                with self.assertRaises(ValueError):
                    amend(self.db, fixture, parent, 'M4', changes)
                self.assertEqual(self.observed_counts(MEASUREMENT_TABLES), before)
        next_child = amend(self.db, bench, child, 'M4', [('ax', 4, 'S')])
        independent = amend(self.db, bench, other_batch.revision_id, 'M5', [('xb', 3, 'S')])
        self.assertEqual(store.load_revision(next_child).parent_id, child)
        self.assertEqual(store.load_revision(independent).parent_id, other_batch.revision_id)

    def test_reissue_old(self):
        _, batch, old_freeze, _, new_freeze = self.corrected()
        new = issue(self.db, new_freeze, CLAMPS)
        again = issue(self.db, old_freeze, CLAMPS)
        self.assertEqual(again.body['revision_id'], batch.revision_id)
        self.assertEqual(again.body['freeze_id'], old_freeze)
        self.assertEqual(again.body['branches'][0]['source'], 'meter-M1')
        self.assertEqual(again.body['branches'][0]['reading_ref'], dict(batch.reading_refs)['lead'])
        self.assertEqual(again.body['total_dissipation'], Fraction(1))
        self.assertEqual(new.body['total_dissipation'], Fraction(2))

    def test_reinitialize(self):
        bench, batch, old_freeze, child, new_freeze = self.corrected()
        old = issue(self.db, old_freeze, CLAMPS)
        new = issue(self.db, new_freeze, CLAMPS)
        original = export(self.db, old.report_id)
        updated = export(self.db, new.report_id)
        initialize(self.db)
        initialize(self.db)
        self.reopen()
        self.assertEqual(read(self.db, old.report_id), old)
        self.assertEqual(read(self.db, new.report_id), new)
        self.assertEqual((export(self.db, old.report_id), export(self.db, new.report_id)), (original, updated))
        replay = ingest(self.db, bench, 'batch-1', 'meter-M1', [('lead', 1000, 'mS')])
        self.assertEqual(replay, batch)
        source = IntakeStore(self.db).load_readings([dict(replay.reading_refs)['lead']])
        self.assertEqual(next(iter(source.values())).conductance.raw_value, 1)
        latest = amend(self.db, bench, child, 'meter-M3', [('lead', 3, 'S')])
        self.assertEqual(issue(self.db, freeze(self.db, latest), CLAMPS).body['total_dissipation'], Fraction(3))
        for operation in (read, export):
            with self.assertRaises(KeyError):
                operation(self.db, 100)

    def test_failed_issue_retry(self):
        _, _, frozen = self.single_branch()
        with fail_report_commit(self.db):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                issue(self.db, frozen, CLAMPS)
            self.assertFalse(self.db.in_transaction)
            rejected_counts = self.observed_counts(REPORT_TABLES)
            self.assertEqual(rejected_counts, (0, 0))
            with self.assertRaises(KeyError):
                read(self.db, 1)
        retried = issue(self.db, frozen, CLAMPS)
        committed_counts = self.observed_counts(REPORT_TABLES)
        self.assertEqual(committed_counts, (1, 1))
        self.reopen()
        saved = read(self.db, retried.report_id)
        self.assertEqual(saved, retried)
        self.assertEqual(saved.body['total_dissipation'], Fraction(1))
        self.assertEqual(saved.receipt['freeze_id'], frozen)
        scenario('v8', {'conductance_S': 1, 'clamps_V': CLAMPS, 'failure': 'deferred foreign key'},
                 {'after_failure': [0, 0]}, {'after_failure': list(rejected_counts)},
                 {'after_retry': [1, 1], 'saved_W': '1', 'receipt_freeze_matches': True},
                 {'after_retry': list(committed_counts), 'saved_W': str(saved.body['total_dissipation']),
                  'receipt_freeze_matches': saved.receipt['freeze_id'] == frozen},
                 ['report/issue.py', 'report/store.py', 'lab.py', 'report/read.py'],
                 'Independent SQLite connections count both records; a 1 S lead at 1 V dissipates 1 W')

    def test_retry_old_freeze(self):
        _, batch, old_freeze, _, new_freeze = self.corrected()
        existing = issue(self.db, new_freeze, CLAMPS)
        existing_bytes = export(self.db, existing.report_id)
        with fail_report_commit(self.db):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                issue(self.db, old_freeze, CLAMPS)
            self.assertEqual(self.observed_counts(REPORT_TABLES), (1, 1))
            self.assertEqual(read(self.db, existing.report_id), existing)
        retried = issue(self.db, old_freeze, CLAMPS)
        self.reopen()
        self.assertEqual(read(self.db, retried.report_id), retried)
        self.assertEqual(self.observed_counts(REPORT_TABLES), (2, 2))
        self.assertEqual(retried.body['freeze_id'], old_freeze)
        self.assertEqual(retried.body['revision_id'], batch.revision_id)
        self.assertEqual(retried.body['total_dissipation'], Fraction(1))
        branch = retried.body['branches'][0]
        self.assertEqual((branch['source'], branch['reading_ref']), ('meter-M1', dict(batch.reading_refs)['lead']))
        self.assertEqual(export(self.db, existing.report_id), existing_bytes)
