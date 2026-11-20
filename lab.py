"""Connection and transaction boundaries for a laboratory work database."""

import argparse
import sqlite3
from contextlib import closing, contextmanager
from os import PathLike


def connect(path: str | PathLike[str]) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        db.close()
        raise
    return db


def is_record_id(value: object) -> bool:
    return type(value) is int and 0 < value <= 2**63 - 1


@contextmanager
def write_transaction(db: sqlite3.Connection):
    if db.in_transaction:
        raise ValueError('write operation requires a connection outside a transaction')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def initialize(db: sqlite3.Connection) -> None:
    from fixture.store import FixtureStore
    from intake.store import IntakeStore
    from report.coupled_store import CoupledStore
    from report.store import ReportStore
    from revision.store import RevisionStore

    db.execute('PRAGMA foreign_keys = ON')
    with write_transaction(db):
        for store in (FixtureStore, IntakeStore, RevisionStore, ReportStore, CoupledStore):
            store(db).initialize()


def main() -> None:
    parser = argparse.ArgumentParser(description='Initialize a laboratory work database')
    parser.add_argument('database')
    args = parser.parse_args()
    with closing(connect(args.database)) as db:
        initialize(db)


if __name__ == '__main__':
    main()
