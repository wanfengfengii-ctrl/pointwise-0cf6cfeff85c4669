from fractions import Fraction
from hashlib import sha256

from fixture.catalog import register
from intake.imports import ingest
from report.export import export
from report.issue import issue
from report.read import read
from revision.freeze import freeze
from tests.support import DatabaseCase, REPORT_TABLES, scenario


class InspectionTests(DatabaseCase):
    def frozen(self, nodes, terminals, branches, values):
        bench = register(self.db, 'T1', 'bench', nodes, terminals, branches)
        rows = [(branch, value, 'S') for branch, value in values]
        batch = ingest(self.db, bench, 'S1', 'M1', rows)
        return freeze(self.db, batch.revision_id)

    def series(self, parallel=False):
        branches = [('ax', 'a', 'x'), ('xb', 'x', 'b')]
        values = [('ax', 2), ('xb', 2)]
        if parallel:
            branches.append(('direct', 'a', 'b'))
            values.append(('direct', 2))
        return self.frozen(['a', 'x', 'b'], ['a', 'b'], branches, values)

    def test_series(self):
        frozen = self.series()
        clamps = [('a', 1), ('b', 0)]
        issued = issue(self.db, frozen, clamps)
        body = issued.body
        self.assertEqual([(row['node'], row['voltage'], row['net_current']) for row in body['potentials']],
                         [('a', Fraction(1), Fraction(1)), ('x', Fraction(1, 2), Fraction(0)),
                          ('b', Fraction(0), Fraction(-1))])
        self.assertEqual([(row['terminal'], row['current']) for row in body['supplies']], [('a', 1), ('b', -1)])
        self.assertEqual([(row['current'], row['dissipation']) for row in body['branches']],
                         [(Fraction(1), Fraction(1, 2)), (Fraction(1), Fraction(1, 2))])
        self.assertEqual((body['total_dissipation'], body['source_power']), (Fraction(1), Fraction(1)))
        self.assertIsInstance(body['total_dissipation'], Fraction)
        saved = read(self.db, issued.report_id)
        digest = sha256(export(self.db, issued.report_id)).hexdigest()
        self.assertEqual(saved, issued)
        self.assertEqual(saved.receipt['body_sha256'], digest)
        scenario('v4', {'series_S': [2, 2], 'clamps_V': clamps},
                 {'x_V': '1/2', 'supplies_A': ['1', '-1'], 'loss_W': '1'},
                 {'x_V': str(body['potentials'][1]['voltage']),
                  'supplies_A': [str(row['current']) for row in body['supplies']],
                  'loss_W': str(body['total_dissipation'])},
                 {'saved_loss_W': '1', 'receipt_matches_export': True},
                 {'saved_loss_W': str(saved.body['total_dissipation']),
                  'receipt_matches_export': saved.receipt['body_sha256'] == digest},
                 ['analysis/potentials.py', 'analysis/currents.py', 'analysis/power.py', 'report/issue.py', 'report/read.py'],
                 'Two equal series resistances divide the volt equally, so each branch has 1 A and 1/2 W')

    def test_clamp_scope_order(self):
        frozen = self.series()
        register(self.db, 'T2', 'bench', ['a', 'z'], ['z'], [('az', 'a', 'z')])
        forward = issue(self.db, frozen, [('a', 1), ('b', 0)])
        reverse = issue(self.db, frozen, [('b', 0), ('a', 1)])
        self.assertEqual(reverse.body['supplies'], list(reversed(forward.body['supplies'])))
        self.assertEqual(reverse.body['clamps'], list(reversed(forward.body['clamps'])))
        self.assertEqual(reverse.body['potentials'], forward.body['potentials'])
        self.assertEqual(reverse.body['branches'], forward.body['branches'])
        for clamps in ([('a', 1), ('a', 0)], [('a', 1), ('z', 0)], [('a', 1), ('x', 0)],
                       [('a', 1), ('b', '1/0')], [('b', False)], [('b',)], []):
            with self.subTest(clamps=clamps):
                with self.assertRaises(ValueError):
                    issue(self.db, frozen, clamps)
                self.assertEqual(self.observed_counts(REPORT_TABLES), (2, 2))
        with self.assertRaises(ValueError):
            issue(self.db, frozen + 100, [('a', 1), ('b', 0)])

    def test_unclamped_island(self):
        frozen = self.frozen(['a', 'b', 'c'], ['a', 'c'], [('ab', 'a', 'b')], [('ab', 1)])
        with self.assertRaisesRegex(ValueError, 'island.*c.*no clamp'):
            issue(self.db, frozen, [('a', 1)])
        self.assertEqual(self.observed_counts(REPORT_TABLES), (0, 0))
        with self.assertRaises(KeyError):
            read(self.db, 1)

    def test_zero_bridge(self):
        frozen = self.frozen(['a', 'b', 'c', 'd'], ['a', 'c'],
                             [('ab', 'a', 'b'), ('open', 'b', 'c'), ('cd', 'c', 'd')],
                             [('ab', 2), ('open', 0), ('cd', 3)])
        issued = issue(self.db, frozen, [('a', 1), ('c', 0)])
        body = issued.body
        self.assertEqual([row['voltage'] for row in body['potentials']], [1, 1, 0, 0])
        self.assertEqual([row['current'] for row in body['supplies']], [0, 0])
        self.assertEqual([(row['branch'], row['current'], row['dissipation']) for row in body['branches']],
                         [('ab', 0, 0), ('open', 0, 0), ('cd', 0, 0)])
        self.assertEqual((body['total_dissipation'], body['source_power']), (0, 0))
        self.assertEqual((body['branches'][1]['conductance'], body['branches'][1]['source']), (0, 'M1'))
        with self.assertRaises(ValueError):
            issue(self.db, frozen, [('a', 1)])
        self.assertEqual(self.observed_counts(REPORT_TABLES), (1, 1))

    def test_parallel(self):
        frozen = self.series(parallel=True)
        report = issue(self.db, frozen, [('a', 1), ('b', 0)]).body
        self.assertEqual(report['potentials'][1], {'node': 'x', 'voltage': Fraction(1, 2), 'net_current': Fraction(0)})
        self.assertEqual([row['current'] for row in report['branches']], [1, 1, 2])
        self.assertEqual([row['dissipation'] for row in report['branches']], [Fraction(1, 2), Fraction(1, 2), 2])
        self.assertEqual([row['current'] for row in report['supplies']], [3, -3])
        self.assertEqual((report['total_dissipation'], report['source_power']), (3, 3))

    def test_parallel_ids(self):
        frozen = self.frozen(['a', 'b'], ['a', 'b'], [('out', 'a', 'b'), ('back', 'b', 'a')],
                             [('back', 2), ('out', 1)])
        body = issue(self.db, frozen, [('a', 1), ('b', 0)]).body
        self.assertEqual([(row['branch'], row['current']) for row in body['branches']], [('out', 1), ('back', -2)])
        self.assertEqual([row['current'] for row in body['supplies']], [3, -3])
        self.assertEqual((body['total_dissipation'], body['source_power']), (3, 3))

    def test_signed_clamps_and_singleton(self):
        frozen = self.frozen(['a', 'x', 'b', 'idle'], ['a', 'b', 'idle'],
                             [('ax', 'a', 'x'), ('xb', 'x', 'b')], [('ax', 2), ('xb', 2)])
        body = issue(self.db, frozen, [('a', '3/2'), ('b', '-1/2'), ('idle', '-7/3')]).body
        self.assertEqual([row['voltage'] for row in body['potentials']],
                         [Fraction(3, 2), Fraction(1, 2), Fraction(-1, 2), Fraction(-7, 3)])
        self.assertEqual([row['current'] for row in body['supplies']], [2, -2, 0])
        self.assertEqual((body['total_dissipation'], body['source_power']), (4, 4))
