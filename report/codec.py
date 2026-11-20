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
