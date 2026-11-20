"""Materialize the exact, coverage-checked reading set for a fixture revision."""

from sqlite3 import Connection

from analysis.response import terminal_response
from fixture.store import FixtureStore
from fixture.terminals import Terminal, resolve_terminal
from fixture.topology import ordered_items
from intake.store import IntakeStore
from lab import write_transaction
from report.piece import encode_terminal_piece
from revision.coverage import require_complete_coverage
from revision.store import FrozenBranchReading, RevisionStore


def freeze(db: Connection, revision_id: int) -> int:
    revisions = RevisionStore(db)
    with write_transaction(db):
        revision = revisions.load_revision(revision_id)
        original = revisions.find_freeze(revision_id)
        if original is not None:
            return original
        bench = FixtureStore(db).load_bench(revision.bench_id)
        coverage = require_complete_coverage(bench.topology, dict(revision.reading_refs))
        sources = IntakeStore(db).load_readings(ref for _, ref in coverage)
        frozen = []
        for branch, ref in coverage:
            reading = sources[ref]
            value = reading.conductance
            frozen.append(FrozenBranchReading(branch, ref, reading.source, value.raw_value, value.unit, value.si))
        freeze_id = revisions.save_freeze(revision_id, tuple(frozen))
    return freeze_id


def _select_terminals(bench, rows: object) -> tuple[Terminal, ...]:
    available = {terminal.name: terminal for terminal in bench.terminals}
    selected = []
    seen = set()
    for value in ordered_items(rows, 'terminal piece terminals'):
        terminal = resolve_terminal(available, value)
        if terminal.name in seen:
            raise ValueError(f'duplicate terminal {terminal.name!r} in terminal piece')
        selected.append(terminal)
        seen.add(terminal.name)
    if not selected:
        raise ValueError('terminal piece requires at least one registered terminal')
    return tuple(selected)


def export_terminal_piece(db: Connection, freeze_id: int, terminals: object) -> bytes:
    """Return the fixed UTF-8 JSON terminal piece for ``freeze_id`` and ``terminals``."""
    try:
        frozen = RevisionStore(db).load_frozen(freeze_id)
    except KeyError:
        raise ValueError(f'unknown freeze {freeze_id!r}') from None
    bench = FixtureStore(db).load_bench(frozen.bench_id)
    chosen = _select_terminals(bench, terminals)
    conductance = {reading.branch: reading.si for reading in frozen.readings}
    response = terminal_response(bench.topology, conductance, chosen)
    return encode_terminal_piece(
        bench.experiment, bench.name, frozen.revision_id, frozen.freeze_id,
        tuple(terminal.name for terminal in chosen), response.matrix, response.islands,
    )
