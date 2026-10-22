from __future__ import annotations

from dataclasses import replace

from rich.console import Console

from sysmon.dashboard import render_dashboard
from sysmon.models import (
    MetricThreshold,
    NetworkInterfaceStats,
    Snapshot,
    Thresholds,
    TrendSample,
)


def _render(snapshot: Snapshot, width: int = 100, **kwargs: object) -> str:
    console = Console(
        record=True,
        width=width,
        force_terminal=False,
        color_system=None,
        highlight=False,
    )
    console.print(
        render_dashboard(snapshot, width=width, **kwargs)  # type: ignore[arg-type]
    )
    return console.export_text()


def test_dashboard_shows_every_required_metric(sample_snapshot: Snapshot) -> None:
    output = _render(sample_snapshot, width=110)

    assert "sysmon" in output
    assert "termux" in output
    assert "Ubuntu 26.04.1 LTS" in output
    assert "CPU" in output
    assert "1.25 / 0.75 / 0.50" in output
    assert "37.5%" in output
    assert "Memory" in output
    assert "3.0 GiB used / 8.0 GiB total" in output
    assert "Disk" in output
    assert "42.0%" in output
    assert "Uptime" in output
    assert "1d 1h 1m" in output
    assert "Battery" in output
    assert "45.0%" in output
    assert "Discharging · Unplugged" in output
    assert "37.5°C" in output
    assert "Good" in output
    assert "Li-poly" in output
    assert "3.05 W" in output
    assert "~2h 30m left" in output
    assert "src: termux-battery-status" in output
    assert "CPU 0-3" in output
    assert "1.80 GHz" in output
    assert "2.20 GHz" in output
    assert "src: sysfs cpufreq" not in output
    assert "Warnings" not in output
    assert "Alerts" not in output


def test_narrow_terminal_stacks_panels(sample_snapshot: Snapshot) -> None:
    output = _render(sample_snapshot, width=60)

    assert output.index("CPU") < output.index("Memory") < output.index("Disk")
    assert output.index("Disk") < output.index("Uptime")
    assert output.index("Uptime") < output.index("Battery")
    assert "3.0 GiB used / 8.0 GiB total" in output


def test_ascii_bars_avoid_unicode_blocks(sample_snapshot: Snapshot) -> None:
    output = _render(sample_snapshot, width=100, ascii_bars=True)
    assert "#" in output
    assert "█" not in output


def test_warnings_are_rendered_literally(sample_snapshot: Snapshot) -> None:
    snapshot = replace(
        sample_snapshot,
        warnings=("Memory: [bold]not available[/]",),
    )
    output = _render(snapshot, width=100)
    assert "Warnings" in output
    assert "[bold]not available[/]" in output


def test_missing_sections_render_without_crashing(sample_snapshot: Snapshot) -> None:
    snapshot = replace(
        sample_snapshot,
        cpu=None,
        memory=None,
        disks=(),
        uptime=None,
        battery=None,
        warnings=("Everything unavailable",),
    )
    output = _render(snapshot, width=100)
    assert "CPU data unavailable" in output
    assert "Memory data unavailable" in output
    assert "Disk usage unavailable" in output
    assert "Uptime unavailable" in output
    assert "Battery" not in output


def test_live_mode_adds_network_process_and_session_details(
    live_snapshot: Snapshot,
) -> None:
    output = _render(
        live_snapshot,
        width=110,
        live=True,
        sample=4,
        session_seconds=12,
    )

    assert "Network" in output
    assert "RX" in output
    assert "1.5 KiB/s" in output
    assert "512 B/s" in output
    assert "wlan0" in output
    assert "rmnet0" in output
    assert "1.4 KiB/s" in output
    assert "400 B/s" in output
    assert "2 interfaces" in output
    assert "Processes" in output
    assert "2 running · 42 processes" in output
    assert "python" in output
    assert "12.5%" in output
    assert "512.0 MiB" in output
    assert "sample #4" in output
    assert "watching 12s" in output


def test_live_panels_are_hidden_in_one_shot_mode(live_snapshot: Snapshot) -> None:
    output = _render(live_snapshot, width=110, live=False)
    assert "Network" not in output
    assert "Processes" not in output
    assert "sample #" not in output


def test_live_missing_network_and_process_data(sample_snapshot: Snapshot) -> None:
    output = _render(sample_snapshot, width=100, live=True, sample=1)
    assert "Network data unavailable" in output
    assert "Process data unavailable" in output
    assert "rate pending" not in output


def test_live_narrow_layout_stacks_extra_panels(live_snapshot: Snapshot) -> None:
    output = _render(
        live_snapshot, width=60, live=True, sample=2, session_seconds=5
    )
    assert (
        output.index("Uptime")
        < output.index("Battery")
        < output.index("Network")
        < output.index("Processes")
    )
    assert "watching" in output


def test_live_mode_renders_trend_strips(live_snapshot: Snapshot) -> None:
    trends = (
        TrendSample(
            timestamp=1.0,
            cpu_percent=10.0,
            memory_percent=40.0,
            rx_rate=100.0,
            tx_rate=50.0,
            battery_percent=44.0,
        ),
        TrendSample(
            timestamp=2.0,
            cpu_percent=30.0,
            memory_percent=50.0,
            rx_rate=300.0,
            tx_rate=150.0,
            battery_percent=40.0,
        ),
    )
    output = _render(
        live_snapshot, width=110, live=True, trends=trends
    )

    assert "Trends" in output
    assert "in-memory history" in output
    assert "max 30.0%" in output
    assert "peak 300 B/s" in output
    assert "low 40.0%" in output
    assert "▂" in output


def test_ascii_trends_use_ascii_sparklines(live_snapshot: Snapshot) -> None:
    trends = (
        TrendSample(timestamp=1.0, cpu_percent=0.0),
        TrendSample(timestamp=2.0, cpu_percent=100.0),
    )
    output = _render(
        live_snapshot,
        width=100,
        live=True,
        ascii_bars=True,
        trends=trends,
    )
    assert "Trends" in output
    assert "█" not in output
    assert "." in output


def test_threshold_alerts_are_rendered(sample_snapshot: Snapshot) -> None:
    assert sample_snapshot.cpu is not None
    assert sample_snapshot.battery is not None
    snapshot = replace(
        sample_snapshot,
        cpu=replace(sample_snapshot.cpu, usage_percent=95.0),
        battery=replace(sample_snapshot.battery, percentage=9.0),
    )
    thresholds = Thresholds(
        cpu=MetricThreshold(50.0, 90.0),
        memory=MetricThreshold(80.0, 92.0),
        disk=MetricThreshold(85.0, 95.0),
        battery=MetricThreshold(30.0, 15.0),
    )
    output = _render(snapshot, width=110, thresholds=thresholds)

    assert "Alerts" in output
    assert "CPU 95.0% ≥ 90.0%" in output
    assert "Battery 9.0% ≤ 15.0%" in output


def test_process_filter_feedback_is_rendered(live_snapshot: Snapshot) -> None:
    assert live_snapshot.processes is not None
    processes = replace(
        live_snapshot.processes,
        top=(),
        filter="does-not-match",
    )
    snapshot = replace(live_snapshot, processes=processes)
    output = _render(snapshot, width=110, live=True)

    assert "filter 'does-not-match'" in output
    assert "No matching processes" in output


def test_battery_cache_age_is_rendered(sample_snapshot: Snapshot) -> None:
    assert sample_snapshot.battery is not None
    snapshot = replace(
        sample_snapshot,
        battery=replace(sample_snapshot.battery, cache_age_seconds=12.0),
    )
    output = _render(snapshot, width=100)
    assert "cached 12s ago" in output


def test_network_details_are_capped_at_three_rows(
    live_snapshot: Snapshot,
) -> None:
    assert live_snapshot.network is not None
    details = tuple(
        NetworkInterfaceStats(
            name=f"if{index}",
            rx_bytes=(10 - index) * 1024,
            tx_bytes=0,
            rx_rate=float(index),
            tx_rate=0.0,
        )
        for index in range(5)
    )
    network = replace(live_snapshot.network, interface_details=details)
    snapshot = replace(live_snapshot, network=network)
    output = _render(snapshot, width=110, live=True)

    assert "if0" in output
    assert "if1" in output
    assert "if2" in output
    assert "if3" not in output
    assert "+2 more" in output
