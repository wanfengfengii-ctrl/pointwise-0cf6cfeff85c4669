"""Calculate and issue a fixed local inspection report."""

from hashlib import sha256
from sqlite3 import Connection

from analysis.clamps import bind_clamps
from analysis.currents import calculate_currents
from analysis.islands import find_islands, require_clamped_islands
from analysis.potentials import solve_potentials
from analysis.power import calculate_power
from fixture.store import FixtureStore
from lab import write_transaction
from report.codec import LocalReport, encode_receipt, encode_report
from report.store import ReportStore, StoredReport
from revision.store import RevisionStore


def issue(db: Connection, freeze_id: int, clamp_rows: object) -> LocalReport:
    try:
        frozen = RevisionStore(db).load_frozen(freeze_id)
    except KeyError:
        raise ValueError(f'unknown freeze {freeze_id!r}') from None
    bench = FixtureStore(db).load_bench(frozen.bench_id)
    clamps = bind_clamps(bench.terminals, clamp_rows)
    topology = bench.topology
    conductance = {reading.branch: reading.si for reading in frozen.readings}
    islands = find_islands(topology, conductance)
    require_clamped_islands(islands, clamps)
    potentials = solve_potentials(islands, conductance, clamps)
    currents = calculate_currents(topology, conductance, clamps, potentials)
    power = calculate_power(topology, conductance, clamps, potentials, currents)

    branches = []
    readings = {reading.branch: reading for reading in frozen.readings}
    for branch in topology.branches:
        reading = readings[branch.name]
        branches.append({
            'branch': branch.name,
            'start': branch.start,
            'end': branch.end,
            'conductance': reading.si,
            'current': currents.branches[branch.name],
            'dissipation': power.branches[branch.name],
            'reading_ref': reading.reading_ref,
            'source': reading.source,
            'raw_value': reading.raw_value,
            'unit': reading.unit,
        })
    body = {
        'version': 1,
        'experiment': bench.experiment,
        'bench_id': bench.bench_id,
        'bench_name': bench.name,
        'revision_id': frozen.revision_id,
        'freeze_id': frozen.freeze_id,
        'clamps': [{'terminal': clamp.terminal, 'voltage': clamp.voltage} for clamp in clamps.clamps],
        'potentials': [
            {'node': node, 'voltage': potentials.voltages[node], 'net_current': currents.node_net[node]}
            for node in topology.nodes
        ],
        'supplies': [{'terminal': name, 'current': amps} for name, amps in currents.supplies],
        'branches': branches,
        'total_dissipation': power.total,
        'source_power': power.supplied,
    }
    reports = ReportStore(db)
    with write_transaction(db):
        report_id = reports.next_report_id()
        body['report_id'] = report_id
        body_bytes = encode_report(body)
        receipt = {
            'version': 1,
            'report_id': report_id,
            'freeze_id': frozen.freeze_id,
            'body_sha256': sha256(body_bytes).hexdigest(),
        }
        reports.save_issued(StoredReport(report_id, frozen.freeze_id, body_bytes, encode_receipt(receipt)))
    return LocalReport(report_id, body, receipt)
