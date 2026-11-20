"""Equivalence of the original submission and an instrument retransmission."""

from collections.abc import Iterable
from fractions import Fraction

from intake.readings import Reading


def submission_key(
    bench_id: int, source: str, readings: Iterable[Reading],
) -> tuple[int, str, tuple[tuple[str, Fraction], ...]]:
    values = tuple(sorted((reading.branch, reading.conductance.si) for reading in readings))
    return bench_id, source, values
