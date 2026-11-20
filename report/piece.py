"""Fixed terminal pieces carried from a station to the cross-fixture centre.

A piece holds only what the centre needs: the experiment and bench identity,
the exact revision and freeze numbers, the ordered public terminals and the
exact reduced terminal response.  Internal nodes, branches and the original
measurement detail stay in the station database.
"""

import json
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256

from fixture.topology import require_name
from intake.units import parse_rational, rational_text
from lab import is_record_id


PIECE_VERSION = 2


@dataclass(frozen=True)
class TerminalPiece:
    experiment: str
    bench_name: str
    revision_id: int
    freeze_id: int
    terminals: tuple[str, ...]
    matrix: tuple[tuple[Fraction, ...], ...]
    islands: tuple[tuple[int, ...], ...]
    payload: bytes
    sha256: str


def _matrix_text(matrix: tuple[tuple[Fraction, ...], ...]) -> list[list[str]]:
    return [[rational_text(value) for value in row] for row in matrix]


def encode_terminal_piece(
    experiment: str, bench_name: str, revision_id: int, freeze_id: int,
    terminals: tuple[str, ...], matrix: tuple[tuple[Fraction, ...], ...],
    islands: tuple[tuple[int, ...], ...],
) -> bytes:
    record = {
        'version': PIECE_VERSION,
        'experiment': experiment,
        'bench_name': bench_name,
        'revision_id': revision_id,
        'freeze_id': freeze_id,
        'terminals': list(terminals),
        'response': {
            'matrix': _matrix_text(matrix),
            'islands': [list(group) for group in islands],
        },
    }
    return json.dumps(record, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _load_json(payload: object) -> dict:
    if type(payload) is not bytes:
        raise ValueError('terminal piece must be bytes')
    try:
        text = payload.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError('terminal piece is not UTF-8') from error
    try:
        record = json.loads(text)
    except ValueError as error:
        raise ValueError('terminal piece is not valid JSON') from error
    if not isinstance(record, dict):
        raise ValueError('terminal piece must be a JSON object')
    return record


def _load_terminals(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError('terminal piece requires a nonempty ordered terminal list')
    names = []
    seen = set()
    for item in value:
        name = require_name(item, 'terminal piece terminal')
        if name in seen:
            raise ValueError(f'duplicate terminal {name!r} in terminal piece')
        names.append(name)
        seen.add(name)
    return tuple(names)


def _load_matrix(value: object, size: int) -> tuple[tuple[Fraction, ...], ...]:
    if not isinstance(value, list) or len(value) != size:
        raise ValueError('terminal response matrix does not cover the listed terminals')
    rows = []
    for row in value:
        if not isinstance(row, list) or len(row) != size:
            raise ValueError('terminal response matrix is not square')
        rows.append(tuple(parse_rational(item, 'terminal response entry') for item in row))
    return tuple(rows)


def _load_islands(value: object, size: int) -> tuple[tuple[int, ...], ...]:
    if not isinstance(value, list):
        raise ValueError('terminal response islands must be an ordered list')
    seen = set()
    groups = []
    for group in value:
        if not isinstance(group, list) or not group:
            raise ValueError('terminal response island must be a nonempty list')
        members = []
        for index in group:
            if type(index) is not int or not 0 <= index < size:
                raise ValueError('terminal response island index is out of range')
            if index in seen:
                raise ValueError('terminal response island repeats a terminal')
            seen.add(index)
            members.append(index)
        groups.append(tuple(members))
    if seen != set(range(size)):
        raise ValueError('terminal response islands do not cover the listed terminals')
    return tuple(groups)


def _check_passive(matrix: tuple[tuple[Fraction, ...], ...], islands: tuple[tuple[int, ...], ...]) -> None:
    size = len(matrix)
    for row in range(size):
        for column in range(size):
            if matrix[row][column] != matrix[column][row]:
                raise ValueError('terminal response matrix is not symmetric')
            if row != column and matrix[row][column] > 0:
                raise ValueError('terminal response matrix is not a passive network')
        if sum(matrix[row], Fraction(0)) != 0:
            raise ValueError('terminal response matrix does not conserve net current')
    group_of = {}
    for number, group in enumerate(islands):
        for index in group:
            group_of[index] = number
    for row in range(size):
        for column in range(size):
            if group_of[row] != group_of[column] and matrix[row][column] != 0:
                raise ValueError('terminal response couples distinct conducting islands')
    for group in islands:
        if len(group) == 1:
            continue
        members = set(group)
        neighbors = {index: set() for index in members}
        for row in group:
            for column in group:
                if row != column and matrix[row][column] < 0:
                    neighbors[row].add(column)
        reached = {group[0]}
        pending = [group[0]]
        while pending:
            for neighbor in neighbors[pending.pop()]:
                if neighbor not in reached:
                    reached.add(neighbor)
                    pending.append(neighbor)
        if reached != members:
            raise ValueError('terminal response island is not conducting')


def decode_terminal_piece(payload: object) -> TerminalPiece:
    """Validate fixed piece bytes and recover their exact rational response."""
    record = _load_json(payload)
    version = record.get('version')
    if type(version) is not int or version != PIECE_VERSION:
        raise ValueError('unsupported terminal piece version')
    experiment = require_name(record.get('experiment'), 'terminal piece experiment')
    bench_name = require_name(record.get('bench_name'), 'terminal piece bench name')
    revision_id = record.get('revision_id')
    freeze_id = record.get('freeze_id')
    if not is_record_id(revision_id):
        raise ValueError('terminal piece revision number is invalid')
    if not is_record_id(freeze_id):
        raise ValueError('terminal piece freeze number is invalid')
    terminals = _load_terminals(record.get('terminals'))
    response = record.get('response')
    if not isinstance(response, dict):
        raise ValueError('terminal piece response is missing')
    matrix = _load_matrix(response.get('matrix'), len(terminals))
    islands = _load_islands(response.get('islands'), len(terminals))
    _check_passive(matrix, islands)
    return TerminalPiece(
        experiment, bench_name, revision_id, freeze_id, terminals, matrix, islands,
        payload, sha256(payload).hexdigest(),
    )
