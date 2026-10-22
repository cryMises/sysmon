from __future__ import annotations

import math

import pytest

from sysmon.formatting import (
    format_bytes,
    format_duration,
    format_load,
    format_percent,
    format_rate,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "n/a"),
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KiB"),
        (1536, "1.5 KiB"),
        (8 * 1024**3, "8.0 GiB"),
        (-5, "0 B"),
    ],
)
def test_format_bytes(value: int | None, expected: str) -> None:
    assert format_bytes(value) == expected


def test_format_bytes_rejects_non_finite() -> None:
    assert format_bytes(math.nan) == "n/a"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, "n/a"),
        (0, "0s"),
        (59, "59s"),
        (60, "1m 0s"),
        (3661, "1h 1m"),
        (86_400, "1d 0h 0m"),
        (90_061, "1d 1h 1m"),
    ],
)
def test_format_duration(seconds: float | None, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_format_percent_and_load() -> None:
    assert format_percent(None) == "n/a"
    assert format_percent(42.345) == "42.3%"
    assert format_percent(42.345, digits=0) == "42%"
    assert format_load(None) == "n/a"
    assert format_load(1.234) == "1.23"


def test_format_rate() -> None:
    assert format_rate(None) == "n/a"
    assert format_rate(0) == "0 B/s"
    assert format_rate(1536) == "1.5 KiB/s"
    assert format_rate(2 * 1024**2) == "2.0 MiB/s"
