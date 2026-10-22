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
    calculate_process_cpu_rates,
    calculate_process_cpu_usage,
    parse_android_netstats,
    parse_boot_time,
    parse_cgroup_cpu_max,
    parse_cgroup_cpu_usage,
    parse_cgroup_memory_current,
    parse_cgroup_memory_limit,
    parse_cpu_stat,
    parse_df_k,
    parse_free_bytes,
    parse_ip_link_json,
    parse_loadavg,
    parse_meminfo,
    parse_net_dev,
    parse_os_release,
    parse_ps_processes,
    parse_sysfs_net,
    parse_termux_battery,
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

NET_DEV = """\
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:    1000      10    0    0    0     0          0         0   1000      10    0    0    0     0       0          0
wlan0:    2000      20    0    0    0     0          0         0    500       5    0    0    0     0       0          0
"""

PS_OUTPUT = """\
  123  12.5 204800 chrome
  456   0.0 102400 python
  789  30.0  51200 process with spaces
  999 100.0   1000 ps
"""

IP_LINK_JSON = """\
[
  {"ifname": "lo", "stats64": {"rx": {"bytes": 1000}, "tx": {"bytes": 1000}}},
  {"ifname": "eth0", "stats64": {"rx": {"bytes": 5000}, "tx": {"bytes": 2500}}},
  {"ifname": "wlan0", "stats": {"rx": {"bytes": 3000}, "tx": {"bytes": 1500}}}
]
"""

BATTERY_JSON = """\
{
  "present": true,
  "technology": "Li-poly",
  "health": "GOOD",
  "plugged": "UNPLUGGED",
  "status": "DISCHARGING",
  "temperature": 37.5,
  "voltage": 3813,
  "current": 801000,
  "current_average": -3000,
  "percentage": 45,
  "level": 45,
  "scale": 100,
  "charge_counter": 2015000,
  "cycle": 789
}
"""

ANDROID_NETSTATS = """\
Result: Parcel(
0x00000000: 00000000 00000001 00000024 5e12641b '........$....d.^'
0x00000010: 00000000 0016262b 00000000 0f6e01d1 '....+&........n.'
0x00000020: 00000000 000a49a6 00000000          '.....I......    ')
"""


def add_proc_process(
    proc: Path,
    pid: int,
    state: str,
    command: str,
    resident_pages: int = 10,
) -> None:
    process_dir = proc / str(pid)
    process_dir.mkdir()
    (process_dir / "stat").write_text(
        f"{pid} ({command}) {state} 1 2 3 4 5 6 7 8 9 10\n"
    )
    (process_dir / "statm").write_text(
        f"100 {resident_pages} 10 0 0 0 0\n"
    )
    (process_dir / "comm").write_text(f"{command}\n")


def write_proc_cpu_times(proc: Path, pid: int, utime: int, stime: int) -> None:
    process_dir = proc / str(pid)
    process_dir.mkdir(exist_ok=True)
    (process_dir / "stat").write_text(
        f"{pid} (worker) R 1 2 3 4 5 6 7 8 9 10 {utime} {stime} 0 0 0\n"
    )
    (process_dir / "statm").write_text("100 10 10 0 0 0 0\n")
    (process_dir / "comm").write_text("worker\n")


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


def test_parse_cgroup_cpu_values() -> None:
    assert parse_cgroup_cpu_max("200000 100000\n") == 2.0
    assert parse_cgroup_cpu_max("max 100000\n") is None
    with pytest.raises(MetricUnavailable):
        parse_cgroup_cpu_max("bad")
    with pytest.raises(MetricUnavailable):
        parse_cgroup_cpu_max("0 100000")

    assert parse_cgroup_cpu_usage("usage_usec 1234\nnr_periods 10\n") == 1234
    assert parse_cgroup_cpu_usage("nr_periods 10\n") is None
    with pytest.raises(MetricUnavailable):
        parse_cgroup_cpu_usage("usage_usec nope\n")


def test_parse_cgroup_memory_values() -> None:
    assert parse_cgroup_memory_limit("1073741824\n") == 1073741824
    assert parse_cgroup_memory_limit("max\n") is None
    assert parse_cgroup_memory_limit("0\n") is None
    with pytest.raises(MetricUnavailable):
        parse_cgroup_memory_limit("nope")

    assert parse_cgroup_memory_current("4096\n") == 4096
    with pytest.raises(MetricUnavailable):
        parse_cgroup_memory_current("-1\n")


def test_parse_df_k() -> None:
    disk = parse_df_k(DF_K, "/")
    assert disk.total_bytes == 100_000 * 1024
    assert disk.used_bytes == 42_000 * 1024
    assert disk.free_bytes == 58_000 * 1024
    assert disk.used_percent == 42.0
    assert disk.source == "df -Pk"


def test_parse_net_dev_excludes_loopback() -> None:
    network = parse_net_dev(NET_DEV)
    assert network.rx_bytes == 2000
    assert network.tx_bytes == 500
    assert network.interfaces == 1
    assert network.rx_rate is None
    assert network.source == "/proc/net/dev"


def test_parse_net_dev_falls_back_to_loopback() -> None:
    only_loopback = "\n".join(NET_DEV.splitlines()[:2] + [NET_DEV.splitlines()[2]])
    network = parse_net_dev(only_loopback)
    assert network.rx_bytes == 1000
    assert network.tx_bytes == 1000
    assert network.interfaces == 1


def test_parse_sysfs_net_excludes_loopback(tmp_path: Path) -> None:
    interfaces = (("lo", 1000, 1000), ("eth0", 5000, 2500), ("wlan0", 3000, 1500))
    for name, rx, tx in interfaces:
        statistics = tmp_path / name / "statistics"
        statistics.mkdir(parents=True)
        (statistics / "rx_bytes").write_text(f"{rx}\n")
        (statistics / "tx_bytes").write_text(f"{tx}\n")

    network = parse_sysfs_net(tmp_path)
    assert network.rx_bytes == 8000
    assert network.tx_bytes == 4000
    assert network.interfaces == 2
    assert network.source == "sysfs"


def test_parse_sysfs_net_falls_back_to_loopback(tmp_path: Path) -> None:
    statistics = tmp_path / "lo" / "statistics"
    statistics.mkdir(parents=True)
    (statistics / "rx_bytes").write_text("42\n")
    (statistics / "tx_bytes").write_text("24\n")

    network = parse_sysfs_net(tmp_path)
    assert (network.rx_bytes, network.tx_bytes, network.interfaces) == (42, 24, 1)


def test_parse_sysfs_net_rejects_missing_or_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(MetricUnavailable):
        parse_sysfs_net(tmp_path / "missing")
    with pytest.raises(MetricUnavailable):
        parse_sysfs_net(tmp_path)


def test_parse_ip_link_json() -> None:
    network = parse_ip_link_json(IP_LINK_JSON)
    assert network.rx_bytes == 8000
    assert network.tx_bytes == 4000
    assert network.interfaces == 2
    assert network.source == "ip -s"


def test_parse_ip_link_json_rejects_bad_output() -> None:
    with pytest.raises(MetricUnavailable):
        parse_ip_link_json("not json")
    with pytest.raises(MetricUnavailable):
        parse_ip_link_json('[{"ifname": "eth0"}]')


def test_parse_android_netstats() -> None:
    network = parse_android_netstats(ANDROID_NETSTATS)
    assert network.rx_bytes == 0x5E12641B
    assert network.tx_bytes == 0x0F6E01D1
    assert network.interfaces == 0
    assert network.source == "android netstats"


def test_parse_android_netstats_errors() -> None:
    with pytest.raises(MetricUnavailable):
        parse_android_netstats("")
    with pytest.raises(MetricUnavailable, match="exception -1"):
        parse_android_netstats(
            "0x00000000: ffffffff 00000001 00000024 00000000 '........$.......'\n"
        )
    with pytest.raises(MetricUnavailable, match="unsupported"):
        parse_android_netstats(
            "0x00000000: 00000000 00000001 00000010 00000000 '................'\n"
        )


def test_parse_ps_processes_sorts_and_limits() -> None:
    processes = parse_ps_processes(PS_OUTPUT, limit=2)
    assert [process.pid for process in processes] == [789, 123]
    assert processes[0].command == "process with spaces"
    assert processes[0].cpu_percent == 30.0
    assert processes[0].memory_bytes == 51_200 * 1024
    assert processes[1].command == "chrome"
    assert all(process.command != "ps" for process in processes)


def test_parse_ps_processes_rejects_empty_output() -> None:
    with pytest.raises(MetricUnavailable):
        parse_ps_processes("PID CPU MEM COMMAND\n")


def test_parse_os_release() -> None:
    assert (
        parse_os_release('NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 26.04.1 LTS"\n')
        == "Ubuntu 26.04.1 LTS"
    )
    assert parse_os_release('NAME="Termux"\n') == "Termux"
    assert parse_os_release("") is None


def test_parse_termux_battery() -> None:
    battery = parse_termux_battery(BATTERY_JSON)

    assert battery.present
    assert battery.percentage == 45
    assert battery.status == "DISCHARGING"
    assert battery.plugged == "UNPLUGGED"
    assert battery.temperature_c == 37.5
    assert battery.health == "GOOD"
    assert battery.technology == "Li-poly"
    assert battery.voltage_mv == 3813
    assert battery.current_ua == 801000
    assert battery.source == "termux-battery-status"


def test_parse_termux_battery_percentage_fallback() -> None:
    battery = parse_termux_battery(
        '{"present": true, "level": 50, "scale": 200, "status": "FULL"}'
    )
    assert battery.percentage == 25.0

    clamped = parse_termux_battery(
        '{"present": true, "percentage": 120, "status": "FULL"}'
    )
    assert clamped.percentage == 100.0


def test_parse_termux_battery_absent_and_invalid() -> None:
    absent = parse_termux_battery('{"present": false}')
    assert absent.present is False
    assert absent.percentage is None

    with pytest.raises(MetricUnavailable):
        parse_termux_battery("not json")
    with pytest.raises(MetricUnavailable):
        parse_termux_battery("[]")
    with pytest.raises(MetricUnavailable):
        parse_termux_battery('{"present": "yes"}')
    with pytest.raises(MetricUnavailable):
        parse_termux_battery("{}")


def test_battery_collection_caches_termux_command(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...]) -> str:
        calls.append(args)
        return BATTERY_JSON

    times = iter([100.0, 101.0, 131.0])
    collector = SystemCollector(
        proc_root=tmp_path,
        runner=runner,
        battery_cache_seconds=30,
        monotonic=lambda: next(times),
    )
    warnings: list[str] = []

    first = collector._collect_battery(warnings)
    second = collector._collect_battery(warnings)
    third = collector._collect_battery(warnings)

    assert first is not None and first.percentage == 45
    assert second is first
    assert third is not None and third.percentage == 45
    assert calls == [
        ("termux-battery-status",),
        ("termux-battery-status",),
    ]
    assert warnings == []


def test_battery_missing_command_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(collectors.shutil, "which", lambda name: None)
    collector = SystemCollector(proc_root=tmp_path, monotonic=lambda: 100.0)
    warnings: list[str] = []

    assert collector._collect_battery(warnings) is None
    assert warnings == []


def test_battery_absent_is_silent(tmp_path: Path) -> None:
    collector = SystemCollector(
        proc_root=tmp_path,
        runner=lambda args: '{"present": false}',
        monotonic=lambda: 100.0,
    )
    warnings: list[str] = []

    assert collector._collect_battery(warnings) is None
    assert warnings == []


def test_battery_failure_is_cached(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...]) -> str:
        calls.append(args)
        raise RuntimeError("Termux:API unavailable")

    times = iter([100.0, 101.0])
    collector = SystemCollector(
        proc_root=tmp_path,
        runner=runner,
        battery_cache_seconds=30,
        monotonic=lambda: next(times),
    )
    warnings: list[str] = []
    cached_warnings: list[str] = []

    assert collector._collect_battery(warnings) is None
    assert collector._collect_battery(cached_warnings) is None

    assert len(calls) == 1
    assert warnings and "Battery:" in warnings[0]
    assert cached_warnings and "Battery:" in cached_warnings[0]


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
        battery_command=None,
    )
    snapshot = collector.collect()

    assert calls == [("free", "-b")]
    assert snapshot.memory is not None
    assert snapshot.memory.source == "free -b"
    assert snapshot.uptime is not None
    assert snapshot.uptime.seconds == 124.08
    assert snapshot.disks[0].source == "statvfs"
    assert snapshot.network is None
    assert snapshot.processes is None
    assert snapshot.warnings == ()


def test_frozen_uptime_is_extrapolated(tmp_path: Path) -> None:
    uptime_path = tmp_path / "uptime"
    uptime_path.write_text("124.08 932.76\n")
    times = iter([100.0, 110.0, 120.0, 130.0])
    collector = SystemCollector(
        proc_root=tmp_path,
        cpu_sample_seconds=0,
        monotonic=lambda: next(times),
    )
    warnings: list[str] = []

    first = collector._collect_uptime(warnings)
    second = collector._collect_uptime(warnings)
    assert first is not None and second is not None
    assert first.seconds == 124.08
    assert first.source == "/proc/uptime"
    assert second.seconds == pytest.approx(134.08)
    assert second.source == "/proc/uptime (extrapolated)"

    uptime_path.write_text("144.08 932.76\n")
    third = collector._collect_uptime(warnings)
    assert third is not None
    assert third.seconds == 144.08
    assert third.source == "/proc/uptime"

    uptime_path.write_text("5.00 932.76\n")
    fourth = collector._collect_uptime(warnings)
    assert fourth is not None
    assert fourth.seconds == 5.0
    assert fourth.source == "/proc/uptime"
    assert warnings == []


def test_collector_uses_cgroup_cpu_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "cpu.max").write_text("200000 100000\n")
    (cgroup / "cpu.stat").write_text("usage_usec 0\n")

    def advance(seconds: float) -> None:
        (cgroup / "cpu.stat").write_text("usage_usec 4000000\n")

    monkeypatch.setattr(collectors.os, "cpu_count", lambda: 8)
    times = iter([100.0, 102.0])
    collector = SystemCollector(
        proc_root=tmp_path / "proc",
        cgroup_root=cgroup,
        cpu_sample_seconds=0.01,
        sleep=advance,
        monotonic=lambda: next(times),
    )

    assert collector._effective_cpu_cores() == 2
    usage, source = collector._sample_cpu_usage()
    assert usage == pytest.approx(100.0)
    assert source == "cgroup v2"


def test_collector_uses_cgroup_memory(tmp_path: Path) -> None:
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text("4294967296\n")
    (cgroup / "memory.current").write_text("1073741824\n")
    (cgroup / "memory.swap.max").write_text("2147483648\n")
    (cgroup / "memory.swap.current").write_text("536870912\n")

    collector = SystemCollector(
        proc_root=tmp_path / "proc",
        cgroup_root=cgroup,
        cpu_sample_seconds=0,
    )
    memory = collector._collect_memory([])

    assert memory is not None
    assert memory.total_bytes == 4 * 1024**3
    assert memory.used_bytes == 1 * 1024**3
    assert memory.available_bytes == 3 * 1024**3
    assert memory.free_bytes == 3 * 1024**3
    assert memory.swap_total_bytes == 2 * 1024**3
    assert memory.swap_used_bytes == 512 * 1024**2
    assert memory.source == "cgroup v2"


def test_cgroup_path_uses_current_scope(tmp_path: Path) -> None:
    scoped = tmp_path / "cgroup" / "uid_1000" / "pid_42"
    scoped.mkdir(parents=True)
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "self" / "cgroup").write_text("0::/uid_1000/pid_42\n")

    collector = SystemCollector(proc_root=proc, cgroup_root=tmp_path / "cgroup")
    assert collector._cgroup_dir() == scoped


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
        battery_command=None,
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


def test_process_cpu_usage_calculation() -> None:
    assert calculate_process_cpu_usage(
        {1: 100, 2: 50, 3: 10},
        {1: 300, 2: 50, 4: 999},
        elapsed=2.0,
        cores=4,
        clock_ticks=100,
    ) == pytest.approx(25.0)
    assert (
        calculate_process_cpu_usage(
            {1: 100}, {2: 200}, elapsed=2.0, cores=4, clock_ticks=100
        )
        is None
    )
    assert (
        calculate_process_cpu_usage(
            {1: 100}, {1: 300}, elapsed=0.0, cores=4, clock_ticks=100
        )
        is None
    )


def test_process_cpu_rates_calculation() -> None:
    rates = calculate_process_cpu_rates(
        {1: 100, 2: 50, 3: 10},
        {1: 300, 2: 50, 4: 999},
        elapsed=2.0,
        clock_ticks=100,
    )
    assert rates[1] == pytest.approx(100.0)
    assert rates[2] == pytest.approx(0.0)
    assert 3 not in rates
    assert 4 not in rates
    assert calculate_process_cpu_rates(None, {1: 300}, 2.0) == {}
    assert calculate_process_cpu_rates({1: 0}, {1: 300}, 0.0) == {}


def test_static_proc_stat_falls_back_to_process_cpu_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "stat").write_text("cpu  200 0 100 1100 0 0 0 0 0 0\n")
    write_proc_cpu_times(tmp_path, 100, utime=10, stime=5)
    write_proc_cpu_times(tmp_path, 200, utime=20, stime=5)

    def advance(seconds: float) -> None:
        write_proc_cpu_times(tmp_path, 100, utime=210, stime=5)
        write_proc_cpu_times(tmp_path, 200, utime=20, stime=5)

    monkeypatch.setattr(collectors.os, "cpu_count", lambda: 4)
    times = iter([100.0, 102.0])
    collector = SystemCollector(
        proc_root=tmp_path,
        cpu_sample_seconds=0.01,
        sleep=advance,
        monotonic=lambda: next(times),
    )
    usage, source = collector._sample_cpu_usage()
    assert usage == pytest.approx(25.0)
    assert source == "/proc/[pid]/stat"


def test_process_cpu_fallback_when_proc_stat_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_proc_cpu_times(tmp_path, 100, utime=0, stime=0)

    def advance(seconds: float) -> None:
        write_proc_cpu_times(tmp_path, 100, utime=400, stime=0)

    monkeypatch.setattr(collectors.os, "cpu_count", lambda: 2)
    times = iter([100.0, 102.0])
    collector = SystemCollector(
        proc_root=tmp_path,
        cpu_sample_seconds=0.01,
        sleep=advance,
        monotonic=lambda: next(times),
    )
    usage, source = collector._sample_cpu_usage()
    assert usage == pytest.approx(100.0)
    assert source == "/proc/[pid]/stat"


def test_detailed_cpu_sampling_feeds_live_top_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "loadavg").write_text("0.10 0.20 0.30 1/100 42\n")
    write_proc_cpu_times(tmp_path, 100, utime=0, stime=0)
    write_proc_cpu_times(tmp_path, 200, utime=50, stime=0)

    def advance(seconds: float) -> None:
        write_proc_cpu_times(tmp_path, 100, utime=200, stime=0)
        write_proc_cpu_times(tmp_path, 200, utime=50, stime=0)

    monkeypatch.setattr(collectors.os, "cpu_count", lambda: 4)
    times = iter([100.0, 102.0])
    collector = SystemCollector(
        proc_root=tmp_path,
        cgroup_root=tmp_path / "no-cgroup",
        cpu_sample_seconds=0.01,
        sleep=advance,
        monotonic=lambda: next(times),
    )

    cpu = collector._collect_cpu([], detailed=True)
    assert cpu.cores == 4
    assert cpu.usage_percent == pytest.approx(25.0)
    assert cpu.source == "/proc/loadavg + /proc/[pid]/stat"
    assert collector._process_cpu_rates[100] == pytest.approx(100.0)
    assert collector._process_cpu_rates[200] == 0.0

    processes = collector._collect_processes([])
    assert processes.source == "/proc"
    assert processes.running == 2
    assert processes.total == 2
    assert [process.pid for process in processes.top] == [100, 200]
    assert processes.top[0].command == "worker"
    assert processes.top[0].cpu_percent == pytest.approx(100.0)


def test_process_counts_and_proc_fallback_top(tmp_path: Path) -> None:
    add_proc_process(tmp_path, 1, "R", "init", resident_pages=10)
    add_proc_process(tmp_path, 2, "S", "bash", resident_pages=30)
    add_proc_process(tmp_path, 3, "R", "worker", resident_pages=20)

    collector = SystemCollector(proc_root=tmp_path, cpu_sample_seconds=0)
    assert collector._process_counts() == (2, 3)

    top = collector._top_processes_from_proc()
    assert [process.pid for process in top] == [2, 3, 1]
    assert all(process.cpu_percent is None for process in top)
    assert top[0].command == "bash"
    assert top[0].memory_bytes is not None
    assert top[0].memory_bytes > 0


def test_top_processes_fall_back_to_proc_when_ps_is_missing(
    tmp_path: Path,
) -> None:
    add_proc_process(tmp_path, 1, "R", "init", resident_pages=10)
    add_proc_process(tmp_path, 2, "S", "bash", resident_pages=30)

    def runner(args: tuple[str, ...]) -> str:
        raise RuntimeError("ps is not installed")

    collector = SystemCollector(
        proc_root=tmp_path,
        runner=runner,
        cpu_sample_seconds=0,
    )
    top, source = collector._read_top_processes()
    assert source == "/proc"
    assert [process.pid for process in top] == [2, 1]
    assert top[0].memory_bytes is not None


def test_network_rates_use_collector_state(tmp_path: Path) -> None:
    net_dir = tmp_path / "net"
    net_dir.mkdir()
    (net_dir / "dev").write_text(NET_DEV)

    times = iter([100.0, 110.0])
    collector = SystemCollector(
        proc_root=tmp_path,
        cpu_sample_seconds=0,
        monotonic=lambda: next(times),
    )
    warnings: list[str] = []
    first = collector._collect_network(warnings)
    assert first is not None
    assert first.rx_rate is None
    assert first.tx_rate is None

    updated = (
        "wlan0: 4000 20 0 0 0 0 0 0 1500 5 0 0 0 0 0 0\n"
    )
    (net_dir / "dev").write_text(updated)
    second = collector._collect_network(warnings)

    assert warnings == []
    assert second is not None
    assert second.rx_rate == 200.0
    assert second.tx_rate == 100.0
    assert second.rx_bytes == 4000
    assert second.tx_bytes == 1500


def test_network_rates_reset_when_source_changes(tmp_path: Path) -> None:
    net_dir = tmp_path / "proc" / "net"
    net_dir.mkdir(parents=True)
    (net_dir / "dev").write_text(NET_DEV)

    sysfs = tmp_path / "sys"
    statistics = sysfs / "wlan0" / "statistics"
    statistics.mkdir(parents=True)
    (statistics / "rx_bytes").write_text("100000\n")
    (statistics / "tx_bytes").write_text("200000\n")

    times = iter([100.0, 110.0, 120.0])
    collector = SystemCollector(
        proc_root=tmp_path / "proc",
        sysfs_net=sysfs,
        android_service=tmp_path / "no-service",
        cpu_sample_seconds=0,
        monotonic=lambda: next(times),
    )
    warnings: list[str] = []

    first = collector._collect_network(warnings)
    assert first is not None
    assert first.source == "/proc/net/dev"

    (net_dir / "dev").unlink()
    second = collector._collect_network(warnings)
    assert second is not None
    assert second.source == "sysfs"
    assert second.rx_bytes == 100000
    assert second.rx_rate is None
    assert second.tx_rate is None

    (statistics / "rx_bytes").write_text("110000\n")
    (statistics / "tx_bytes").write_text("220000\n")
    third = collector._collect_network(warnings)
    assert third is not None
    assert third.rx_rate == 1000.0
    assert third.tx_rate == 2000.0
    assert warnings == []


def test_network_falls_back_to_android_netstats(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    service = tmp_path / "service"
    service.write_text("")

    def parcel(rx: int, tx: int) -> str:
        return "\n".join(
            [
                "Result: Parcel(",
                f"0x00000000: 00000000 00000001 00000024 {rx & 0xFFFFFFFF:08x} '....'",
                f"0x00000010: {rx >> 32:08x} 00000000 00000000 {tx & 0xFFFFFFFF:08x} '....'",
                f"0x00000020: {tx >> 32:08x} 00000000 00000000 00000000 '....'",
                ")",
            ]
        )

    outputs = iter(
        [
            parcel(1000, 500),
            parcel(4000, 1500),
        ]
    )
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...]) -> str:
        calls.append(args)
        assert args[0] == str(service)
        return next(outputs)

    times = iter([100.0, 110.0])
    collector = SystemCollector(
        paths=(tmp_path,),
        proc_root=proc,
        sysfs_net=tmp_path / "no-sysfs",
        android_service=service,
        runner=runner,
        cpu_sample_seconds=0,
        monotonic=lambda: next(times),
    )
    warnings: list[str] = []

    first = collector._collect_network(warnings)
    second = collector._collect_network(warnings)

    assert warnings == []
    assert first is not None and second is not None
    assert first.source == "android netstats"
    assert first.rx_rate is None
    assert second.rx_bytes == 4000
    assert second.tx_bytes == 1500
    assert second.rx_rate == 300.0
    assert second.tx_rate == 100.0
    assert calls == [
        (str(service), "call", "netstats", "13"),
        (str(service), "call", "netstats", "13"),
    ]


def test_network_reports_all_sources_when_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()

    def runner(args: tuple[str, ...]) -> str:
        raise RuntimeError("not supported")

    collector = SystemCollector(
        paths=(tmp_path,),
        proc_root=proc,
        sysfs_net=tmp_path / "no-sysfs",
        android_service=tmp_path / "no-service",
        runner=runner,
        cpu_sample_seconds=0,
        monotonic=lambda: 100.0,
    )
    warnings: list[str] = []
    assert collector._collect_network(warnings) is None
    assert len(warnings) == 1
    assert "/proc/net/dev unavailable" in warnings[0]
    assert "sysfs unavailable" in warnings[0]
    assert "ip" in warnings[0]


def test_detailed_collection_includes_live_metrics(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "loadavg").write_text("0.10 0.20 0.30 1/100 42\n")
    (proc / "uptime").write_text("124.08 932.76\n")
    (proc / "net").mkdir()
    (proc / "net" / "dev").write_text(NET_DEV)
    add_proc_process(proc, 10, "R", "python", resident_pages=20)
    add_proc_process(proc, 11, "S", "bash", resident_pages=10)

    def runner(args: tuple[str, ...]) -> str:
        if args[0] == "free":
            return FREE_BYTES
        if args[0] == "ps":
            return PS_OUTPUT
        if args[0] == "termux-battery-status":
            return BATTERY_JSON
        raise AssertionError(f"unexpected command: {args}")

    collector = SystemCollector(
        paths=(tmp_path,),
        proc_root=proc,
        runner=runner,
        cpu_sample_seconds=0,
        monotonic=lambda: 100.0,
    )
    snapshot = collector.collect(detailed=True)

    assert snapshot.network is not None
    assert snapshot.network.rx_bytes == 2000
    assert snapshot.network.interfaces == 1
    assert snapshot.processes is not None
    assert snapshot.processes.total == 2
    assert snapshot.processes.running == 1
    assert snapshot.processes.top[0].pid == 789
    assert snapshot.processes.source == "ps"
    assert snapshot.battery is not None
    assert snapshot.battery.percentage == 45
    assert snapshot.battery.source == "termux-battery-status"
    assert snapshot.warnings == ()


@pytest.mark.skipif(not Path("/proc/meminfo").exists(), reason="requires Linux /proc")
def test_real_snapshot_on_this_host() -> None:
    snapshot = SystemCollector(cpu_sample_seconds=0, battery_command=None).collect()
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
