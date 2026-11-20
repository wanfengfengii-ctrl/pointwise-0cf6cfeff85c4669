"""Export the issued body bytes for an offline local inspection record."""

from sqlite3 import Connection

from report.store import ReportStore


def export(db: Connection, report_id: int) -> bytes:
    return ReportStore(db).load_issued(report_id).body
