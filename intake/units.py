"""Normalize exact instrument conductance while retaining the raw input."""

from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType


SIEMENS_SCALES = MappingProxyType({'S': Fraction(1), 'mS': Fraction(1, 1000)})


@dataclass(frozen=True)
class Conductance:
    raw_value: int | str
    unit: str
    si: Fraction


def parse_rational(value: object, field: str) -> Fraction:
    if type(value) is not int and not isinstance(value, str):
        raise ValueError(f'{field} requires an integer or rational text')
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f'invalid {field}: {value!r}') from error


def rational_text(value: Fraction) -> str:
    return f'{value.numerator}/{value.denominator}'


def parse_conductance(value: object, unit: object) -> Conductance:
    if not isinstance(unit, str) or unit not in SIEMENS_SCALES:
        raise ValueError(f'unknown conductance unit {unit!r}')
    exact = parse_rational(value, 'conductance')
    if exact < 0:
        raise ValueError('conductance must be nonnegative')
    return Conductance(value, unit, exact * SIEMENS_SCALES[unit])
