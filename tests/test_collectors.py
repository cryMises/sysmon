from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

import sysmon.collectors as collectors
from sysmon.collectors import (
    CpuTimes,
    MetricUnavailable,
    SystemCollector,
    calculate_cpu_usage,
    calculate_cpu_usage_since_boot,
    parse_boot_time,
    parse_cpu_stat,
    parse_df_k,
    parse_free_bytes,
    parse_loadavg,
    parse_meminfo,
    parse_os_release,
    parse_uptime,
)

MEMINFO = """\
MemTotal:        8000000 kB
MemFree:         2000000 kB
MemAvailable:    5000000 kB
Buffers:          100000 kB
Cached:          1000000 kB
SwapTotal:       2000000 kB
SwapFree:         500000 kB
"""

FREE_HEADER = (
    "               total        used        free      shared  "
    "buff/cache   available\n"
)
FREE_BYTES = (
    FREE_HEADER
    + "Mem:     8000000000  3000000000  2000000000   100000000  "
    "1000000000  5000000000\n"
    + "Swap:    2000000000  1500000000   500000000\n"
)

DF_K = """\
Filesystem     1024-blocks    Used Available Capacity Mounted on
/dev/sda1           100000   42000     58000      42% /
"""


def test_parse_loadavg() -> None:
    load = parse_loadavg("1.25 0.75 0.50 2/300 1234\n")
    assert (load.one, load.five, load.fifteen) == (1.25, 0.75, 0.50)


def test_parse_loadavg_rejects_bad_data() -> None:
    with pytest.raises(MetricUnavailable):
        parse_loadavg("not enough")
    with pytest.raises(MetricUnavailable):
        parse_loadavg("one two three")


def test_parse_meminfo() -> None:
    memory = parse_meminfo(MEMINFO)
    assert memory.total_bytes == 8_000_000 * 1024
    assert memory.available_bytes == 5_000_000 * 1024
    assert memory.used_bytes == 3_000_000 * 1024
    assert memory.used_percent == 37.5
    assert memory.swap_used_bytes == 1_500_000 * 1024
    assert memory.swap_percent == 75.0
    assert memory.source == "/proc/meminfo"


def test_parse_meminfo_approximates_memavailable() -> None:
    memory = parse_meminfo(
        "MemTotal: 1000 kB\n"
        "MemFree: 100 kB\n"
        "Buffers: 50 kB\n"
        "Cached: 200 kB\n"
        "SReclaimable: 50 kB\n"
        "Shmem: 20 kB\n"
    )
    assert memory.available_bytes == 380 * 1024
    assert memory.used_percent == 62.0
    assert memory.swap_total_bytes == 0


def test_parse_meminfo_rejects_missing_totals() -> None:
    with pytest.raises(MetricUnavailable):
        parse_meminfo("MemFree: 10 kB\n")


def test_parse_free_bytes() -> None:
    memory = parse_free_bytes(FREE_BYTES)
    assert memory.total_bytes == 8_000_000_000
    assert memory.used_bytes == 3_000_000_000
    assert memory.available_bytes == 5_000_000_000
    assert memory.used_percent == 37.5
    assert memory.swap_used_bytes == 1_500_000_000
    assert memory.source == "free -b"


def test_parse_cpu_stat_and_usage() -> None:
    before = parse_cpu_stat(
        "cpu  100 0 100 800 0 0 0 0 0 0\n"
        "cpu0 50 0 50 400 0 0 0 0 0 0\n"
    )
    after = parse_cpu_stat("cpu  200 0 100 1100 0 0 0 0 0 0\n")
    assert before == CpuTimes(idle=800, total=1000)
    assert calculate_cpu_usage(before, after) == 25.0
    assert calculate_cpu_usage_since_boot(after) == pytest.approx(21.428571)
    assert calculate_cpu_usage(before, before) is None
    assert calculate_cpu_usage_since_boot(CpuTimes(idle=0, total=0)) is None


def test_parse_cpu_stat_rejects_invalid_data() -> None:
    with pytest.raises(MetricUnavailable):
        parse_cpu_stat("intr 123\n")
    with pytest.raises(MetricUnavailable):
        parse_cpu_stat("cpu 1 2 3\n")


def test_parse_uptime() -> None:
    assert parse_uptime("124.08 932.76\n") == 124.08
    with pytest.raises(MetricUnavailable):
        parse_uptime("nope")


def test_parse_boot_time() -> None:
    parsed = parse_boot_time("2026-10-21 21:26:30\n")
    expected = datetime.fromisoformat("2026-10-21 21:26:30").astimezone().timestamp()
    assert parsed == expected


def test_parse_df_k() -> None:
    disk = parse_df_k(DF_K, "/")
    assert disk.total_bytes == 100_000 * 1024
    assert disk.used_bytes == 42_000 * 1024
    assert disk.free_bytes == 58_000 * 1024
    assert disk.used_percent == 42.0
    assert disk.source == "df -Pk"


def test_parse_os_release() -> None:
    assert (
        parse_os_release('NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 26.04.1 LTS"\n')
        == "Ubuntu 26.04.1 LTS"
    )
    assert parse_os_release('NAME="Termux"\n') == "Termux"
    assert parse_os_release("") is None


def test_collector_uses_command_fallbacks(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "loadavg").write_text("0.10 0.20 0.30 1/100 42\n")
    (proc / "uptime").write_text("124.08 932.76\n")

    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...]) -> str:
        calls.append(args)
        if args[0] == "free":
            return FREE_BYTES
        raise AssertionError(f"unexpected command: {args}")

    collector = SystemCollector(
        paths=(tmp_path,),
        proc_root=proc,
        runner=runner,
        cpu_sample_seconds=0,
    )
    snapshot = collector.collect()

    assert calls == [("free", "-b")]
    assert snapshot.memory is not None
    assert snapshot.memory.source == "free -b"
    assert snapshot.uptime is not None
    assert snapshot.uptime.seconds == 124.08
    assert snapshot.disks[0].source == "statvfs"
    assert snapshot.warnings == ()


def test_collector_missing_proc_and_utilities_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_runner(args: tuple[str, ...]) -> str:
        raise RuntimeError("utility is missing")

    def fail_loadavg() -> tuple[float, float, float]:
        raise OSError("loadavg unavailable")

    def fail_disk_usage(path: object) -> object:
        raise OSError("statvfs blocked")

    monkeypatch.setattr(os, "getloadavg", fail_loadavg)
    monkeypatch.setattr(collectors.shutil, "disk_usage", fail_disk_usage)

    collector = SystemCollector(
        paths=(tmp_path,),
        proc_root=tmp_path / "does-not-exist",
        runner=fail_runner,
        cpu_sample_seconds=0,
    )
    snapshot = collector.collect()

    assert snapshot.cpu is not None
    assert snapshot.cpu.usage_percent is None
    assert snapshot.cpu.load.one is None
    assert snapshot.cpu.source == "unavailable"
    assert snapshot.memory is None
    assert snapshot.disks == ()
    assert snapshot.uptime is None
    assert len(snapshot.warnings) == 4
    assert any(w.startswith("CPU load:") for w in snapshot.warnings)
    assert any(w.startswith("Memory:") for w in snapshot.warnings)
    assert any(w.startswith(f"Disk {tmp_path}:") for w in snapshot.warnings)
    assert any(w.startswith("Uptime:") for w in snapshot.warnings)


def test_missing_command_reports_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collectors.shutil, "which", lambda name: None)
    collector = SystemCollector(proc_root=tmp_path, cpu_sample_seconds=0)
    with pytest.raises(MetricUnavailable, match="command not found"):
        collector._run(("free", "-b"))


def test_static_proc_stat_falls_back_to_since_boot(tmp_path: Path) -> None:
    (tmp_path / "stat").write_text("cpu  200 0 100 1100 0 0 0 0 0 0\n")
    collector = SystemCollector(
        proc_root=tmp_path,
        cpu_sample_seconds=0.01,
        sleep=lambda seconds: None,
    )
    usage, source = collector._sample_cpu_usage()
    assert usage == pytest.approx(21.428571)
    assert source == "/proc/stat (boot avg)"


@pytest.mark.skipif(not Path("/proc/meminfo").exists(), reason="requires Linux /proc")
def test_real_snapshot_on_this_host() -> None:
    snapshot = SystemCollector(cpu_sample_seconds=0).collect()
    assert snapshot.hostname
    assert snapshot.os_name
    assert snapshot.cpu is not None
    assert snapshot.memory is not None
    assert snapshot.memory.total_bytes
    assert snapshot.memory.total_bytes > 0
    assert snapshot.uptime is not None
    assert snapshot.uptime.seconds >= 0
    assert snapshot.disks
    assert snapshot.disks[0].total_bytes
    assert snapshot.disks[0].total_bytes > 0
