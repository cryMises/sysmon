"""Read-only collectors for CPU, memory, disks, and uptime.

The primary sources are Linux ``/proc`` and the Python standard library. If
those are unavailable, a few read-only command-line tools are tried as
fallbacks. Every failure is reported as a warning rather than crashing the
dashboard.
"""

from __future__ import annotations

import math
import os
import platform
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import (
    CpuStats,
    DiskStats,
    LoadAverage,
    MemoryStats,
    Snapshot,
    UptimeStats,
)

CommandRunner = Callable[[Sequence[str]], str]


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
        os_release: Path = Path("/etc/os-release"),
        cpu_sample_seconds: float = 0.12,
        command_timeout: float = 2.0,
        runner: CommandRunner | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.paths = tuple(Path(path) for path in paths) or (Path("/"),)
        self.proc_root = Path(proc_root)
        self.os_release = Path(os_release)
        self.cpu_sample_seconds = max(0.0, cpu_sample_seconds)
        self.command_timeout = command_timeout
        self.runner = runner
        self.clock = clock
        self.sleep = sleep

    def collect(self) -> Snapshot:
        warnings: list[str] = []
        cpu = self._collect_cpu(warnings)
        memory = self._collect_memory(warnings)
        disks = self._collect_disks(warnings)
        uptime = self._collect_uptime(warnings)

        return Snapshot(
            timestamp=self.clock(),
            cpu=cpu,
            memory=memory,
            disks=disks,
            uptime=uptime,
            warnings=tuple(warnings),
            hostname=platform.node().strip() or "unknown",
            os_name=self._read_os_name(),
            machine=platform.machine().strip() or "unknown",
        )

    def _collect_cpu(self, warnings: list[str]) -> CpuStats:
        load = LoadAverage()
        load_source: str | None = None
        load_error: str | None = None
        try:
            load, load_source = self._read_load()
        except MetricUnavailable as exc:
            load_error = str(exc)

        usage: float | None = None
        usage_source: str | None = None
        usage_error: str | None = None
        try:
            usage, usage_source = self._sample_cpu_usage()
        except (OSError, ValueError, MetricUnavailable) as exc:
            usage_error = str(exc)

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
            cores=os.cpu_count(),
            source=" + ".join(sources) if sources else "unavailable",
        )

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

    def _sample_cpu_usage(self) -> tuple[float | None, str | None]:
        """Sample CPU usage, falling back to the average since boot.

        Some containers (notably PRoot on Android) expose a static
        ``/proc/stat``. In that case delta sampling produces no delta and the
        since-boot average is the best read-only estimate available.
        """

        if self.cpu_sample_seconds <= 0:
            return None, None
        stat_path = self.proc_root / "stat"
        before = parse_cpu_stat(_read_text(stat_path))
        self.sleep(self.cpu_sample_seconds)
        after = parse_cpu_stat(_read_text(stat_path))
        usage = calculate_cpu_usage(before, after)
        if usage is not None:
            return usage, "/proc/stat"
        since_boot = calculate_cpu_usage_since_boot(after)
        if since_boot is not None:
            return since_boot, "/proc/stat (boot avg)"
        return None, None

    def _collect_memory(self, warnings: list[str]) -> MemoryStats | None:
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

    def _collect_uptime(self, warnings: list[str]) -> UptimeStats | None:
        proc_error: Exception | None = None
        try:
            return UptimeStats(
                seconds=parse_uptime(_read_text(self.proc_root / "uptime")),
                source="/proc/uptime",
            )
        except (OSError, ValueError, MetricUnavailable) as exc:
            proc_error = exc

        try:
            booted = parse_boot_time(self._run(("uptime", "-s")))
            return UptimeStats(
                seconds=max(0.0, self.clock() - booted), source="uptime -s"
            )
        except MetricUnavailable as exc:
            warnings.append(
                f"Uptime: /proc/uptime unavailable ({proc_error}); {exc}"
            )
            return None

    def _run(self, args: Sequence[str]) -> str:
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
                timeout=self.command_timeout,
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
