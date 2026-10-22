"""Small, dependency-free formatting helpers used by the dashboard and JSON CLI."""

from __future__ import annotations

import math
from collections.abc import Sequence

_BYTE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
_SPARK_UNICODE = "▁▂▃▄▅▆▇█"
_SPARK_ASCII = "._-=+*#@"


def format_bytes(value: float | None) -> str:
    """Format a byte count with binary units (1 KiB = 1024 B)."""

    if value is None or not math.isfinite(value):
        return "n/a"

    value = max(0.0, float(value))
    if value < 1024:
        return f"{int(value)} B"

    for unit in _BYTE_UNITS[1:]:
        value /= 1024.0
        if value < 1024 or unit == _BYTE_UNITS[-1]:
            return f"{value:.1f} {unit}"

    return f"{value:.1f} PiB"  # pragma: no cover - loop always returns


def format_duration(seconds: float | None) -> str:
    """Format seconds as a compact human-readable duration."""

    if seconds is None or not math.isfinite(seconds):
        return "n/a"

    total = int(max(0, seconds))
    days, remainder = divmod(total, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, secs = divmod(remainder, 60)

    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_percent(value: float | None, digits: int = 1) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    return f"{value:.{digits}f}%"


def format_load(value: float | None) -> str:
    return "n/a" if value is None or not math.isfinite(value) else f"{value:.2f}"


def format_rate(value: float | None) -> str:
    """Format a bytes-per-second rate."""

    if value is None or not math.isfinite(value):
        return "n/a"
    return f"{format_bytes(value)}/s"


def format_frequency(khz: int | None) -> str:
    """Format a frequency expressed in kHz."""

    if khz is None or khz < 0:
        return "n/a"
    if khz >= 1_000_000:
        return f"{khz / 1_000_000:.2f} GHz"
    if khz >= 1_000:
        return f"{khz / 1_000:.0f} MHz"
    return f"{khz} kHz"


def format_sparkline(
    values: Sequence[float | None],
    width: int,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
    ascii_bars: bool = False,
) -> str:
    """Render the most recent values as a fixed-width sparkline.

    Missing values become gaps. When a series is shorter than the requested
    width, it is right-aligned so the newest sample stays on the right.
    """

    if width <= 0:
        return ""

    window = list(values)[-width:]
    if not window:
        return " " * width

    numeric = [
        value
        for value in window
        if value is not None and math.isfinite(value)
    ]
    if not numeric:
        return " " * width

    low = minimum
    high = maximum if maximum is not None else max(numeric)
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        high = low + 1.0

    characters = _SPARK_ASCII if ascii_bars else _SPARK_UNICODE
    spark: list[str] = []
    for value in window:
        if value is None or not math.isfinite(value):
            spark.append(" ")
            continue
        ratio = max(0.0, min(1.0, (value - low) / (high - low)))
        index = round(ratio * (len(characters) - 1))
        spark.append(characters[index])

    return " " * (width - len(window)) + "".join(spark)
