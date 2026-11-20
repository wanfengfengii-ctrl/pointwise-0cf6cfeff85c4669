"""Calculate and issue a fixed local inspection report."""

from hashlib import sha256
from sqlite3 import Connection

from analysis.clamps import bind_clamps
from analysis.currents import calculate_currents
from analysis.islands import find_islands, require_clamped_islands
from analysis.potentials import solve_potentials
from analysis.power import calculate_power
from fixture.store import FixtureStore
from lab import is_record_id, write_transaction
from report.codec import LocalReport, encode_receipt, encode_report
from report.coupled import build_request, solve_request
from report.coupled_store import CoupledStore, StoredCoupledReport
from report.piece import TerminalPiece, decode_terminal_piece
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


def _load_piece(store: CoupledStore, piece_id: object):
    if not is_record_id(piece_id):
        raise ValueError(f'invalid piece ID {piece_id!r}')
    try:
        return store.load_piece(piece_id)
    except KeyError:
        raise ValueError(f'unknown piece {piece_id!r}') from None


def accept_terminal_piece(db: Connection, payload: object) -> int:
    """Validate a station terminal piece and persist its exact accepted bytes."""
    piece = decode_terminal_piece(payload)
    with write_transaction(db):
        return CoupledStore(db).accept_piece(piece)


def issue_coupled(
    db: Connection, piece_ids: object, jumper_rows: object, injection_rows: object,
) -> LocalReport:
    """Issue one fixed cross-fixture report from two accepted pieces and a request."""
    ids = piece_ids
    if not isinstance(ids, (list, tuple)) or len(ids) != 2:
        raise ValueError('a cross-fixture request selects exactly two pieces')
    store = CoupledStore(db)
    accepted = [_load_piece(store, piece_id) for piece_id in ids]
    left, right = accepted
    if left.experiment != right.experiment:
        raise ValueError('selected pieces belong to different experiments')
    if left.bench_name == right.bench_name:
        raise ValueError('selected pieces must come from two different fixtures')
    pieces = tuple(
        TerminalPiece(
            item.experiment, item.bench_name, item.revision_id, item.freeze_id,
            item.terminals, item.matrix, item.islands, item.payload, item.sha256,
        )
        for item in accepted
    )
    request = build_request(pieces, jumper_rows, injection_rows)
    result = solve_request(request)

    body = {
        'version': 2,
        'experiment': left.experiment,
        'pieces': [
            {
                'piece_id': item.piece_id,
                'bench_name': item.bench_name,
                'revision_id': item.revision_id,
                'freeze_id': item.freeze_id,
                'terminals': list(item.terminals),
                'sha256': item.sha256,
            }
            for item in accepted
        ],
        'jumpers': [
            [jumper.name, [jumper.start.slot, jumper.start.terminal],
             [jumper.end.slot, jumper.end.terminal], jumper.conductance]
            for jumper in request.jumpers
        ],
        'injections': [
            [[endpoint.slot, endpoint.terminal], amount]
            for endpoint, amount in request.injections
        ],
        'feasible': result.feasible,
        'jumper_currents': None if result.jumper_currents is None else list(result.jumper_currents),
        'dissipation': None if result.dissipation is None else list(result.dissipation),
    }
    with write_transaction(db):
        report_id = store.next_report_id()
        body['report_id'] = report_id
        body_bytes = encode_report(body)
        receipt = {
            'version': 2,
            'report_id': report_id,
            'body_sha256': sha256(body_bytes).hexdigest(),
        }
        store.save_report(StoredCoupledReport(report_id, body_bytes, encode_receipt(receipt)))
    return LocalReport(report_id, body, receipt)
