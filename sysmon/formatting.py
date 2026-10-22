"""Small, dependency-free formatting helpers used by the dashboard and JSON CLI."""

from __future__ import annotations

import math

_BYTE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")


def format_bytes(value: int | float | None) -> str:
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
