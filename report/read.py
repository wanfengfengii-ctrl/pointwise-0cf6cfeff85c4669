"""Retrieve the report actually handed to the next shift."""

from sqlite3 import Connection

from report.codec import LocalReport, decode_receipt, decode_report
from report.store import ReportStore


def read(db: Connection, report_id: int) -> LocalReport:
    record = ReportStore(db).load_issued(report_id)
    return LocalReport(record.report_id, decode_report(record.body), decode_receipt(record.receipt))
