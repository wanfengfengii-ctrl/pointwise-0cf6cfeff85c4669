import sqlite3
from fractions import Fraction

from fixture.catalog import register
from fixture.store import FixtureStore
from intake.imports import ingest
from intake.store import IntakeStore
from revision.amend import amend
from revision.freeze import freeze
from revision.store import RevisionStore
from tests.support import DatabaseCase, MEASUREMENT_TABLES, fail_initial_revision, scenario


class MeasureTests(DatabaseCase):
    def bench(self):
        return register(self.db, 'T1', 'bench', ['a', 'x', 'b'], ['a', 'b'],
                        [('left', 'a', 'x'), ('right', 'x', 'b')])

    def test_units_and_retry(self):
        bench = self.bench()
        first_rows = [('left', 500, 'mS'), ('right', 2, 'S')]
        replay_rows = [('right', 2000, 'mS'), ('left', '1/2', 'S')]
        first = ingest(self.db, bench, 'S1', 'M1', first_rows)
        replay = ingest(self.db, bench, 'S1', 'M1', replay_rows)
        self.assertEqual(replay, first)
        first_ref = dict(first.reading_refs)['left']
        value = IntakeStore(self.db).load_readings([first_ref])[first_ref].conductance
        self.assertEqual(value.si, Fraction(1, 2))
        frozen = RevisionStore(self.db).load_frozen(freeze(self.db, replay.revision_id))
        left = frozen.readings[0]
        self.assertEqual((left.si, left.raw_value, left.unit, left.reading_ref), (Fraction(1, 2), 500, 'mS', first_ref))
        scenario('v1', {'original': first_rows, 'replay': replay_rows},
                 {'left_S': '1/2', 'same_acceptance': True},
                 {'left_S': str(value.si), 'same_acceptance': replay == first},
                 {'frozen_raw': [500, 'mS'], 'same_reference': True},
                 {'frozen_raw': [left.raw_value, left.unit], 'same_reference': left.reading_ref == first_ref},
                 ['intake/units.py', 'intake/imports.py', 'revision/freeze.py'],
                 '500 mS divide by 1000, then compare original identities and source fields')

    def test_bench_scope(self):
        a = register(self.db, 'T-A', 'same bench', ['a', 'b'], ['a', 'b'], [('A-only', 'a', 'b')])
        b = register(self.db, 'T-B', 'same bench', ['a', 'b'], ['a', 'b'], [('B-only', 'a', 'b')])
        self.assertNotEqual(a, b)
        for bench, own, foreign in ((b, 'B-only', 'A-only'), (a, 'A-only', 'B-only')):
            with self.subTest(bench=bench):
                accepted = ingest(self.db, bench, own, 'M1', [(own, 1, 'S')])
                frozen = RevisionStore(self.db).load_frozen(freeze(self.db, accepted.revision_id))
                self.assertEqual((frozen.bench_id, frozen.readings[0].branch), (bench, own))
                before = self.observed_counts(MEASUREMENT_TABLES)
                with self.assertRaises(ValueError):
                    ingest(self.db, bench, own + '-cross', 'M1', [(foreign, 1, 'S')])
                self.assertEqual(self.observed_counts(MEASUREMENT_TABLES), before)

    def test_register_invalid(self):
        bench = self.bench()
        tables = ('benches', 'bench_nodes', 'bench_terminals', 'bench_branches')
        before = self.observed_counts(tables)
        invalid = (
            ('bench', ['a', 'b'], ['a'], [('lead', 'a', 'b')]),
            ('other', ['a', 'b'], ['a'], [('lead', 'a', 'other-node')]),
            ('other', ['a', 'b'], ['a'], [('lead', 'a', 'a')]),
            ('other', ['a', 'b'], ['other-node'], []),
            ('other', ['a', 'a'], [], []),
            ('other', ['a', 'b'], ['a', 'a'], []),
            ('other', ['a', 'b'], ['a'], [('lead', 'a', 'b'), ('lead', 'b', 'a')]),
        )
        for name, nodes, terminals, branches in invalid:
            with self.subTest(registration=(name, nodes, terminals, branches)):
                with self.assertRaises(ValueError):
                    register(self.db, 'T1', name, nodes, terminals, branches)
                self.assertEqual(self.observed_counts(tables), before)
        self.assertEqual(FixtureStore(self.db).load_bench(bench).topology.nodes, ('a', 'x', 'b'))

    def test_raw_provenance(self):
        bench = self.bench()
        batch = ingest(self.db, bench, 'S1', '台式 M1', [('left', '0500', 'mS')])
        ref = dict(batch.reading_refs)['left']
        self.reopen()
        reading = IntakeStore(self.db).load_readings([ref])[ref]
        self.assertEqual((reading.bench_id, reading.branch, reading.source), (bench, 'left', '台式 M1'))
        value = reading.conductance
        self.assertEqual((value.raw_value, value.unit, value.si), ('0500', 'mS', Fraction(1, 2)))

    def test_retry_conflict(self):
        bench = self.bench()
        other = register(self.db, 'T2', 'bench', ['a', 'x'], ['a'], [('left', 'a', 'x')])
        rows = [('left', 500, 'mS')]
        original = ingest(self.db, bench, 'S1', 'M1', rows)
        before = self.observed_counts(MEASUREMENT_TABLES)
        for target, source, measurements in ((bench, 'M1', [('left', '3/4', 'S')]),
                                              (bench, 'M2', rows), (other, 'M1', rows)):
            with self.subTest(target=target, source=source, rows=measurements):
                with self.assertRaises(ValueError):
                    ingest(self.db, target, 'S1', source, measurements)
                self.assertEqual(self.observed_counts(MEASUREMENT_TABLES), before)
        self.assertEqual(IntakeStore(self.db).load_submission('S1'), original)

    def test_reject_whole_batch(self):
        bench = self.bench()
        with self.assertRaises(ValueError):
            ingest(self.db, bench, 'S1', 'M1', [('left', 2, 'S'), ('right', -1, 'S')])
        self.assertEqual(self.observed_counts(MEASUREMENT_TABLES), (0, 0, 0, 0, 0))
        self.assertIsNone(IntakeStore(self.db).load_submission('S1'))

    def test_invalid_readings(self):
        bench = self.bench()
        invalid = (('right', 1, 'A'), ('right', 'nan', 'S'), ('right', '1/0', 'S'),
                   ('right', -1, 'S'), ('unknown', 1, 'S'), ('right', True, 'S'),
                   ('right', 0.5, 'S'), ('right', 1), ('left', 2, 'S'))
        for row in invalid:
            with self.subTest(reading=row):
                with self.assertRaises(ValueError):
                    ingest(self.db, bench, 'S1', 'M1', [('left', 2, 'S'), row])
                self.assertEqual(self.observed_counts(MEASUREMENT_TABLES), (0, 0, 0, 0, 0))
        with self.assertRaises(ValueError):
            ingest(self.db, bench, 'S1', '', [('left', 2, 'S')])

    def test_write_rollback(self):
        bench = self.bench()
        rows = [('left', 2, 'S'), ('right', 2, 'S')]
        with fail_initial_revision(self.db):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'initial revision write blocked'):
                ingest(self.db, bench, 'S1', 'M1', rows)
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(self.observed_counts(MEASUREMENT_TABLES), (0, 0, 0, 0, 0))
        accepted = ingest(self.db, bench, 'S1', 'M1', rows)
        self.assertEqual(self.observed_counts(MEASUREMENT_TABLES), (1, 2, 1, 2, 1))
        frozen = RevisionStore(self.db).load_frozen(freeze(self.db, accepted.revision_id))
        self.assertEqual([reading.branch for reading in frozen.readings], ['left', 'right'])

    def test_missing_and_measured_zero(self):
        bench = self.bench()
        original = ingest(self.db, bench, 'S1', 'M1', [('left', 2, 'S')])
        with self.assertRaisesRegex(ValueError, 'missing readings.*right'):
            freeze(self.db, original.revision_id)
        self.assertEqual(self.observed_counts(('frozen_revisions', 'frozen_branch_readings')), (0, 0))
        corrected = amend(self.db, bench, original.revision_id, 'M2', [('right', 0, 'mS')])
        frozen = RevisionStore(self.db).load_frozen(freeze(self.db, corrected))
        self.assertEqual(frozen.revision_id, corrected)
        self.assertEqual([reading.branch for reading in frozen.readings], ['left', 'right'])
        measured_zero = frozen.readings[1]
        self.assertEqual((measured_zero.si, measured_zero.raw_value, measured_zero.unit, measured_zero.source),
                         (Fraction(0), 0, 'mS', 'M2'))
        self.assertEqual(measured_zero.reading_ref, dict(RevisionStore(self.db).load_revision(corrected).reading_refs)['right'])
        with self.assertRaises(ValueError):
            freeze(self.db, original.revision_id)

    def test_freeze_repeat(self):
        bench = self.bench()
        batch = ingest(self.db, bench, 'S1', 'M1', [('left', 1, 'S')])
        corrected = amend(self.db, bench, batch.revision_id, 'M2', [('right', 0, 'S')])
        first = freeze(self.db, corrected)
        self.reopen()
        self.assertEqual(freeze(self.db, corrected), first)
        with self.assertRaises(KeyError):
            freeze(self.db, corrected + 100)
        with self.assertRaises(ValueError):
            freeze(self.db, batch.revision_id)
        self.assertEqual(self.observed_counts(('frozen_revisions', 'frozen_branch_readings')), (1, 2))
