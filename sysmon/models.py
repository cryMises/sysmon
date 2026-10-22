"""Plain data models shared by collectors, the dashboard, and JSON output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class LoadAverage:
    """Kernel load averages. Values remain ``None`` when unavailable."""

    one: float | None = None
    five: float | None = None
    fifteen: float | None = None


@dataclass(frozen=True)
class CpuStats:
    load: LoadAverage = LoadAverage()
    usage_percent: float | None = None
    cores: int | None = None
    source: str = "unavailable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "load_1m": self.load.one,
            "load_5m": self.load.five,
            "load_15m": self.load.fifteen,
            "usage_percent": _rounded(self.usage_percent),
            "cores": self.cores,
            "source": self.source,
        }


@dataclass(frozen=True)
class MemoryStats:
    total_bytes: int | None = None
    used_bytes: int | None = None
    available_bytes: int | None = None
    free_bytes: int | None = None
    swap_total_bytes: int | None = None
    swap_used_bytes: int | None = None
    source: str = "unavailable"

    @property
    def used_percent(self) -> float | None:
        return _percent(self.used_bytes, self.total_bytes)

    @property
    def swap_percent(self) -> float | None:
        return _percent(self.swap_used_bytes, self.swap_total_bytes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_bytes": self.total_bytes,
            "used_bytes": self.used_bytes,
            "available_bytes": self.available_bytes,
            "free_bytes": self.free_bytes,
            "used_percent": _rounded(self.used_percent),
            "swap_total_bytes": self.swap_total_bytes,
            "swap_used_bytes": self.swap_used_bytes,
            "swap_percent": _rounded(self.swap_percent),
            "source": self.source,
        }


@dataclass(frozen=True)
class DiskStats:
    path: str
    total_bytes: int | None = None
    used_bytes: int | None = None
    free_bytes: int | None = None
    source: str = "unavailable"

    @property
    def used_percent(self) -> float | None:
        return _percent(self.used_bytes, self.total_bytes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "total_bytes": self.total_bytes,
            "used_bytes": self.used_bytes,
            "free_bytes": self.free_bytes,
            "used_percent": _rounded(self.used_percent),
            "source": self.source,
        }


@dataclass(frozen=True)
class UptimeStats:
    seconds: float
    source: str = "unavailable"

    def to_dict(self, now: float) -> dict[str, Any]:
        boot_time = datetime.fromtimestamp(now - self.seconds).astimezone()
        return {
            "seconds": round(self.seconds, 1),
            "boot_time": boot_time.isoformat(timespec="seconds"),
            "source": self.source,
        }


@dataclass(frozen=True)
class Snapshot:
    """A complete, immutable sample of the host."""

    timestamp: float
    cpu: CpuStats | None
    memory: MemoryStats | None
    disks: tuple[DiskStats, ...]
    uptime: UptimeStats | None
    warnings: tuple[str, ...]
    hostname: str
    os_name: str
    machine: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": datetime.fromtimestamp(self.timestamp)
            .astimezone()
            .isoformat(timespec="seconds"),
            "hostname": self.hostname,
            "os": self.os_name,
            "machine": self.machine,
            "cpu": self.cpu.to_dict() if self.cpu else None,
            "memory": self.memory.to_dict() if self.memory else None,
            "disks": [disk.to_dict() for disk in self.disks],
            "uptime": self.uptime.to_dict(self.timestamp) if self.uptime else None,
            "warnings": list(self.warnings),
        }


def _percent(used: int | None, total: int | None) -> float | None:
    if used is None or total is None or total <= 0:
        return None
    return max(0.0, min(100.0, used / total * 100.0))


def _rounded(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None
