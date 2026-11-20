"""Prepare the two independent V1 measurements used in the cross-fixture example."""

import json
from contextlib import closing
from fractions import Fraction
from pathlib import Path

from fixture.catalog import register
from intake.imports import ingest
from lab import connect, initialize
from report.issue import issue
from revision.amend import amend
from revision.freeze import freeze


def load_sample():
    path = Path(__file__).with_name("examples") / "coupled_shift.json"
    return json.loads(path.read_text(encoding="utf-8"))


def seed_station(db, experiment, station):
    initialize(db)
    bench_id = register(db, experiment, station["bench_name"], station["nodes"],
                        station["terminals"], station["branches"])
    batch = ingest(db, bench_id, station["submission_id"], station["source"], station["readings"])
    return bench_id, batch.revision_id, freeze(db, batch.revision_id)


def main():
    work = load_sample()
    left, right = work["stations"]
    with closing(connect(":memory:")) as left_db, closing(connect(":memory:")) as right_db:
        left_ids = seed_station(left_db, work["experiment"], left)
        right_ids = seed_station(right_db, work["experiment"], right)
        bench_id, revision_id, old_freeze = left_ids
        corrected = amend(left_db, bench_id, revision_id, left["correction_source"], left["correction"])
        new_freeze = freeze(left_db, corrected)
        old = issue(left_db, old_freeze, left["clamps"]).body
        new = issue(left_db, new_freeze, left["clamps"]).body
        other = issue(right_db, right_ids[2], right["clamps"]).body
        unit_clamps = [(name, int(name == "a")) for name, _ in left["clamps"]]
        powers = tuple(issue(left_db, fid, unit_clamps).body["total_dissipation"]
                       for fid in (old_freeze, new_freeze))
        if left_ids != right_ids or new_freeze == old_freeze:
            raise RuntimeError("the sample did not produce independent station identities and a new freeze")
        if any(record["total_dissipation"] != 0 for record in (old, new, other)):
            raise RuntimeError("equal-voltage fixture checks should have zero dissipation")
        if old["supplies"] != new["supplies"] or powers != (Fraction(1), Fraction(3, 2)):
            raise RuntimeError("the old and corrected measurements disagree with the local check")
        print(f"工装甲、乙本地编号各为 {left_ids}，等电位报告耗散均为 0 W")
        print(f"工装甲端差 1 V，原冻结与勘误冻结耗散分别为 {powers[0]}、{powers[1]} W")


if __name__ == "__main__":
    main()
