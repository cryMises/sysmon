"""Shared test fixtures."""

from __future__ import annotations

import pytest

from sysmon.models import (
    CpuStats,
    DiskStats,
    LoadAverage,
    MemoryStats,
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
        warnings=(),
        hostname="termux",
        os_name="Ubuntu 26.04.1 LTS",
        machine="aarch64",
    )
