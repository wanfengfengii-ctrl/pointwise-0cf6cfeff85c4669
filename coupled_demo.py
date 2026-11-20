"""Demonstrate closed-jumper issuance, open-jumper ruling and next-shift retrieval."""

from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from coupled_sample import load_sample, seed_station
from lab import connect, initialize
from report.issue import accept_terminal_piece, issue_coupled
from report.read import read_coupled
from revision.freeze import export_terminal_piece


def main() -> None:
    work = load_sample()
    left, right = work['stations']
    with TemporaryDirectory(prefix='coupled-shift-') as directory:
        left_path = Path(directory) / 'station-a.sqlite3'
        right_path = Path(directory) / 'station-b.sqlite3'
        centre_path = Path(directory) / 'centre.sqlite3'

        with closing(connect(left_path)) as left_db:
            left_ids = seed_station(left_db, work['experiment'], left)
        with closing(connect(right_path)) as right_db:
            right_ids = seed_station(right_db, work['experiment'], right)
        with closing(connect(left_path)) as left_db:
            left_piece = export_terminal_piece(left_db, left_ids[2], left['published_terminals'])
        with closing(connect(right_path)) as right_db:
            right_piece = export_terminal_piece(right_db, right_ids[2], right['published_terminals'])

        with closing(connect(centre_path)) as centre:
            initialize(centre)
            left_piece_id = accept_terminal_piece(centre, left_piece)
            right_piece_id = accept_terminal_piece(centre, right_piece)
            closed = issue_coupled(centre, [left_piece_id, right_piece_id],
                                   work['jumpers']['closed'], work['injections'])
            opened = issue_coupled(centre, [left_piece_id, right_piece_id],
                                   work['jumpers']['open'], work['injections'])
        if (closed.body['feasible'], closed.body['jumper_currents'], closed.body['dissipation']) != (
            True, [Fraction(1)], [Fraction(1), Fraction(0)],
        ):
            raise RuntimeError('the closed jumper ruling differs from the sample check')
        if opened.body['feasible'] or opened.body['jumper_currents'] is not None:
            raise RuntimeError('the open jumper should be infeasible with the sample injections')
        print(f'关闭两站库后接纳端子件 {left_piece_id}、{right_piece_id}；'
              f'接通跳线可行，跳线电流 {closed.body["jumper_currents"]} A，'
              f'甲乙耗散 {closed.body["dissipation"]} W')
        print('同一对端点的零电导跳线断开，甲 a 与乙 c 分属不同分量，裁决不可行')

        with closing(connect(centre_path)) as next_shift:
            if (read_coupled(next_shift, closed.report_id), read_coupled(next_shift, opened.report_id)) != (
                closed, opened,
            ):
                raise RuntimeError('the reopened centre returned different fixed reports')
            print(f'重开中心库后按号领取固定报告 {closed.report_id}、{opened.report_id}，'
                  f'接通报告摘要 {closed.receipt["body_sha256"][:16]}…')


if __name__ == '__main__':
    main()
