"""Canonical V1 encoding for the saved report and its receipt."""

import json
from dataclasses import dataclass
from fractions import Fraction

from intake.units import rational_text


@dataclass(frozen=True)
class LocalReport:
    report_id: int
    body: dict
    receipt: dict


def _encode_fraction(value: object) -> str:
    if isinstance(value, Fraction):
        return rational_text(value)
    raise TypeError(f'cannot encode {type(value).__name__} in a local report')


def _encode(record: dict) -> bytes:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      default=_encode_fraction).encode('utf-8')


def _decode(payload: bytes) -> dict:
    record = json.loads(payload.decode('utf-8'))
    if not isinstance(record, dict) or type(record.get('version')) is not int or record['version'] != 1:
        raise ValueError('unsupported local report record version')
    return record


def encode_report(body: dict) -> bytes:
    return _encode(body)


def decode_report(payload: bytes) -> dict:
    body = _decode(payload)
    for key in ('total_dissipation', 'source_power'):
        body[key] = Fraction(body[key])
    numeric_fields = {
        'clamps': ('voltage',),
        'potentials': ('voltage', 'net_current'),
        'supplies': ('current',),
        'branches': ('conductance', 'current', 'dissipation'),
    }
    for section, fields in numeric_fields.items():
        for row in body[section]:
            for field in fields:
                row[field] = Fraction(row[field])
    return body


def encode_receipt(receipt: dict) -> bytes:
    return _encode(receipt)


def decode_receipt(payload: bytes) -> dict:
    return _decode(payload)


COUPLED_VERSION = 2


def _decode_coupled(payload: bytes) -> dict:
    record = json.loads(payload.decode('utf-8'))
    if not isinstance(record, dict) or type(record.get('version')) is not int or record['version'] != COUPLED_VERSION:
        raise ValueError('unsupported cross-fixture report record version')
    return record


def _ratio(value: object) -> Fraction:
    if not isinstance(value, str):
        raise ValueError('cross-fixture record values must be rational text')
    return Fraction(value)


def decode_coupled_report(payload: bytes) -> dict:
    body = _decode_coupled(payload)
    body['feasible'] = bool(body['feasible'])
    if body['jumper_currents'] is not None:
        body['jumper_currents'] = [_ratio(value) for value in body['jumper_currents']]
    if body['dissipation'] is not None:
        body['dissipation'] = [_ratio(value) for value in body['dissipation']]
    body['jumpers'] = [
        [name, list(start), list(end), _ratio(value)]
        for name, start, end, value in body['jumpers']
    ]
    body['injections'] = [[list(endpoint), _ratio(value)] for endpoint, value in body['injections']]
    return body


def decode_coupled_receipt(payload: bytes) -> dict:
    return _decode_coupled(payload)
