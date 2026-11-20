"""Replay a work order and reopen both signed reports as the next shift."""

import json
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from fixture.catalog import register
from intake.imports import ingest
from lab import connect, initialize
from report.export import export
from report.issue import issue
from report.read import read
from revision.amend import amend
from revision.freeze import freeze


def main() -> None:
    sample = Path(__file__).resolve().parent / 'examples' / 'day_shift.json'
    work = json.loads(sample.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='harness-shift-') as directory:
        database = Path(directory) / 'shift.sqlite3'
        with closing(connect(database)) as db:
            initialize(db)
            bench = register(db, work['experiment'], work['bench'], work['nodes'], work['terminals'], work['branches'])
            batch = ingest(db, bench, work['submission_id'], work['source'], work['readings'])
            before = issue(db, freeze(db, batch.revision_id), work['clamps'])
            original_bytes = export(db, before.report_id)
            corrected = amend(db, bench, batch.revision_id, work['correction_source'], work['correction'])
            after = issue(db, freeze(db, corrected), work['clamps'])

        with closing(connect(database)) as next_shift:
            old = read(next_shift, before.report_id)
            new = read(next_shift, after.report_id)
            if (old, new) != (before, after) or export(next_shift, old.report_id) != original_bytes:
                raise RuntimeError('the reports recovered by the next shift differ from the issued records')
            if (old.body['total_dissipation'], new.body['total_dissipation']) != (Fraction(1), Fraction(3, 2)):
                raise RuntimeError('dissipation differs from the 2+2 S and 2+6 S series checks')
            if (old.body['branches'][1]['source'], new.body['branches'][1]['source']) != (
                work['source'], work['correction_source'],
            ):
                raise RuntimeError('the corrected branch lost its original or revised origin')
            for record in (old, new):
                print(export(next_shift, record.report_id).decode('utf-8'))

    from coupled_demo import main as coupled_main
    coupled_main()


if __name__ == '__main__':
    main()
