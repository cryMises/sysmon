"""Read-only collectors for CPU, memory, disks, and uptime.

The primary sources are Linux ``/proc`` and the Python standard library. If
those are unavailable, a few read-only command-line tools are tried as
fallbacks. Every failure is reported as a warning rather than crashing the
dashboard.
"""

from __future__ import annotations

import json
import math
import os
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from .models import (
    BatteryStats,
    ContainerStats,
    CpuClusterStats,
    CpuStats,
    DiskStats,
    DockerStats,
    LoadAverage,
    MemoryStats,
    NetworkInterfaceStats,
    NetworkStats,
    ProcessInfo,
    ProcessStats,
    Snapshot,
    UptimeStats,
)

CommandRunner = Callable[[Sequence[str]], str]
MAX_TOP_PROCESSES = 5


class MetricUnavailable(RuntimeError):
    """Raised when a metric cannot be read from any available source."""


@dataclass(frozen=True)
class CpuTimes:
    idle: int
    total: int


def parse_loadavg(text: str) -> LoadAverage:
    fields = text.split()
    if len(fields) < 3:
        raise MetricUnavailable(f"invalid loadavg data: {text.strip()!r}")
    try:
        one, five, fifteen = (float(value) for value in fields[:3])
    except ValueError as exc:
        raise MetricUnavailable(f"invalid loadavg data: {text.strip()!r}") from exc
    if not all(math.isfinite(value) for value in (one, five, fifteen)):
        raise MetricUnavailable(f"invalid loadavg data: {text.strip()!r}")
    return LoadAverage(one=one, five=five, fifteen=fifteen)


def parse_meminfo(text: str) -> MemoryStats:
    """Parse /proc/meminfo. Linux reports these values in KiB."""

    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        fields = raw.split()
        if not fields:
            continue
        try:
            values[key.strip()] = int(fields[0])
        except ValueError:
            continue

    total_kb = values.get("MemTotal")
    free_kb = values.get("MemFree")
    if total_kb is None or free_kb is None or total_kb <= 0:
        raise MetricUnavailable("/proc/meminfo does not contain MemTotal/MemFree")

    available_kb = values.get("MemAvailable")
    if available_kb is None:
        # Approximation for kernels older than 3.14, which lack MemAvailable.
        available_kb = (
            free_kb
            + values.get("Buffers", 0)
            + values.get("Cached", 0)
            + values.get("SReclaimable", 0)
            - values.get("Shmem", 0)
        )
    available_kb = max(0, min(total_kb, available_kb))
    swap_total_kb = max(0, values.get("SwapTotal", 0))
    swap_free_kb = max(0, values.get("SwapFree", 0))

    return MemoryStats(
        total_bytes=total_kb * 1024,
        used_bytes=(total_kb - available_kb) * 1024,
        available_bytes=available_kb * 1024,
        free_bytes=free_kb * 1024,
        swap_total_bytes=swap_total_kb * 1024,
        swap_used_bytes=max(0, swap_total_kb - swap_free_kb) * 1024,
        source="/proc/meminfo",
    )


def parse_free_bytes(text: str) -> MemoryStats:
    """Parse ``free -b`` output as a fallback for systems without /proc."""

    lines = [line.split() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise MetricUnavailable("free -b returned no memory rows")

    header = lines[0]
    rows = {
        row[0].rstrip(":"): row
        for row in lines[1:]
        if row and row[0].rstrip(":") in {"Mem", "Swap"}
    }
    mem = rows.get("Mem")
    if mem is None:
        raise MetricUnavailable("free -b returned no Mem row")

    def column(row: list[str], name: str) -> int | None:
        try:
            # The first header label ("total") aligns with row[1]; row[0] is
            # the "Mem:"/"Swap:" label.
            return int(row[header.index(name) + 1])
        except (ValueError, IndexError):
            return None

    total = column(mem, "total")
    used = column(mem, "used")
    free = column(mem, "free")
    if total is None or used is None:
        raise MetricUnavailable("free -b returned incomplete Mem data")

    available = column(mem, "available")
    if available is None:
        buff_cache = column(mem, "buff/cache") or 0
        available = (free or 0) + buff_cache if "buff/cache" in header else total - used
    available = max(0, min(total, available))

    swap = rows.get("Swap")
    swap_total = column(swap, "total") if swap else 0
    swap_used = column(swap, "used") if swap else 0

    return MemoryStats(
        total_bytes=total,
        used_bytes=max(0, total - available),
        available_bytes=available,
        free_bytes=free,
        swap_total_bytes=swap_total or 0,
        swap_used_bytes=swap_used or 0,
        source="free -b",
    )


def parse_cpu_stat(text: str) -> CpuTimes:
    """Return aggregate idle/total jiffies from the first ``cpu`` line."""

    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] != "cpu":
            continue
        try:
            values = [int(value) for value in fields[1:]]
        except ValueError as exc:
            raise MetricUnavailable("invalid /proc/stat CPU counters") from exc
        if len(values) < 4:
            raise MetricUnavailable("/proc/stat CPU line has too few counters")
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values[:8])
        return CpuTimes(idle=idle, total=total)

    raise MetricUnavailable("/proc/stat has no aggregate cpu line")


def calculate_cpu_usage(before: CpuTimes, after: CpuTimes) -> float | None:
    total_delta = after.total - before.total
    idle_delta = after.idle - before.idle
    if total_delta <= 0:
        return None
    usage = (total_delta - idle_delta) / total_delta * 100.0
    return max(0.0, min(100.0, usage))


def calculate_cpu_usage_since_boot(times: CpuTimes) -> float | None:
    """Average CPU usage since boot; used when delta sampling is unavailable."""

    if times.total <= 0:
        return None
    usage = (times.total - times.idle) / times.total * 100.0
    return max(0.0, min(100.0, usage))


def calculate_process_cpu_usage(
    before: Mapping[int, int] | None,
    after: Mapping[int, int] | None,
    elapsed: float,
    cores: float | None,
    clock_ticks: int = 100,
) -> float | None:
    """Estimate CPU usage from per-process utime/stime deltas.

    Some containers (notably PRoot on Android) expose a frozen ``/proc/stat``
    while still accounting CPU time for individual processes. Summing the
    deltas for processes present in both samples recovers a live usage value.
    """

    if (
        not before
        or not after
        or elapsed <= 0
        or not cores
        or cores <= 0
        or clock_ticks <= 0
    ):
        return None

    common_pids = set(before).intersection(after)
    if not common_pids:
        return None

    delta_ticks = sum(max(0, after[pid] - before[pid]) for pid in common_pids)
    usage = delta_ticks / clock_ticks / elapsed / cores * 100.0
    return max(0.0, min(100.0, usage))


def calculate_process_cpu_rates(
    before: Mapping[int, int] | None,
    after: Mapping[int, int] | None,
    elapsed: float,
    clock_ticks: int = 100,
) -> dict[int, float]:
    """Return per-PID CPU percentages for processes present in both samples.

    Values are relative to one CPU core, matching the convention used by
    ``ps`` and ``top``; a busy multi-threaded process can exceed 100%.
    """

    if not before or not after or elapsed <= 0 or clock_ticks <= 0:
        return {}
    common_pids = set(before).intersection(after)
    if not common_pids:
        return {}
    return {
        pid: max(0.0, after[pid] - before[pid]) / clock_ticks / elapsed * 100.0
        for pid in common_pids
    }


def _clock_ticks() -> int:
    """Return the kernel's clock tick rate, defaulting to the Linux norm."""

    try:
        ticks = int(os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError):
        return 100
    return ticks if ticks > 0 else 100


def parse_uptime(text: str) -> float:
    fields = text.split()
    if not fields:
        raise MetricUnavailable("empty /proc/uptime")
    try:
        seconds = float(fields[0])
    except ValueError as exc:
        raise MetricUnavailable(f"invalid /proc/uptime: {text.strip()!r}") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise MetricUnavailable(f"invalid /proc/uptime: {text.strip()!r}")
    return seconds


def parse_boot_time(text: str) -> float:
    """Parse the timestamp printed by ``uptime -s``."""

    raw = text.strip()
    if not raw:
        raise MetricUnavailable("uptime -s returned no timestamp")
    try:
        booted = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise MetricUnavailable(f"invalid uptime -s timestamp: {raw!r}") from exc
    if booted.tzinfo is None:
        booted = booted.astimezone()
    return booted.timestamp()


def parse_df_k(text: str, path: str) -> DiskStats:
    """Parse the final row of POSIX ``df -Pk`` output."""

    rows = [line.split() for line in text.splitlines()[1:] if line.strip()]
    if not rows:
        raise MetricUnavailable("df -Pk returned no filesystem row")
    row = rows[-1]
    if len(row) < 4:
        raise MetricUnavailable("df -Pk returned incomplete filesystem data")
    try:
        total = int(row[1]) * 1024
        used = int(row[2]) * 1024
        free = int(row[3]) * 1024
    except ValueError as exc:
        raise MetricUnavailable("df -Pk returned non-numeric sizes") from exc
    if total <= 0:
        raise MetricUnavailable("df -Pk reported zero total space")
    return DiskStats(
        path=path,
        total_bytes=total,
        used_bytes=max(0, used),
        free_bytes=max(0, free),
        source="df -Pk",
    )


def parse_os_release(text: str) -> str | None:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values.get("PRETTY_NAME") or values.get("NAME") or None


def parse_termux_battery(text: str) -> BatteryStats:
    """Parse JSON returned by ``termux-battery-status``."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MetricUnavailable("invalid battery JSON") from exc
    if not isinstance(data, dict):
        raise MetricUnavailable("battery JSON is not an object")

    present = data.get("present", True)
    if not isinstance(present, bool):
        raise MetricUnavailable("battery 'present' is not a boolean")
    if not present:
        return BatteryStats(present=False)

    percentage = _optional_float(data.get("percentage"))
    if percentage is None:
        level = _optional_float(data.get("level"))
        scale = _optional_float(data.get("scale"))
        if level is not None and scale is not None and scale > 0:
            percentage = level / scale * 100.0
    if percentage is not None:
        percentage = max(0.0, min(100.0, percentage))

    status = _optional_text(data.get("status"))
    plugged = _optional_text(data.get("plugged"))
    temperature = _optional_float(data.get("temperature"))
    health = _optional_text(data.get("health"))
    technology = _optional_text(data.get("technology"))
    if all(
        value is None
        for value in (percentage, status, plugged, temperature, health, technology)
    ):
        raise MetricUnavailable("battery JSON contains no status fields")

    return BatteryStats(
        percentage=percentage,
        status=status,
        plugged=plugged,
        temperature_c=temperature,
        health=health,
        technology=technology,
        voltage_mv=_optional_int(data.get("voltage")),
        current_ua=_optional_int(data.get("current")),
        current_average_ua=_optional_int(data.get("current_average")),
        charge_counter_uah=_optional_int(data.get("charge_counter")),
    )


def parse_cgroup_cpu_max(text: str) -> float | None:
    """Parse a cgroup v2 ``cpu.max`` quota into an effective core count.

    Returns ``None`` when the quota is unlimited (``max``).
    """

    fields = text.split()
    if len(fields) < 2:
        raise MetricUnavailable("invalid cgroup cpu.max")
    quota, period = fields[0], fields[1]
    if quota == "max":
        return None
    try:
        quota_value = int(quota)
        period_value = int(period)
    except ValueError as exc:
        raise MetricUnavailable("invalid cgroup cpu.max") from exc
    if quota_value <= 0 or period_value <= 0:
        raise MetricUnavailable("invalid cgroup cpu.max")
    return quota_value / period_value


def parse_cgroup_cpu_usage(text: str) -> int | None:
    """Return ``usage_usec`` from a cgroup v2 ``cpu.stat`` file."""

    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 2 or fields[0] != "usage_usec":
            continue
        try:
            return max(0, int(fields[1]))
        except ValueError as exc:
            raise MetricUnavailable("invalid cgroup cpu.stat") from exc
    return None


def parse_cgroup_memory_limit(text: str) -> int | None:
    """Parse a cgroup v2 memory limit; ``None`` means unlimited."""

    raw = text.strip()
    if not raw or raw == "max":
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise MetricUnavailable("invalid cgroup memory limit") from exc
    return value if value > 0 else None


def parse_cgroup_memory_current(text: str) -> int:
    """Parse a cgroup v2 current-usage value in bytes."""

    raw = text.strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise MetricUnavailable("invalid cgroup memory usage") from exc
    if value < 0:
        raise MetricUnavailable("invalid cgroup memory usage")
    return value


def _network_stats_from_entries(
    entries: list[tuple[str, int, int]], source: str
) -> NetworkStats:
    """Build network totals, preferring non-loopback interfaces."""

    non_loopback = [entry for entry in entries if entry[0] != "lo"]
    selected = sorted(non_loopback or entries, key=lambda entry: entry[0])
    return NetworkStats(
        rx_bytes=sum(entry[1] for entry in selected),
        tx_bytes=sum(entry[2] for entry in selected),
        interfaces=len(selected),
        interface_details=tuple(
            NetworkInterfaceStats(name=name, rx_bytes=rx, tx_bytes=tx)
            for name, rx, tx in selected
        ),
        source=source,
    )


def parse_net_dev(text: str) -> NetworkStats:
    """Parse /proc/net/dev and total all interfaces except loopback."""

    entries: list[tuple[str, int, int]] = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        interface, raw = line.split(":", 1)
        fields = raw.split()
        if len(fields) < 9:
            continue
        try:
            rx_bytes = int(fields[0])
            tx_bytes = int(fields[8])
        except ValueError:
            continue
        entries.append((interface.strip(), rx_bytes, tx_bytes))

    if not entries:
        raise MetricUnavailable("/proc/net/dev contains no interface rows")
    return _network_stats_from_entries(entries, "/proc/net/dev")


def parse_sysfs_net(net_root: Path) -> NetworkStats:
    """Read interface counters from ``/sys/class/net``.

    ``/proc/net/dev`` is restricted for unprivileged Android apps and in some
    containers, while sysfs counters often remain readable.
    """

    try:
        interfaces = sorted(net_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise MetricUnavailable(f"cannot list {net_root}: {exc}") from exc

    entries: list[tuple[str, int, int]] = []
    for interface in interfaces:
        statistics = interface / "statistics"
        try:
            rx_bytes = int(_read_text(statistics / "rx_bytes").strip())
            tx_bytes = int(_read_text(statistics / "tx_bytes").strip())
        except (OSError, ValueError):
            continue
        if rx_bytes < 0 or tx_bytes < 0:
            continue
        entries.append((interface.name, rx_bytes, tx_bytes))

    if not entries:
        raise MetricUnavailable(f"{net_root} contains no readable counters")
    return _network_stats_from_entries(entries, "sysfs")


def parse_ip_link_json(text: str) -> NetworkStats:
    """Parse ``ip -s -j link`` output (iproute2 JSON)."""

    try:
        links = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MetricUnavailable("ip returned invalid JSON") from exc
    if not isinstance(links, list):
        raise MetricUnavailable("ip returned an unexpected JSON document")

    entries: list[tuple[str, int, int]] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        name = link.get("ifname")
        stats = link.get("stats64") or link.get("stats")
        if not isinstance(name, str) or not isinstance(stats, dict):
            continue
        rx_bytes = _ip_stat_bytes(stats, "rx")
        tx_bytes = _ip_stat_bytes(stats, "tx")
        if rx_bytes is None or tx_bytes is None:
            continue
        entries.append((name, rx_bytes, tx_bytes))

    if not entries:
        raise MetricUnavailable("ip reported no interface counters")
    return _network_stats_from_entries(entries, "ip -s")


def _ip_stat_bytes(stats: dict[str, object], direction: str) -> int | None:
    section = stats.get(direction)
    if not isinstance(section, dict):
        return None
    try:
        value = int(section.get("bytes", -1))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def parse_android_netstats(text: str) -> NetworkStats:
    """Parse the parcel printed by ``service call netstats 13``.

    Android denies unprivileged apps access to ``/proc/net/dev`` and sysfs
    network counters, but its ``netstats`` binder service exposes device-wide
    totals. ``service`` prints the reply as a hex parcel.
    """

    words: list[int] = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        _, raw = line.split(":", 1)
        data = raw.split("'", 1)[0]
        words.extend(
            int(token, 16) for token in re.findall(r"\b[0-9a-fA-F]{8}\b", data)
        )

    if not words:
        raise MetricUnavailable("netstats returned no parcel data")

    exception = words[0]
    if exception:
        signed = exception - 2**32 if exception >= 2**31 else exception
        raise MetricUnavailable(f"netstats returned exception {signed}")

    # AIDL writes a presence flag for the nullable StatsResult, followed by the
    # parcelable's size (36 bytes) and four longs.
    size_index = 2 if len(words) >= 4 and words[1] == 1 else 1
    if len(words) < size_index + 9 or words[size_index] != 36:
        raise MetricUnavailable("netstats returned an unsupported response")

    values = words[size_index + 1 : size_index + 9]
    rx_bytes = values[0] | (values[1] << 32)
    tx_bytes = values[4] | (values[5] << 32)
    return NetworkStats(
        rx_bytes=rx_bytes,
        tx_bytes=tx_bytes,
        interfaces=0,
        source="android netstats",
    )


_PS_ROW = re.compile(
    r"^\s*(\d+)\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s+(\d+)\s+(.+?)\s*$"
)


def parse_ps_processes(
    text: str,
    limit: int = MAX_TOP_PROCESSES,
    *,
    sort_by: str = "cpu",
    filter_pattern: str | None = None,
) -> tuple[ProcessInfo, ...]:
    """Parse ``ps -eo pid=,pcpu=,rss=,comm=`` output.

    A filter is applied after parsing but before sorting and limiting, so the
    caller can show only matching processes without changing process counts.
    """

    pattern = re.compile(filter_pattern) if filter_pattern else None
    parsed: list[ProcessInfo] = []
    for line in text.splitlines():
        match = _PS_ROW.match(line)
        if not match:
            continue
        pid = int(match.group(1))
        cpu = float(match.group(2))
        if not math.isfinite(cpu):
            continue
        rss_kb = int(match.group(3))
        command = match.group(4).strip() or f"[{pid}]"
        if _is_ps_command(command):
            # The ps process itself often reports a misleading 100% CPU.
            continue
        parsed.append(
            ProcessInfo(
                pid=pid,
                command=command,
                cpu_percent=max(0.0, cpu),
                memory_bytes=max(0, rss_kb) * 1024,
            )
        )

    if not parsed:
        raise MetricUnavailable("ps returned no parsable process rows")
    selected = [
        process
        for process in parsed
        if pattern is None or pattern.search(process.command)
    ]
    return tuple(_sort_processes(selected, sort_by)[:limit])


_DOCKER_SIZE_UNITS = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


def parse_docker_size(text: str) -> int | None:
    """Parse a Docker human size such as ``369.4MiB`` into bytes."""

    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)\s*", text)
    if match is None:
        return None
    factor = _DOCKER_SIZE_UNITS.get(match.group(2).upper())
    if factor is None:
        return None
    return int(float(match.group(1)) * factor)


def _parse_docker_percent(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return float(value.strip().rstrip("%"))
    except ValueError:
        return None


def parse_docker_stats(text: str) -> DockerStats:
    """Parse ``docker stats --no-stream --format {{json .}}`` output.

    Malformed lines are skipped rather than failing the whole snapshot:
    one odd container row should not hide the rest of the host.
    """

    containers: list[ContainerStats] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        name = raw.get("Name")
        if not isinstance(name, str) or not name.strip():
            continue
        memory_bytes: int | None = None
        memory_limit_bytes: int | None = None
        usage = raw.get("MemUsage")
        if isinstance(usage, str) and "/" in usage:
            used_text, _, limit_text = usage.partition("/")
            memory_bytes = parse_docker_size(used_text)
            memory_limit_bytes = parse_docker_size(limit_text)
        containers.append(
            ContainerStats(
                name=name.strip().lstrip("/"),
                cpu_percent=_parse_docker_percent(raw.get("CPUPerc")),
                memory_bytes=memory_bytes,
                memory_limit_bytes=memory_limit_bytes,
            )
        )
    containers.sort(
        key=lambda container: container.memory_bytes or 0, reverse=True
    )
    return DockerStats(containers=tuple(containers))


def _sort_processes(
    processes: Sequence[ProcessInfo], sort_by: str
) -> list[ProcessInfo]:
    if sort_by == "pid":
        return sorted(processes, key=lambda process: process.pid)
    if sort_by == "mem":
        return sorted(
            processes,
            key=lambda process: (
                process.memory_bytes or -1,
                process.cpu_percent or -1,
                process.pid,
            ),
            reverse=True,
        )
    return sorted(
        processes,
        key=lambda process: (
            process.cpu_percent if process.cpu_percent is not None else -1.0,
            process.memory_bytes or 0,
            process.pid,
        ),
        reverse=True,
    )


def _is_ps_command(command: str) -> bool:
    fields = command.split(None, 1)
    return bool(fields) and fields[0].rsplit("/", 1)[-1] == "ps"


class SystemCollector:
    """Collect one read-only snapshot of the host.

    Parameters are injectable so the collectors can be tested without a real
    Linux host or external utilities.
    """

    def __init__(
        self,
        paths: Sequence[str | Path] = ("/",),
        *,
        proc_root: Path = Path("/proc"),
        sysfs_net: Path = Path("/sys/class/net"),
        android_service: Path = Path("/system/bin/service"),
        cgroup_root: Path = Path("/sys/fs/cgroup"),
        os_release: Path = Path("/etc/os-release"),
        cpu_freq_root: Path = Path("/sys/devices/system/cpu/cpufreq"),
        process_limit: int = MAX_TOP_PROCESSES,
        process_sort: str = "cpu",
        process_filter: str | None = None,
        full_command: bool = False,
        cpu_sample_seconds: float = 0.12,
        command_timeout: float = 2.0,
        battery_command: Sequence[str] | None = ("termux-battery-status",),
        battery_timeout: float = 5.0,
        battery_cache_seconds: float = 30.0,
        docker_command: Sequence[str] | None = (
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
        ),
        docker_timeout: float = 10.0,
        runner: CommandRunner | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.paths = tuple(Path(path) for path in paths) or (Path("/"),)
        self.proc_root = Path(proc_root)
        self.sysfs_net = Path(sysfs_net)
        self.android_service = Path(android_service)
        self.cgroup_root = Path(cgroup_root)
        self.os_release = Path(os_release)
        self.cpu_freq_root = Path(cpu_freq_root)
        if process_limit < 1:
            raise ValueError("process_limit must be at least 1")
        if process_sort not in {"cpu", "mem", "pid"}:
            raise ValueError("process_sort must be cpu, mem, or pid")
        self.process_limit = process_limit
        self.process_sort = process_sort
        self.process_filter = process_filter.strip() if process_filter else None
        self.full_command = full_command
        try:
            self._process_pattern = (
                re.compile(self.process_filter)
                if self.process_filter is not None
                else None
            )
        except re.error as exc:
            raise ValueError(
                f"process_filter is not a valid regular expression: {exc}"
            ) from exc
        self.cpu_sample_seconds = max(0.0, cpu_sample_seconds)
        self.command_timeout = command_timeout
        self.battery_command = tuple(battery_command) if battery_command else None
        self.battery_timeout = max(0.1, battery_timeout)
        self.battery_cache_seconds = max(0.0, battery_cache_seconds)
        self.docker_command = tuple(docker_command) if docker_command else None
        self.docker_timeout = max(0.1, docker_timeout)
        self.runner = runner
        self.clock = clock
        self.sleep = sleep
        self.monotonic = monotonic
        self._last_network: tuple[float, int, int, str] | None = None
        self._last_interfaces: (
            tuple[float, dict[str, tuple[int, int]], str] | None
        ) = None
        self._last_uptime: tuple[float, float, float, str] | None = None
        self._last_process_sample: (
            tuple[float, Mapping[int, int]] | None
        ) = None
        self._process_cpu_rates: dict[int, float] = {}
        self._battery_cache: tuple[float, BatteryStats | None, str | None] | None = None

    def collect(self, detailed: bool = False) -> Snapshot:
        warnings: list[str] = []
        cpu = self._collect_cpu(warnings, detailed=detailed)
        memory = self._collect_memory(warnings)
        disks = self._collect_disks(warnings)
        uptime = self._collect_uptime(warnings)
        network = self._collect_network(warnings) if detailed else None
        processes = self._collect_processes(warnings) if detailed else None
        battery = self._collect_battery(warnings)
        docker = self._collect_docker() if detailed else None

        return Snapshot(
            timestamp=self.clock(),
            cpu=cpu,
            memory=memory,
            disks=disks,
            uptime=uptime,
            network=network,
            processes=processes,
            warnings=tuple(warnings),
            hostname=platform.node().strip() or "unknown",
            os_name=self._read_os_name(),
            machine=platform.machine().strip() or "unknown",
            battery=battery,
            docker=docker,
        )

    def _collect_cpu(
        self, warnings: list[str], *, detailed: bool = False
    ) -> CpuStats:
        load = LoadAverage()
        load_source: str | None = None
        load_error: str | None = None
        try:
            load, load_source = self._read_load()
        except MetricUnavailable as exc:
            load_error = str(exc)

        cores = self._effective_cpu_cores()
        usage: float | None = None
        usage_source: str | None = None
        usage_error: str | None = None
        try:
            usage, usage_source = self._sample_cpu_usage(
                cores=cores, detailed=detailed
            )
        except (OSError, ValueError, MetricUnavailable) as exc:
            usage_error = str(exc)

        clusters = self._collect_cpu_frequencies()
        sources = [source for source in (load_source, usage_source) if source]
        if load_error and usage_error:
            warnings.append(
                f"CPU: load and usage unavailable ({load_error}; {usage_error})"
            )
        elif load_error:
            warnings.append(f"CPU load: {load_error}")
        elif usage_error:
            warnings.append(f"CPU usage: {usage_error}")

        return CpuStats(
            load=load,
            usage_percent=usage,
            cores=cores,
            clusters=clusters,
            source=" + ".join(sources) if sources else "unavailable",
        )

    def _collect_cpu_frequencies(self) -> tuple[CpuClusterStats, ...]:
        """Read per-policy CPU frequencies from cpufreq sysfs.

        Files may be absent on kernels or containers without cpufreq support;
        that is not an error, so this silently returns an empty tuple.
        """

        try:
            policies = sorted(
                (
                    path
                    for path in self.cpu_freq_root.iterdir()
                    if path.name.startswith("policy") and path.is_dir()
                ),
                key=_policy_sort_key,
            )
        except OSError:
            return ()

        clusters: list[CpuClusterStats] = []
        for policy in policies:
            current = _read_int_file(policy / "scaling_cur_freq")
            if current is None:
                continue
            minimum = _first_readable_int(
                policy,
                ("cpuinfo_min_freq", "scaling_min_freq"),
            )
            maximum = _first_readable_int(
                policy,
                ("cpuinfo_max_freq", "scaling_max_freq"),
            )
            cpus = _read_int_list(policy / "affected_cpus")
            clusters.append(
                CpuClusterStats(
                    label=_cpu_label(cpus) or policy.name,
                    current_khz=current,
                    min_khz=minimum,
                    max_khz=maximum,
                )
            )
        return tuple(clusters)

    def _read_load(self) -> tuple[LoadAverage, str]:
        loadavg_path = self.proc_root / "loadavg"
        proc_error: Exception | None = None
        try:
            return parse_loadavg(_read_text(loadavg_path)), "/proc/loadavg"
        except (OSError, ValueError, MetricUnavailable) as exc:
            proc_error = exc

        try:
            one, five, fifteen = os.getloadavg()
        except (OSError, AttributeError) as exc:
            raise MetricUnavailable(
                f"/proc/loadavg unavailable ({proc_error}); "
                f"os.getloadavg unavailable ({exc})"
            ) from exc
        return LoadAverage(one=one, five=five, fifteen=fifteen), "os.getloadavg"

    def _effective_cpu_cores(self) -> float | None:
        """Return host cores, capped by a finite cgroup CPU quota."""

        host = os.cpu_count()
        try:
            limit = parse_cgroup_cpu_max(
                _read_text(self._cgroup_dir() / "cpu.max")
            )
        except (OSError, ValueError, MetricUnavailable):
            limit = None
        if limit is None:
            return host
        if host:
            limit = min(limit, float(host))
        value = max(0.01, round(limit, 2))
        return int(value) if value.is_integer() else value

    def _cgroup_dir(self) -> Path:
        """Resolve the current cgroup v2 directory, falling back to the root."""

        try:
            content = _read_text(self.proc_root / "self" / "cgroup")
        except OSError:
            return self.cgroup_root

        for line in content.splitlines():
            fields = line.split(":", 2)
            if len(fields) != 3 or fields[0] != "0":
                continue
            relative = fields[2].strip()
            if not relative:
                continue
            candidate = self.cgroup_root / relative.lstrip("/")
            try:
                if candidate.is_dir():
                    return candidate
            except OSError:
                continue
        return self.cgroup_root

    def _read_cgroup_cpu_usage(self, cgroup_dir: Path) -> int | None:
        try:
            return parse_cgroup_cpu_usage(_read_text(cgroup_dir / "cpu.stat"))
        except (OSError, ValueError, MetricUnavailable):
            return None

    def _sample_cpu_usage(
        self,
        cores: float | None = None,
        *,
        detailed: bool = False,
    ) -> tuple[float | None, str | None]:
        """Sample CPU usage, preferring cgroup limits and process deltas.

        A readable cgroup v2 ``cpu.stat`` is the most accurate source inside a
        container. Otherwise ``/proc/stat`` is used; if those counters are
        frozen (notably under PRoot on Android), per-process ``utime``/``stime``
        deltas are summed before falling back to the average since boot.
        """

        self._process_cpu_rates = {}
        if self.cpu_sample_seconds <= 0:
            return None, None
        if cores is None:
            cores = self._effective_cpu_cores()

        cgroup_dir = self._cgroup_dir()
        cgroup_before = self._read_cgroup_cpu_usage(cgroup_dir)
        stat_path = self.proc_root / "stat"
        stat_error: Exception | None = None
        before: CpuTimes | None = None
        try:
            before = parse_cpu_stat(_read_text(stat_path))
        except (OSError, ValueError, MetricUnavailable) as exc:
            stat_error = exc

        process_before = self._read_process_cpu_ticks()
        started = self.monotonic()
        self.sleep(self.cpu_sample_seconds)
        elapsed = self.monotonic() - started
        sample_end = started + elapsed

        cgroup_after = self._read_cgroup_cpu_usage(cgroup_dir)
        if (
            cgroup_before is not None
            and cgroup_after is not None
            and cgroup_after >= cgroup_before
            and elapsed > 0
        ):
            cgroup_usage = (
                (cgroup_after - cgroup_before)
                / 1_000_000.0
                / elapsed
                / max(cores or 1.0, 0.01)
                * 100.0
            )
            if detailed:
                self._record_process_cpu_rates(
                    process_before,
                    self._read_process_cpu_ticks(),
                    elapsed,
                    sample_end,
                )
            return max(0.0, min(100.0, cgroup_usage)), "cgroup v2"

        after: CpuTimes | None = None
        if before is not None:
            try:
                after = parse_cpu_stat(_read_text(stat_path))
            except (OSError, ValueError, MetricUnavailable) as exc:
                stat_error = exc

        if before is not None and after is not None:
            usage = calculate_cpu_usage(before, after)
            if usage is not None:
                if detailed:
                    self._record_process_cpu_rates(
                        process_before,
                        self._read_process_cpu_ticks(),
                        elapsed,
                        sample_end,
                    )
                return usage, "/proc/stat"

        process_after = self._read_process_cpu_ticks()
        if detailed:
            self._record_process_cpu_rates(
                process_before, process_after, elapsed, sample_end
            )
        usage = calculate_process_cpu_usage(
            process_before,
            process_after,
            elapsed,
            cores,
            _clock_ticks(),
        )
        if usage is not None:
            return usage, "/proc/[pid]/stat"

        if after is not None:
            since_boot = calculate_cpu_usage_since_boot(after)
            if since_boot is not None:
                return since_boot, "/proc/stat (boot avg)"

        if stat_error is not None:
            raise MetricUnavailable(f"/proc/stat unavailable ({stat_error})")
        return None, None

    def _record_process_cpu_rates(
        self,
        before: Mapping[int, int] | None,
        after: Mapping[int, int] | None,
        elapsed: float,
        sample_end: float,
    ) -> None:
        """Store per-PID CPU rates, blending the previous watch sample."""

        if not after:
            return
        clock_ticks = _clock_ticks()
        rates = calculate_process_cpu_rates(before, after, elapsed, clock_ticks)
        if self._last_process_sample is not None:
            previous_time, previous_ticks = self._last_process_sample
            rates.update(
                calculate_process_cpu_rates(
                    previous_ticks,
                    after,
                    sample_end - previous_time,
                    clock_ticks,
                )
            )
        self._process_cpu_rates = rates
        self._last_process_sample = (sample_end, after)

    def _read_process_cpu_ticks(self) -> dict[int, int] | None:
        """Sum utime+stime for every readable process, keyed by PID."""

        try:
            entries = list(self.proc_root.iterdir())
        except OSError:
            return None

        ticks: dict[int, int] = {}
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                stat = _read_text(entry / "stat")
                # The command name can contain spaces and parentheses, so split
                # only after its closing parenthesis.
                fields = stat.rsplit(")", 1)[1].split()
                utime = int(fields[11])
                stime = int(fields[12])
            except (OSError, ValueError, IndexError):
                continue
            ticks[int(entry.name)] = utime + stime
        return ticks or None

    def _collect_memory(self, warnings: list[str]) -> MemoryStats | None:
        cgroup_memory = self._memory_from_cgroup()
        if cgroup_memory is not None:
            return cgroup_memory

        try:
            return parse_meminfo(_read_text(self.proc_root / "meminfo"))
        except (OSError, ValueError, MetricUnavailable) as proc_exc:
            try:
                return parse_free_bytes(self._run(("free", "-b")))
            except MetricUnavailable as free_exc:
                warnings.append(
                    f"Memory: /proc/meminfo unavailable ({proc_exc}); {free_exc}"
                )
                return None

    def _memory_from_cgroup(self) -> MemoryStats | None:
        """Use a finite cgroup v2 memory limit when one is readable."""

        cgroup_dir = self._cgroup_dir()
        try:
            total = parse_cgroup_memory_limit(
                _read_text(cgroup_dir / "memory.max")
            )
            current = parse_cgroup_memory_current(
                _read_text(cgroup_dir / "memory.current")
            )
        except (OSError, ValueError, MetricUnavailable):
            return None
        if total is None or current is None:
            return None

        used = min(current, total)
        swap_total = 0
        swap_used = 0
        try:
            swap_limit = parse_cgroup_memory_limit(
                _read_text(cgroup_dir / "memory.swap.max")
            )
            swap_current = parse_cgroup_memory_current(
                _read_text(cgroup_dir / "memory.swap.current")
            )
            if swap_limit is not None:
                swap_total = swap_limit
                swap_used = min(swap_current, swap_limit)
        except (OSError, ValueError, MetricUnavailable):
            pass

        return MemoryStats(
            total_bytes=total,
            used_bytes=used,
            available_bytes=total - used,
            free_bytes=total - used,
            swap_total_bytes=swap_total,
            swap_used_bytes=swap_used,
            source="cgroup v2",
        )

    def _collect_disks(self, warnings: list[str]) -> tuple[DiskStats, ...]:
        disks: list[DiskStats] = []
        for path in self.paths:
            disk = self._collect_disk(path, warnings)
            if disk is not None:
                disks.append(disk)
        return tuple(disks)

    def _collect_disk(self, path: Path, warnings: list[str]) -> DiskStats | None:
        try:
            usage = shutil.disk_usage(path)
            return DiskStats(
                path=str(path),
                total_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                source="statvfs",
            )
        except OSError as stat_exc:
            try:
                return parse_df_k(self._run(("df", "-Pk", str(path))), str(path))
            except MetricUnavailable as df_exc:
                warnings.append(
                    f"Disk {path}: statvfs unavailable ({stat_exc}); {df_exc}"
                )
                return None

    def _track_uptime(self, raw_seconds: float, source: str) -> tuple[float, str]:
        """Advance a frozen uptime counter using monotonic elapsed time."""

        now = self.monotonic()
        previous = self._last_uptime
        extrapolated = False
        if previous is None or previous[3] != source:
            seconds = raw_seconds
        else:
            previous_time, previous_raw, previous_seconds, _ = previous
            elapsed = max(0.0, now - previous_time)
            if raw_seconds < previous_raw - 1.0:
                # A reboot or namespace change restarts the counter.
                seconds = raw_seconds
            elif raw_seconds > previous_raw:
                # Normal progress; never move backwards after extrapolation.
                seconds = max(raw_seconds, previous_seconds)
            elif elapsed > 0:
                seconds = previous_seconds + elapsed
                extrapolated = True
            else:
                seconds = previous_seconds

        self._last_uptime = (now, raw_seconds, seconds, source)
        label = f"{source} (extrapolated)" if extrapolated else source
        return seconds, label

    def _collect_uptime(self, warnings: list[str]) -> UptimeStats | None:
        proc_error: Exception | None = None
        try:
            raw_seconds = parse_uptime(_read_text(self.proc_root / "uptime"))
            seconds, source = self._track_uptime(raw_seconds, "/proc/uptime")
            return UptimeStats(seconds=seconds, source=source)
        except (OSError, ValueError, MetricUnavailable) as exc:
            proc_error = exc

        try:
            booted = parse_boot_time(self._run(("uptime", "-s")))
            raw_seconds = max(0.0, self.clock() - booted)
            seconds, source = self._track_uptime(raw_seconds, "uptime -s")
            return UptimeStats(seconds=seconds, source=source)
        except MetricUnavailable as exc:
            warnings.append(
                f"Uptime: /proc/uptime unavailable ({proc_error}); {exc}"
            )
            return None

    def _collect_docker(self) -> DockerStats | None:
        """Read running containers via the Docker CLI, when available.

        Docker is optional host tooling, so every failure mode — no
        binary, a stopped daemon, a socket the current user may not
        read, zero running containers — simply hides the panel instead
        of warning on every refresh.
        """

        if self.docker_command is None:
            return None
        if self.runner is None and shutil.which(self.docker_command[0]) is None:
            return None
        try:
            output = self._run(
                self.docker_command, timeout=self.docker_timeout
            )
        except MetricUnavailable:
            return None
        stats = parse_docker_stats(output)
        return stats if stats.containers else None

    def _collect_battery(self, warnings: list[str]) -> BatteryStats | None:
        """Read battery state via Termux:API, caching slow command results."""

        if self.battery_command is None:
            return None
        if self.runner is None and shutil.which(self.battery_command[0]) is None:
            return None

        now = self.monotonic()
        if self._battery_cache is not None:
            checked_at, stats, error = self._battery_cache
            if now - checked_at < self.battery_cache_seconds:
                if error:
                    warnings.append(f"Battery: {error}")
                if stats is not None:
                    stats = replace(
                        stats,
                        cache_age_seconds=max(0.0, now - checked_at),
                    )
                return stats

        stats, error = self._read_battery()
        if stats is not None:
            stats = replace(stats, cache_age_seconds=0.0)
        self._battery_cache = (now, stats, error)
        if error:
            warnings.append(f"Battery: {error}")
        return stats

    def _read_battery(self) -> tuple[BatteryStats | None, str | None]:
        assert self.battery_command is not None
        try:
            output = self._run(self.battery_command, timeout=self.battery_timeout)
            battery = parse_termux_battery(output)
        except MetricUnavailable as exc:
            if "command not found" in str(exc):
                return None, None
            return None, str(exc)

        if not battery.present:
            return None, None
        return battery, None

    def _collect_network(self, warnings: list[str]) -> NetworkStats | None:
        errors: list[str] = []
        stats: NetworkStats | None = None

        try:
            stats = parse_net_dev(_read_text(self.proc_root / "net" / "dev"))
        except (OSError, ValueError, MetricUnavailable) as exc:
            errors.append(f"/proc/net/dev unavailable ({exc})")

        if stats is None:
            try:
                stats = parse_sysfs_net(self.sysfs_net)
            except (OSError, ValueError, MetricUnavailable) as exc:
                errors.append(f"sysfs unavailable ({exc})")

        if stats is None and self.android_service.exists():
            try:
                stats = parse_android_netstats(
                    self._run(
                        (str(self.android_service), "call", "netstats", "13")
                    )
                )
            except MetricUnavailable as exc:
                errors.append(f"android netstats unavailable ({exc})")

        if stats is None:
            try:
                stats = parse_ip_link_json(self._run(("ip", "-s", "-j", "link")))
            except MetricUnavailable as exc:
                errors.append(str(exc))

        if stats is None:
            warnings.append("Network: " + "; ".join(errors))
            return None

        now = self.monotonic()
        rx_rate: float | None = None
        tx_rate: float | None = None
        if self._last_network is not None:
            previous_time, previous_rx, previous_tx, previous_source = (
                self._last_network
            )
            elapsed = now - previous_time
            if (
                previous_source == stats.source
                and elapsed > 0
                and stats.rx_bytes >= previous_rx
                and stats.tx_bytes >= previous_tx
            ):
                rx_rate = (stats.rx_bytes - previous_rx) / elapsed
                tx_rate = (stats.tx_bytes - previous_tx) / elapsed
        self._last_network = (now, stats.rx_bytes, stats.tx_bytes, stats.source)

        interface_details = stats.interface_details
        if self._last_interfaces is not None:
            previous_time, previous_map, previous_source = self._last_interfaces
            elapsed = now - previous_time
            if previous_source == stats.source and elapsed > 0:
                with_rates: list[NetworkInterfaceStats] = []
                for interface in interface_details:
                    previous = previous_map.get(interface.name)
                    if (
                        previous is not None
                        and interface.rx_bytes >= previous[0]
                        and interface.tx_bytes >= previous[1]
                    ):
                        interface = replace(
                            interface,
                            rx_rate=(interface.rx_bytes - previous[0]) / elapsed,
                            tx_rate=(interface.tx_bytes - previous[1]) / elapsed,
                        )
                    with_rates.append(interface)
                interface_details = tuple(with_rates)
        self._last_interfaces = (
            now,
            {
                interface.name: (interface.rx_bytes, interface.tx_bytes)
                for interface in interface_details
            },
            stats.source,
        )

        return NetworkStats(
            rx_bytes=stats.rx_bytes,
            tx_bytes=stats.tx_bytes,
            rx_rate=rx_rate,
            tx_rate=tx_rate,
            interfaces=stats.interfaces,
            interface_details=interface_details,
            source=stats.source,
        )

    def _collect_processes(self, warnings: list[str]) -> ProcessStats:
        total: int | None = None
        running: int | None = None
        counts_error: str | None = None
        try:
            running, total = self._process_counts()
        except (OSError, ValueError, MetricUnavailable) as exc:
            counts_error = str(exc)

        top: tuple[ProcessInfo, ...] = ()
        top_source = "unavailable"
        top_error: str | None = None
        try:
            top, top_source = self._read_top_processes()
        except (OSError, ValueError, MetricUnavailable) as exc:
            top_error = str(exc)

        if top_error and total is None:
            warnings.append(
                "Processes: counts and top list unavailable "
                f"({counts_error}; {top_error})"
            )
        elif top_error:
            warnings.append(f"Processes: top list unavailable ({top_error})")
        elif counts_error:
            warnings.append(f"Processes: counts unavailable ({counts_error})")

        return ProcessStats(
            total=total,
            running=running,
            top=top,
            source=top_source,
            sort=self.process_sort,
            limit=self.process_limit,
            filter=self.process_filter,
        )

    def _process_counts(self) -> tuple[int, int]:
        total = 0
        running = 0
        for entry in self.proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            total += 1
            try:
                stat = _read_text(entry / "stat")
                state = stat.rsplit(")", 1)[1].split()[0]
            except (OSError, IndexError):
                continue
            if state == "R":
                running += 1
        if total == 0:
            raise MetricUnavailable("/proc contains no process directories")
        return running, total

    def _read_top_processes(self) -> tuple[tuple[ProcessInfo, ...], str]:
        errors: list[str] = []
        if self._process_cpu_rates:
            try:
                return self._top_processes_from_proc(), "/proc"
            except (OSError, ValueError, MetricUnavailable) as exc:
                errors.append(f"/proc unavailable ({exc})")

        columns = "args" if self.full_command else "comm"
        try:
            output = self._run(("ps", "-eo", f"pid=,pcpu=,rss=,{columns}="))
            return (
                parse_ps_processes(
                    output,
                    self.process_limit,
                    sort_by=self.process_sort,
                    filter_pattern=self.process_filter,
                ),
                "ps",
            )
        except MetricUnavailable as exc:
            errors.append(f"ps unavailable ({exc})")

        try:
            return self._top_processes_from_proc(), "/proc"
        except (OSError, ValueError, MetricUnavailable) as exc:
            errors.append(f"/proc scan failed ({exc})")

        raise MetricUnavailable("; ".join(errors))

    def _top_processes_from_proc(self) -> tuple[ProcessInfo, ...]:
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError) as exc:
            raise MetricUnavailable(f"cannot determine page size: {exc}") from exc

        selected: list[ProcessInfo] = []
        readable = 0
        for entry in self.proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                statm = _read_text(entry / "statm").split()
                resident_pages = int(statm[1])
            except (OSError, ValueError, IndexError):
                continue
            if resident_pages <= 0:
                continue
            readable += 1
            pid = int(entry.name)
            command = self._process_command(entry, pid)
            if (
                self._process_pattern is not None
                and not self._process_pattern.search(command)
            ):
                continue
            selected.append(
                ProcessInfo(
                    pid=pid,
                    command=command,
                    cpu_percent=self._process_cpu_rates.get(pid),
                    memory_bytes=resident_pages * page_size,
                )
            )

        if readable == 0:
            raise MetricUnavailable("/proc contains no readable process data")
        return tuple(_sort_processes(selected, self.process_sort)[: self.process_limit])

    def _process_command(self, entry: Path, pid: int) -> str:
        if self.full_command:
            try:
                command = (
                    _read_text(entry / "cmdline")
                    .replace("\x00", " ")
                    .strip()
                )
            except OSError:
                command = ""
            if command:
                return command
        try:
            command = _read_text(entry / "comm").strip()
        except OSError:
            command = ""
        return command or f"[{pid}]"

    def _run(
        self, args: Sequence[str], *, timeout: float | None = None
    ) -> str:
        if self.runner is not None:
            try:
                output = self.runner(tuple(args))
            except MetricUnavailable:
                raise
            except Exception as exc:  # Defensive: a runner is user-supplied.
                raise MetricUnavailable(f"{args[0]}: {exc}") from exc
            if not output.strip():
                raise MetricUnavailable(f"{args[0]} returned no output")
            return output

        executable = shutil.which(args[0])
        if executable is None:
            raise MetricUnavailable(f"{args[0]}: command not found")

        try:
            completed = subprocess.run(
                [executable, *args[1:]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout if timeout is not None else self.command_timeout,
                check=False,
                env={**os.environ, "LC_ALL": "C"},
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MetricUnavailable(f"{args[0]}: {exc}") from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()
            reason = detail[-1] if detail else f"exit code {completed.returncode}"
            raise MetricUnavailable(f"{args[0]} failed: {reason}")
        if not completed.stdout.strip():
            raise MetricUnavailable(f"{args[0]} returned no output")
        return completed.stdout

    def _read_os_name(self) -> str:
        try:
            name = parse_os_release(_read_text(self.os_release))
        except (OSError, ValueError):
            name = None
        return name or platform.system() or "Linux"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_int_file(path: Path) -> int | None:
    try:
        value = int(_read_text(path).strip())
    except (OSError, ValueError):
        return None
    return value if value >= 0 else None


def _first_readable_int(
    directory: Path, names: Sequence[str]
) -> int | None:
    for name in names:
        value = _read_int_file(directory / name)
        if value is not None:
            return value
    return None


def _read_int_list(path: Path) -> list[int]:
    try:
        values = [int(field) for field in _read_text(path).split()]
    except (OSError, ValueError):
        return []
    return sorted({value for value in values if value >= 0})


def _policy_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"(\d+)$", path.name)
    return (int(match.group(1)) if match else 10**9, path.name)


def _cpu_label(cpus: Sequence[int]) -> str | None:
    if not cpus:
        return None
    ordered = sorted(set(cpus))
    ranges: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for cpu in ordered[1:]:
        if cpu == previous + 1:
            previous = cpu
            continue
        ranges.append((start, previous))
        start = previous = cpu
    ranges.append((start, previous))

    labels = [
        str(first) if first == last else f"{first}-{last}"
        for first, last in ranges
    ]
    return "CPU " + ",".join(labels)


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: object) -> int | None:
    number = _optional_float(value)
    return int(number) if number is not None else None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None
