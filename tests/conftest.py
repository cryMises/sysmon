"""Shared test fixtures."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sysmon.models import (
    BatteryStats,
    CpuClusterStats,
    CpuStats,
    DiskStats,
    LoadAverage,
    MemoryStats,
    NetworkInterfaceStats,
    NetworkStats,
    ProcessInfo,
    ProcessStats,
    Snapshot,
    UptimeStats,
)

GIB = 1024**3


@pytest.fixture
def sample_snapshot() -> Snapshot:
    return Snapshot(
        timestamp=1_767_000_000.0,
        cpu=CpuStats(
            load=LoadAverage(one=1.25, five=0.75, fifteen=0.50),
            usage_percent=37.5,
            cores=8,
            clusters=(
                CpuClusterStats(
                    label="CPU 0-3",
                    current_khz=1_800_000,
                    min_khz=400_000,
                    max_khz=2_200_000,
                ),
                CpuClusterStats(
                    label="CPU 4-7",
                    current_khz=2_400_000,
                    min_khz=600_000,
                    max_khz=3_200_000,
                ),
            ),
            source="/proc/loadavg + /proc/stat",
        ),
        memory=MemoryStats(
            total_bytes=8 * GIB,
            used_bytes=3 * GIB,
            available_bytes=5 * GIB,
            free_bytes=2 * GIB,
            swap_total_bytes=2 * GIB,
            swap_used_bytes=1536 * 1024**2,
            source="/proc/meminfo",
        ),
        disks=(
            DiskStats(
                path="/",
                total_bytes=100 * GIB,
                used_bytes=42 * GIB,
                free_bytes=58 * GIB,
                source="statvfs",
            ),
        ),
        uptime=UptimeStats(seconds=90_061, source="/proc/uptime"),
        network=None,
        processes=None,
        warnings=(),
        hostname="termux",
        os_name="Ubuntu 26.04.1 LTS",
        machine="aarch64",
        battery=BatteryStats(
            percentage=45,
            status="DISCHARGING",
            plugged="UNPLUGGED",
            temperature_c=37.5,
            health="GOOD",
            technology="Li-poly",
            voltage_mv=3813,
            current_ua=801000,
            current_average_ua=-3000,
            charge_counter_uah=2_015_000,
            cache_age_seconds=0.0,
        ),
    )


@pytest.fixture
def live_snapshot(sample_snapshot: Snapshot) -> Snapshot:
    return replace(
        sample_snapshot,
        network=NetworkStats(
            rx_bytes=5 * GIB,
            tx_bytes=2 * GIB,
            rx_rate=1536.0,
            tx_rate=512.0,
            interfaces=2,
            interface_details=(
                NetworkInterfaceStats(
                    name="rmnet0",
                    rx_bytes=1 * GIB,
                    tx_bytes=1 * GIB,
                    rx_rate=136.0,
                    tx_rate=112.0,
                ),
                NetworkInterfaceStats(
                    name="wlan0",
                    rx_bytes=4 * GIB,
                    tx_bytes=1 * GIB,
                    rx_rate=1400.0,
                    tx_rate=400.0,
                ),
            ),
            source="/proc/net/dev",
        ),
        processes=ProcessStats(
            total=42,
            running=2,
            top=(
                ProcessInfo(
                    pid=1234,
                    command="python",
                    cpu_percent=12.5,
                    memory_bytes=512 * 1024**2,
                ),
                ProcessInfo(
                    pid=5678,
                    command="bash",
                    cpu_percent=1.0,
                    memory_bytes=64 * 1024**2,
                ),
            ),
            source="ps",
        ),
    )
