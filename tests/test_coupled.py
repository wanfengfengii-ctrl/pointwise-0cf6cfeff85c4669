import json
import sqlite3
from contextlib import closing
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from coupled_sample import load_sample, seed_station
from fixture.catalog import register
from intake.imports import ingest
from lab import connect, initialize
from report.codec import encode_report
from report.issue import accept_terminal_piece, issue, issue_coupled
from report.piece import decode_terminal_piece
from report.read import read_coupled
from report.coupled_store import CoupledStore
from revision.amend import amend
from revision.freeze import export_terminal_piece, freeze
from tests.support import DatabaseCase, scenario


PIECE_TABLES = ('accepted_pieces',)
COUPLED_REPORT_TABLES = ('coupled_reports', 'coupled_report_receipts')


class CoupledTests(DatabaseCase):
    def stations(self):
        work = load_sample()
        left, right = work['stations']
        left_db = connect(':memory:')
        self.addCleanup(left_db.close)
        right_db = connect(':memory:')
        self.addCleanup(right_db.close)
        left_ids = seed_station(left_db, work['experiment'], left)
        right_ids = seed_station(right_db, work['experiment'], right)
        return work, left_db, right_db, left_ids, right_ids

    def pieces(self):
        work, left_db, right_db, left_ids, right_ids = self.stations()
        left_piece = export_terminal_piece(left_db, left_ids[2], work['stations'][0]['published_terminals'])
        right_piece = export_terminal_piece(right_db, right_ids[2], work['stations'][1]['published_terminals'])
        return work, left_db, right_db, left_ids, right_ids, left_piece, right_piece

    def accepted(self, payloads):
        return tuple(accept_terminal_piece(self.db, payload) for payload in payloads)

    def test_sample_requests(self):
        work, _, _, _, _, left_piece, right_piece = self.pieces()
        left_id, right_id = self.accepted((left_piece, right_piece))
        expected = {
            'closed': (True, ['1'], ['1', '0']),
            'open': (False, None, None),
            'parallel': (True, ['1/2', '-1/2'], ['1', '0']),
        }
        actual = {}
        for name, (feasible, currents, dissipation) in expected.items():
            report = issue_coupled(self.db, [left_id, right_id],
                                   work['jumpers'][name], work['injections'])
            body = report.body
            actual[name] = (
                body['feasible'],
                None if body['jumper_currents'] is None else [str(value) for value in body['jumper_currents']],
                None if body['dissipation'] is None else [str(value) for value in body['dissipation']],
            )
            self.assertEqual(actual[name], (feasible, currents, dissipation))
            saved = read_coupled(self.db, report.report_id)
            self.assertEqual(saved, report)
            self.assertEqual(saved.receipt['body_sha256'],
                             sha256(encode_report(report.body)).hexdigest())
            self.assertEqual(saved.receipt['version'], 2)
            self.assertEqual([row['bench_name'] for row in saved.body['pieces']], ['甲', '乙'])
            self.assertEqual([row['sha256'] for row in saved.body['pieces']],
                             [sha256(left_piece).hexdigest(), sha256(right_piece).hexdigest()])
        open_empty = issue_coupled(self.db, (left_id, right_id), work['jumpers']['open'], [])
        self.assertEqual((open_empty.body['feasible'],
                          open_empty.body['jumper_currents'], open_empty.body['dissipation']),
                         (True, [Fraction(0)], [Fraction(0), Fraction(0)]))
        no_jumper = issue_coupled(self.db, [left_id, right_id], [],
                                  [[[0, 'd'], 1], [[1, 'd'], -1]])
        self.assertEqual(no_jumper.body['feasible'], False)
        self.assertIsNone(no_jumper.body['jumper_currents'])
        self.assertIsNone(no_jumper.body['dissipation'])
        self.assertEqual(no_jumper.body['jumpers'], [])
        self.assertEqual(no_jumper.body['injections'],
                         [[[0, 'd'], Fraction(1)], [[1, 'd'], Fraction(-1)]])
        scenario('v9', {'closed_A': ['1'], 'open_A': None, 'parallel_A': ['1/2', '-1/2']},
                 {'closed_W': ['1', '0'], 'open_feasible': False, 'parallel_W': ['1', '0']},
                 {'closed_W': actual['closed'][2], 'open_feasible': actual['open'][0],
                  'parallel_W': actual['parallel'][2]},
                 {'open_empty_A': ['0'], 'saved_matches_issue': True},
                 {'open_empty_A': [str(open_empty.body['jumper_currents'][0])],
                  'saved_matches_issue': read_coupled(self.db, open_empty.report_id) == open_empty},
                 ['analysis/response.py', 'revision/freeze.py', 'report/piece.py',
                  'report/coupled.py', 'report/issue.py', 'report/read.py'],
                 'A 1 S jumper carrying 1 A dissipates 1 W in the left fixture; an open jumper isolates c')

    def test_corrected_freeze(self):
        work, left_db, _, left_ids, _, _, right_piece = self.pieces()
        old_piece = export_terminal_piece(left_db, left_ids[2], work['stations'][0]['published_terminals'])
        corrected = amend(left_db, left_ids[0], left_ids[1], work['stations'][0]['correction_source'],
                          work['stations'][0]['correction'])
        new_piece = export_terminal_piece(left_db, freeze(left_db, corrected),
                                          work['stations'][0]['published_terminals'])
        old_id, new_id, right_id = self.accepted((old_piece, new_piece, right_piece))
        old = issue_coupled(self.db, [old_id, right_id], work['jumpers']['closed'], work['injections'])
        new = issue_coupled(self.db, [new_id, right_id], work['jumpers']['closed'], work['injections'])
        self.assertEqual(old.body['dissipation'], [Fraction(1), Fraction(0)])
        self.assertEqual(new.body['dissipation'], [Fraction(2, 3), Fraction(0)])
        self.assertEqual(old.body['jumper_currents'], [Fraction(1)])

    def test_three_terminal_hand_check(self):
        with closing(connect(':memory:')) as left_db, closing(connect(':memory:')) as right_db:
            initialize(left_db)
            initialize(right_db)
            left = register(left_db, 'HX-12', '甲', ['a', 'b', 'd', 'private'],
                            ['a', 'b', 'd'],
                            [('a1', 'a', 'private'), ('b1', 'b', 'private'), ('d1', 'd', 'private')])
            left_batch = ingest(left_db, left, 'shift-a', 'M-A',
                                [('a1', 1, 'S'), ('b1', 1, 'S'), ('d1', 1, 'S')])
            left_freeze = freeze(left_db, left_batch.revision_id)
            right = register(right_db, 'HX-12', '乙', ['c'], ['c'], [])
            right_batch = ingest(right_db, right, 'shift-b', 'M-B', [])
            right_freeze = freeze(right_db, right_batch.revision_id)
            left_piece = export_terminal_piece(left_db, left_freeze, ['a', 'b', 'd'])
            right_piece = export_terminal_piece(right_db, right_freeze, ['c'])
        self.assertNotIn(b'private', left_piece)
        self.assertNotIn(b'a1', left_piece)
        left_id, right_id = self.accepted((left_piece, right_piece))
        report = issue_coupled(
            self.db, [left_id, right_id],
            [['J1', [0, 'b'], [1, 'c'], 1], ['J2', [0, 'd'], [1, 'c'], 1]],
            [[[0, 'a'], 1], [[1, 'c'], -1]],
        )
        self.assertTrue(report.body['feasible'])
        self.assertEqual(report.body['jumper_currents'], [Fraction(1, 2), Fraction(1, 2)])
        self.assertEqual(report.body['dissipation'], [Fraction(3, 2), Fraction(0)])

    def test_piece_is_fixed_and_identities_are_local(self):
        work, left_db, right_db, left_ids, right_ids, left_piece, right_piece = self.pieces()
        self.assertEqual(self.stations_export(left_db, left_ids[2], work, 0), left_piece)
        self.assertEqual(self.stations_export(right_db, right_ids[2], work, 1), right_piece)
        self.assertEqual(left_ids, right_ids)
        left_id, right_id = self.accepted((left_piece, right_piece))
        report = issue_coupled(self.db, [left_id, right_id], work['jumpers']['closed'], work['injections'])
        self.assertEqual([row['piece_id'] for row in report.body['pieces']], [left_id, right_id])
        self.assertEqual([row['freeze_id'] for row in report.body['pieces']],
                         [left_ids[2], right_ids[2]])
        other_experiment = json.loads(left_piece.decode('utf-8'))
        other_experiment['experiment'] = 'OTHER'
        other_piece = json.dumps(other_experiment, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':')).encode('utf-8')
        other_id = accept_terminal_piece(self.db, other_piece)
        before = self.observed_counts(COUPLED_REPORT_TABLES)
        with self.assertRaises(ValueError):
            issue_coupled(self.db, [other_id, right_id], [], [])
        self.assertEqual(self.observed_counts(COUPLED_REPORT_TABLES), before)

    def stations_export(self, db, freeze_id, work, index):
        return export_terminal_piece(db, freeze_id, work['stations'][index]['published_terminals'])

    def test_station_export_errors(self):
        work, left_db, _, left_ids, _, _, _ = self.pieces()
        terminals = work['stations'][0]['published_terminals']
        payload = export_terminal_piece(left_db, left_ids[2], terminals)
        self.assertEqual(export_terminal_piece(left_db, left_ids[2], terminals), payload)
        for bad in (terminals + [terminals[0]], [], ['x'], [True], 'b'):
            with self.subTest(terminals=bad):
                with self.assertRaises(ValueError):
                    export_terminal_piece(left_db, left_ids[2], bad)
        with self.assertRaises(ValueError):
            export_terminal_piece(left_db, left_ids[2] + 100, terminals)
        record = json.loads(payload.decode('utf-8'))
        self.assertEqual((record['version'], record['experiment'], record['bench_name']), (2, 'HX-12', '甲'))
        self.assertEqual(record['terminals'], terminals)
        self.assertNotIn('source', payload.decode('utf-8'))
        self.assertNotIn('ax', payload.decode('utf-8'))

    def test_bad_pieces(self):
        work, _, _, _, _, left_piece, _ = self.pieces()
        record = json.loads(left_piece.decode('utf-8'))
        accepted = accept_terminal_piece(self.db, left_piece)
        before = self.observed_counts(PIECE_TABLES)
        variants = []

        def variant(mutate):
            copy = json.loads(json.dumps(record))
            mutate(copy)
            variants.append(json.dumps(copy, ensure_ascii=False, sort_keys=True,
                                       separators=(',', ':')).encode('utf-8'))

        variant(lambda item: item.update(version=1))
        variant(lambda item: item.update(version='2'))
        variant(lambda item: item.pop('experiment'))
        variant(lambda item: item.update(bench_name=''))
        variant(lambda item: item.update(revision_id=0))
        variant(lambda item: item.update(freeze_id=True))
        variant(lambda item: item.update(terminals=[]))
        variant(lambda item: item.update(terminals=['a', 'a']))
        variant(lambda item: item['response'].update(matrix=[['1/1']]))
        variant(lambda item: item['response'].update(matrix=[['1/2', 'x', '0/1'],
                                                             ['-1/1', '1/1', '0/1'],
                                                             ['0/1', '0/1', '0/1']]))
        variant(lambda item: item['response'].update(matrix=[['1/1', '1/1', '0/1'],
                                                             ['-1/1', '1/1', '0/1'],
                                                             ['0/1', '0/1', '0/1']]))
        variant(lambda item: item['response'].update(islands=[[0, 1]]))
        variant(lambda item: item['response'].update(islands=[[0], [1], [2], [0]]))
        variant(lambda item: item['response'].update(islands=[[]]))
        bad = [
            'text',
            left_piece.decode('utf-8'),
            b'\xff\xfe',
            b'not json',
            b'[]',
            b'{"version": 2}',
            json.dumps({**record, 'version': 1}).encode('utf-8'),
            *variants,
        ]
        for payload in bad:
            with self.subTest(payload=payload[:24] if isinstance(payload, bytes) else payload):
                with self.assertRaises(ValueError):
                    accept_terminal_piece(self.db, payload)
                self.assertEqual(self.observed_counts(PIECE_TABLES), before)
        self.assertEqual(accept_terminal_piece(self.db, left_piece), accepted + 1)

    def test_bad_requests(self):
        work, _, _, _, _, left_piece, right_piece = self.pieces()
        left_id, right_id = self.accepted((left_piece, right_piece))
        closed = work['jumpers']['closed']
        before = self.observed_counts(COUPLED_REPORT_TABLES)
        bad_requests = (
            ([left_id], closed, work['injections']),
            ([left_id, right_id, left_id], closed, work['injections']),
            ([left_id, 9999], closed, work['injections']),
            ([left_id, True], closed, work['injections']),
            (left_id, closed, work['injections']),
            ([left_id, right_id], [['J', [0, 'b'], [0, 'a'], 1]], work['injections']),
            ([left_id, right_id], [['J', [0, 'b'], [1, 'c'], -1]], work['injections']),
            ([left_id, right_id], [['J', [0, 'b'], [1, 'c'], 0.5]], work['injections']),
            ([left_id, right_id], [['J', [0, 'b'], [1, 'c'], True]], work['injections']),
            ([left_id, right_id], [['', [0, 'b'], [1, 'c'], 1]], work['injections']),
            ([left_id, right_id], [['J', [0, 'b'], [1, 'c'], 1],
                                   ['J', [0, 'a'], [1, 'd'], 1]], work['injections']),
            ([left_id, right_id], [['J', [2, 'b'], [1, 'c'], 1]], work['injections']),
            ([left_id, right_id], [['J', [False, 'b'], [1, 'c'], 1]], work['injections']),
            ([left_id, right_id], [['J', [0, 'zzz'], [1, 'c'], 1]], work['injections']),
            ([left_id, right_id], [['J', [0, 'b'], [1, 'zzz'], 1]], work['injections']),
            ([left_id, right_id], [['J']], work['injections']),
            ([left_id, right_id], closed, [[[0, 'a'], 1], [[0, 'a'], -1]]),
            ([left_id, right_id], closed, [[[0, 'a'], 0.5]]),
            ([left_id, right_id], closed, [[[0, 'a'], True]]),
            ([left_id, right_id], closed, [[[0, 'zzz'], 1]]),
            ([left_id, right_id], closed, [[[0], 1]]),
            ([left_id, right_id], closed, [[[0, 'a'], 1, 2]]),
        )
        for piece_ids, jumpers, injections in bad_requests:
            with self.subTest(piece_ids=piece_ids, jumpers=jumpers, injections=injections):
                with self.assertRaises(ValueError):
                    issue_coupled(self.db, piece_ids, jumpers, injections)
                self.assertEqual(self.observed_counts(COUPLED_REPORT_TABLES), before)
        with self.assertRaises(ValueError):
            issue_coupled(self.db, [left_id, left_id], [], [])

    def test_commit_failure_retry(self):
        work, _, _, _, _, left_piece, right_piece = self.pieces()
        left_id, right_id = self.accepted((left_piece, right_piece))
        self.db.execute('CREATE TABLE test_coupled_parent (id INTEGER PRIMARY KEY)')
        self.db.execute('''CREATE TABLE test_coupled_child (
            missing_id INTEGER REFERENCES test_coupled_parent(id) DEFERRABLE INITIALLY DEFERRED)''')
        self.db.execute('''CREATE TRIGGER test_reject_coupled_commit
            AFTER INSERT ON coupled_report_receipts
            BEGIN INSERT INTO test_coupled_child(missing_id) VALUES (1); END''')
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                issue_coupled(self.db, [left_id, right_id], work['jumpers']['closed'], work['injections'])
            self.assertFalse(self.db.in_transaction)
            self.assertEqual(self.observed_counts(COUPLED_REPORT_TABLES), (0, 0))
            with self.assertRaises(KeyError):
                read_coupled(self.db, 1)
        finally:
            self.db.execute('DROP TRIGGER test_reject_coupled_commit')
            self.db.execute('DROP TABLE test_coupled_child')
            self.db.execute('DROP TABLE test_coupled_parent')
        retried = issue_coupled(self.db, [left_id, right_id], work['jumpers']['closed'], work['injections'])
        self.assertEqual(self.observed_counts(COUPLED_REPORT_TABLES), (1, 1))
        self.reopen()
        saved = read_coupled(self.db, retried.report_id)
        self.assertEqual(saved, retried)
        self.assertEqual(saved.body['jumper_currents'], [Fraction(1)])

    def test_reopen_and_unknown(self):
        work, _, _, _, _, left_piece, right_piece = self.pieces()
        left_id, right_id = self.accepted((left_piece, right_piece))
        report = issue_coupled(self.db, [left_id, right_id], work['jumpers']['parallel'], work['injections'])
        initialize(self.db)
        initialize(self.db)
        self.reopen()
        self.assertEqual(read_coupled(self.db, report.report_id), report)
        self.assertEqual(CoupledStore(self.db).load_piece(left_id).payload, left_piece)
        for unknown in (0, -1, True, 1.0, report.report_id + 100, '1'):
            with self.subTest(report_id=unknown):
                with self.assertRaises(KeyError):
                    read_coupled(self.db, unknown)

    def test_closed_stations_then_reopen_centre(self):
        work = load_sample()
        left, right = work['stations']
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        left_path = Path(temporary.name) / 'station-a.sqlite3'
        right_path = Path(temporary.name) / 'station-b.sqlite3'
        with closing(connect(left_path)) as station:
            left_ids = seed_station(station, work['experiment'], left)
        with closing(connect(right_path)) as station:
            right_ids = seed_station(station, work['experiment'], right)
        with closing(connect(left_path)) as station:
            left_piece = export_terminal_piece(station, left_ids[2], left['published_terminals'])
        with closing(connect(right_path)) as station:
            right_piece = export_terminal_piece(station, right_ids[2], right['published_terminals'])
        centre_path = Path(temporary.name) / 'centre.sqlite3'
        with closing(connect(centre_path)) as centre:
            initialize(centre)
            left_id = accept_terminal_piece(centre, left_piece)
            right_id = accept_terminal_piece(centre, right_piece)
            closed = issue_coupled(centre, [left_id, right_id],
                                   work['jumpers']['closed'], work['injections'])
            opened = issue_coupled(centre, [left_id, right_id],
                                   work['jumpers']['open'], work['injections'])
        with closing(connect(centre_path)) as next_shift:
            self.assertEqual(read_coupled(next_shift, closed.report_id), closed)
            self.assertEqual(read_coupled(next_shift, opened.report_id), opened)
        self.assertEqual((closed.body['feasible'], closed.body['jumper_currents'],
                          closed.body['dissipation']),
                         (True, [Fraction(1)], [Fraction(1), Fraction(0)]))
        self.assertEqual((opened.body['feasible'], opened.body['jumper_currents'],
                          opened.body['dissipation']), (False, None, None))

    def test_piece_matches_local_v1_response(self):
        edges = [('ap', 'a', 'p', 2), ('bp', 'b', 'p', 3), ('pq', 'p', 'q', 1),
                 ('qb', 'q', 'b', 5), ('aq', 'a', 'q', '1/2')]
        bench = register(self.db, 'E', 'bench', ['a', 'b', 'p', 'q'], ['a', 'b'],
                         [(name, start, end) for name, start, end, _ in edges])
        batch = ingest(self.db, bench, 's', 'M', [(name, value, 'S') for name, _, _, value in edges])
        frozen = freeze(self.db, batch.revision_id)
        piece = decode_terminal_piece(export_terminal_piece(self.db, frozen, ['a', 'b']))
        self.assertEqual(piece.islands, ((0, 1),))
        for left, right in (('1', '0'), ('2', '3'), ('1/2', '-1/3')):
            local = issue(self.db, frozen, [('a', left), ('b', right)]).body
            supplies = {row['terminal']: row['current'] for row in local['supplies']}
            left, right = Fraction(left), Fraction(right)
            currents = [piece.matrix[row][0] * left + piece.matrix[row][1] * right for row in range(2)]
            predicted = left * currents[0] + right * currents[1]
            self.assertEqual(supplies, {'a': currents[0], 'b': currents[1]})
            self.assertEqual(local['total_dissipation'], predicted)

    def test_v1_report_bytes_are_not_pieces(self):
        from report.export import export

        bench, batch, frozen = self.single_branch()
        bytes_v1 = export(self.db, issue(self.db, frozen, [('a', 1), ('b', 0)]).report_id)
        with self.assertRaises(ValueError):
            accept_terminal_piece(self.db, bytes_v1)
        self.assertEqual(self.observed_counts(PIECE_TABLES), (0,))
