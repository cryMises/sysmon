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
    assert "Warnings" not in output


def test_narrow_terminal_stacks_panels(sample_snapshot: Snapshot) -> None:
    output = _render(sample_snapshot, width=60)

    assert output.index("CPU") < output.index("Memory") < output.index("Disk")
    assert output.index("Disk") < output.index("Uptime")
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
        warnings=("Everything unavailable",),
    )
    output = _render(snapshot, width=100)
    assert "CPU data unavailable" in output
    assert "Memory data unavailable" in output
    assert "Disk usage unavailable" in output
    assert "Uptime unavailable" in output
