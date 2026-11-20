"""Persist accepted terminal pieces and fixed cross-fixture reports."""

import json
from dataclasses import dataclass
from fractions import Fraction
from sqlite3 import Connection

from intake.units import rational_text
from lab import is_record_id
from report.piece import TerminalPiece


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS accepted_pieces (
        id INTEGER PRIMARY KEY,
        experiment TEXT NOT NULL,
        bench_name TEXT NOT NULL,
        revision_id INTEGER NOT NULL,
        freeze_id INTEGER NOT NULL,
        terminals TEXT NOT NULL,
        matrix TEXT NOT NULL,
        islands TEXT NOT NULL,
        payload BLOB NOT NULL,
        sha256 TEXT NOT NULL
    )''',
    '''CREATE INDEX IF NOT EXISTS accepted_pieces_by_experiment
       ON accepted_pieces(experiment)''',
    '''CREATE TABLE IF NOT EXISTS coupled_reports (
        id INTEGER PRIMARY KEY,
        body BLOB NOT NULL
    )''',
    '''CREATE TABLE IF NOT EXISTS coupled_report_receipts (
        report_id INTEGER PRIMARY KEY REFERENCES coupled_reports(id),
        receipt BLOB NOT NULL
    )''',
)


def _encode_matrix(matrix: tuple[tuple[Fraction, ...], ...]) -> str:
    return json.dumps([[rational_text(value) for value in row] for row in matrix],
                      ensure_ascii=False, separators=(',', ':'))


@dataclass(frozen=True)
class AcceptedPiece:
    piece_id: int
    experiment: str
    bench_name: str
    revision_id: int
    freeze_id: int
    terminals: tuple[str, ...]
    matrix: tuple[tuple[Fraction, ...], ...]
    islands: tuple[tuple[int, ...], ...]
    payload: bytes
    sha256: str


@dataclass(frozen=True)
class StoredCoupledReport:
    report_id: int
    body: bytes
    receipt: bytes


class CoupledStore:
    def __init__(self, db: Connection):
        self.db = db

    def initialize(self) -> None:
        for statement in _SCHEMA:
            self.db.execute(statement)

    def accept_piece(self, piece: TerminalPiece) -> int:
        return self.db.execute(
            '''INSERT INTO accepted_pieces(
                   experiment, bench_name, revision_id, freeze_id,
                   terminals, matrix, islands, payload, sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (piece.experiment, piece.bench_name, piece.revision_id, piece.freeze_id,
             json.dumps(list(piece.terminals), ensure_ascii=False),
             _encode_matrix(piece.matrix),
             json.dumps([list(group) for group in piece.islands]),
             piece.payload, piece.sha256),
        ).lastrowid

    def load_piece(self, piece_id: int) -> AcceptedPiece:
        if not is_record_id(piece_id):
            raise KeyError(piece_id)
        row = self.db.execute(
            '''SELECT experiment, bench_name, revision_id, freeze_id,
                      terminals, matrix, islands, payload, sha256
               FROM accepted_pieces WHERE id = ?''', (piece_id,),
        ).fetchone()
        if row is None:
            raise KeyError(piece_id)
        experiment, bench_name, revision_id, freeze_id, terminals, matrix, islands, payload, digest = row
        return AcceptedPiece(
            piece_id, experiment, bench_name, revision_id, freeze_id,
            tuple(json.loads(terminals)),
            tuple(tuple(Fraction(item) for item in line) for line in json.loads(matrix)),
            tuple(tuple(group) for group in json.loads(islands)),
            payload, digest,
        )

    def next_report_id(self) -> int:
        return self.db.execute('SELECT COALESCE(MAX(id), 0) + 1 FROM coupled_reports').fetchone()[0]

    def save_report(self, report: StoredCoupledReport) -> None:
        self.db.execute(
            'INSERT INTO coupled_reports(id, body) VALUES (?, ?)', (report.report_id, report.body),
        )
        self.db.execute(
            'INSERT INTO coupled_report_receipts(report_id, receipt) VALUES (?, ?)',
            (report.report_id, report.receipt),
        )

    def load_report(self, report_id: int) -> StoredCoupledReport:
        if not is_record_id(report_id):
            raise KeyError(report_id)
        row = self.db.execute(
            '''SELECT r.body, c.receipt FROM coupled_reports AS r
               JOIN coupled_report_receipts AS c ON c.report_id = r.id WHERE r.id = ?''',
            (report_id,),
        ).fetchone()
        if row is None:
            raise KeyError(report_id)
        body, receipt = row
        return StoredCoupledReport(report_id, body, receipt)
