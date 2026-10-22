from __future__ import annotations

from dataclasses import replace

from rich.console import Console

from sysmon.dashboard import render_dashboard
from sysmon.models import Snapshot


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
    assert "src: termux-battery-status" in output
    assert "Warnings" not in output


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
