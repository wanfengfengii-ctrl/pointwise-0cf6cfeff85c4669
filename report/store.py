"""Store the local report body and receipt under a single report ID."""

from dataclasses import dataclass
from sqlite3 import Connection

from lab import is_record_id


_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS local_reports (
        id INTEGER PRIMARY KEY,
        freeze_id INTEGER NOT NULL REFERENCES frozen_revisions(id),
        body BLOB NOT NULL
    )''',
    '''CREATE INDEX IF NOT EXISTS local_reports_by_freeze ON local_reports(freeze_id)''',
    '''CREATE TABLE IF NOT EXISTS report_receipts (
        report_id INTEGER PRIMARY KEY REFERENCES local_reports(id),
        receipt BLOB NOT NULL
    )''',
)


@dataclass(frozen=True)
class StoredReport:
    report_id: int
    freeze_id: int
    body: bytes
    receipt: bytes


class ReportStore:
    def __init__(self, db: Connection):
        self.db = db

    def initialize(self) -> None:
        for statement in _SCHEMA:
            self.db.execute(statement)

    def next_report_id(self) -> int:
        return self.db.execute('SELECT COALESCE(MAX(id), 0) + 1 FROM local_reports').fetchone()[0]

    def save_issued(self, report: StoredReport) -> None:
        self.db.execute(
            'INSERT INTO local_reports(id, freeze_id, body) VALUES (?, ?, ?)',
            (report.report_id, report.freeze_id, report.body),
        )
        self.db.execute(
            'INSERT INTO report_receipts(report_id, receipt) VALUES (?, ?)', (report.report_id, report.receipt),
        )

    def load_issued(self, report_id: int) -> StoredReport:
        if not is_record_id(report_id):
            raise KeyError(report_id)
        row = self.db.execute(
            '''SELECT r.freeze_id, r.body, c.receipt FROM local_reports AS r
               JOIN report_receipts AS c ON c.report_id = r.id WHERE r.id = ?''', (report_id,),
        ).fetchone()
        if row is None:
            raise KeyError(report_id)
        freeze_id, body, receipt = row
        return StoredReport(report_id, freeze_id, body, receipt)
