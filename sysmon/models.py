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
class CpuClusterStats:
    """One cpufreq policy, usually a big.LITTLE CPU cluster."""

    label: str
    current_khz: int | None = None
    min_khz: int | None = None
    max_khz: int | None = None
    source: str = "sysfs cpufreq"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "current_khz": self.current_khz,
            "min_khz": self.min_khz,
            "max_khz": self.max_khz,
            "source": self.source,
        }


@dataclass(frozen=True)
class CpuStats:
    load: LoadAverage = LoadAverage()
    usage_percent: float | None = None
    cores: float | None = None
    source: str = "unavailable"
    clusters: tuple[CpuClusterStats, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "load_1m": self.load.one,
            "load_5m": self.load.five,
            "load_15m": self.load.fifteen,
            "usage_percent": _rounded(self.usage_percent),
            "cores": self.cores,
            "clusters": [cluster.to_dict() for cluster in self.clusters],
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
class NetworkInterfaceStats:
    name: str
    rx_bytes: int
    tx_bytes: int
    rx_rate: float | None = None
    tx_rate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "rx_bytes": self.rx_bytes,
            "tx_bytes": self.tx_bytes,
            "rx_bytes_per_sec": _rounded(self.rx_rate),
            "tx_bytes_per_sec": _rounded(self.tx_rate),
        }


@dataclass(frozen=True)
class NetworkStats:
    rx_bytes: int
    tx_bytes: int
    rx_rate: float | None = None
    tx_rate: float | None = None
    interfaces: int = 0
    source: str = "unavailable"
    interface_details: tuple[NetworkInterfaceStats, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rx_bytes": self.rx_bytes,
            "tx_bytes": self.tx_bytes,
            "rx_bytes_per_sec": _rounded(self.rx_rate),
            "tx_bytes_per_sec": _rounded(self.tx_rate),
            "interfaces": self.interfaces,
            "interface_details": [
                interface.to_dict() for interface in self.interface_details
            ],
            "source": self.source,
        }


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    command: str
    cpu_percent: float | None = None
    memory_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "command": self.command,
            "cpu_percent": _rounded(self.cpu_percent),
            "memory_bytes": self.memory_bytes,
        }


@dataclass(frozen=True)
class ProcessStats:
    total: int | None = None
    running: int | None = None
    top: tuple[ProcessInfo, ...] = ()
    source: str = "unavailable"
    sort: str = "cpu"
    limit: int = 5
    filter: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "running": self.running,
            "top": [process.to_dict() for process in self.top],
            "source": self.source,
            "sort": self.sort,
            "limit": self.limit,
            "filter": self.filter,
        }


@dataclass(frozen=True)
class BatteryStats:
    present: bool = True
    percentage: float | None = None
    status: str | None = None
    plugged: str | None = None
    temperature_c: float | None = None
    health: str | None = None
    technology: str | None = None
    voltage_mv: int | None = None
    current_ua: int | None = None
    source: str = "termux-battery-status"
    current_average_ua: int | None = None
    charge_counter_uah: int | None = None
    cache_age_seconds: float | None = None

    @property
    def power_w(self) -> float | None:
        """Approximate instantaneous battery power in watts."""

        current = self.current_ua
        if current is None:
            current = self.current_average_ua
        if self.voltage_mv is None or current is None:
            return None
        return abs(self.voltage_mv * current) / 1_000_000_000.0

    @property
    def time_remaining_seconds(self) -> float | None:
        """Estimate discharge time from charge counter and current.

        The battery API does not expose a full-charge counter, so charging
        time is intentionally unavailable.
        """

        if (self.status or "").upper() != "DISCHARGING":
            return None
        if not self.charge_counter_uah or self.charge_counter_uah <= 0:
            return None
        current = self.current_ua or self.current_average_ua
        if not current:
            return None
        return self.charge_counter_uah / abs(current) * 3600.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "percentage": _rounded(self.percentage),
            "status": self.status,
            "plugged": self.plugged,
            "temperature_c": _rounded(self.temperature_c),
            "health": self.health,
            "technology": self.technology,
            "voltage_mv": self.voltage_mv,
            "current_ua": self.current_ua,
            "current_average_ua": self.current_average_ua,
            "charge_counter_uah": self.charge_counter_uah,
            "power_w": _rounded(self.power_w),
            "time_remaining_seconds": (
                round(self.time_remaining_seconds)
                if self.time_remaining_seconds is not None
                else None
            ),
            "cache_age_seconds": _rounded(self.cache_age_seconds),
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
    network: NetworkStats | None
    processes: ProcessStats | None
    warnings: tuple[str, ...]
    hostname: str
    os_name: str
    machine: str
    battery: BatteryStats | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
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
            "network": self.network.to_dict() if self.network else None,
            "processes": self.processes.to_dict() if self.processes else None,
            "battery": self.battery.to_dict() if self.battery else None,
            "warnings": list(self.warnings),
        }
        return data


@dataclass(frozen=True)
class TrendSample:
    """The compact metrics retained for watch-mode sparklines."""

    timestamp: float
    cpu_percent: float | None = None
    memory_percent: float | None = None
    rx_rate: float | None = None
    tx_rate: float | None = None
    battery_percent: float | None = None

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot) -> TrendSample:
        return cls(
            timestamp=snapshot.timestamp,
            cpu_percent=snapshot.cpu.usage_percent if snapshot.cpu else None,
            memory_percent=(
                snapshot.memory.used_percent if snapshot.memory else None
            ),
            rx_rate=snapshot.network.rx_rate if snapshot.network else None,
            tx_rate=snapshot.network.tx_rate if snapshot.network else None,
            battery_percent=(
                snapshot.battery.percentage if snapshot.battery else None
            ),
        )


@dataclass(frozen=True)
class MetricThreshold:
    warning: float
    critical: float


@dataclass(frozen=True)
class Thresholds:
    cpu: MetricThreshold = MetricThreshold(75.0, 90.0)
    memory: MetricThreshold = MetricThreshold(80.0, 92.0)
    disk: MetricThreshold = MetricThreshold(85.0, 95.0)
    battery: MetricThreshold = MetricThreshold(30.0, 15.0)


def _percent(used: int | None, total: int | None) -> float | None:
    if used is None or total is None or total <= 0:
        return None
    return max(0.0, min(100.0, used / total * 100.0))


def _rounded(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None
