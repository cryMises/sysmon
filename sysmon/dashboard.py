"""Rich rendering for a :class:`sysmon.models.Snapshot`."""

from __future__ import annotations

from datetime import datetime

from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .formatting import (
    format_bytes,
    format_duration,
    format_load,
    format_percent,
)
from .models import CpuStats, DiskStats, MemoryStats, Snapshot, UptimeStats


def render_dashboard(
    snapshot: Snapshot,
    *,
    width: int = 100,
    ascii_bars: bool = False,
    live: bool = False,
    interval: float = 2.0,
) -> Group:
    """Build the complete dashboard renderable.

    Two-column layout is used on wider terminals; narrow terminals (common in
    Termux portrait mode) get a stacked layout.
    """

    wide = width >= 92
    bar_width = max(8, min(22, width // (6 if wide else 3)))

    cpu_panel = _cpu_panel(snapshot.cpu, bar_width, ascii_bars)
    memory_panel = _memory_panel(snapshot.memory, bar_width, ascii_bars)
    disk_panel = _disk_panel(snapshot.disks, bar_width, ascii_bars)
    uptime_panel = _uptime_panel(snapshot.uptime, snapshot.timestamp)

    parts: list[object] = [_header(snapshot), Rule(style="grey30")]

    if wide:
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(ratio=1)
        grid.add_column(ratio=1)
        grid.add_row(cpu_panel, memory_panel)
        grid.add_row(disk_panel, uptime_panel)
        parts.append(grid)
    else:
        parts.extend([cpu_panel, memory_panel, disk_panel, uptime_panel])

    if snapshot.warnings:
        parts.append(_warnings_panel(snapshot.warnings))

    parts.append(_footer(live=live, interval=interval))
    return Group(*parts)


def _header(snapshot: Snapshot) -> Group:
    title = Text.assemble(
        ("sysmon", "bold bright_cyan"),
        ("  system monitor", "dim"),
    )
    updated = datetime.fromtimestamp(snapshot.timestamp).astimezone()
    timestamp = Text(updated.strftime("%Y-%m-%d %H:%M:%S"), style="dim")

    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(justify="right", no_wrap=True)
    grid.add_row(title, timestamp)

    context = Text(
        f"{snapshot.hostname} · {snapshot.os_name} · {snapshot.machine}",
        style="dim",
        no_wrap=True,
        overflow="ellipsis",
    )
    return Group(grid, context)


def _cpu_panel(
    cpu: CpuStats | None, bar_width: int, ascii_bars: bool
) -> Panel:
    if cpu is None:
        body = Text("CPU data unavailable", style="yellow")
        return _panel("CPU", body, "cyan")

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(no_wrap=True, min_width=11)
    table.add_column(ratio=1)

    load = cpu.load
    load_text = Text.assemble(
        (format_load(load.one), "bold"),
        (" / ", "dim"),
        (format_load(load.five), "bold"),
        (" / ", "dim"),
        (format_load(load.fifteen), "bold"),
    )
    table.add_row(Text("load 1/5/15", style="dim"), load_text)
    table.add_row(
        Text("usage", style="dim"),
        _meter(cpu.usage_percent, bar_width, ascii_bars),
    )
    table.add_row(
        Text("cores", style="dim"),
        Text(str(cpu.cores) if cpu.cores else "n/a"),
    )
    return _panel("CPU", table, "cyan", cpu.source)


def _memory_panel(
    memory: MemoryStats | None, bar_width: int, ascii_bars: bool
) -> Panel:
    if memory is None:
        body = Text("Memory data unavailable", style="yellow")
        return _panel("Memory", body, "magenta")

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(no_wrap=True, min_width=5)
    table.add_column(ratio=1)

    table.add_row(
        Text("RAM", style="bold"),
        _meter(memory.used_percent, bar_width, ascii_bars),
    )
    table.add_row(
        "",
        Text(
            f"{format_bytes(memory.used_bytes)} used / "
            f"{format_bytes(memory.total_bytes)} total",
            style="dim",
            overflow="fold",
        ),
    )

    if memory.swap_total_bytes:
        table.add_row(
            Text("SWAP", style="bold"),
            _meter(memory.swap_percent, bar_width, ascii_bars),
        )
        table.add_row(
            "",
            Text(
                f"{format_bytes(memory.swap_used_bytes)} used / "
                f"{format_bytes(memory.swap_total_bytes)} total",
                style="dim",
                overflow="fold",
            ),
        )

    return _panel("Memory", table, "magenta", memory.source)


def _disk_panel(
    disks: tuple[DiskStats, ...], bar_width: int, ascii_bars: bool
) -> Panel:
    if not disks:
        body = Text("Disk usage unavailable", style="yellow")
        return _panel("Disk", body, "blue")

    rows: list[object] = []
    for index, disk in enumerate(disks):
        if index:
            rows.append(Text(""))
        rows.append(Text(disk.path, style="bold", overflow="fold"))
        rows.append(_meter(disk.used_percent, bar_width, ascii_bars))
        rows.append(
            Text(
                f"{format_bytes(disk.used_bytes)} / "
                f"{format_bytes(disk.total_bytes)} used · "
                f"{format_bytes(disk.free_bytes)} free",
                style="dim",
                overflow="fold",
            )
        )

    sources = ", ".join(sorted({disk.source for disk in disks}))
    return _panel("Disk", Group(*rows), "blue", sources)


def _uptime_panel(uptime: UptimeStats | None, now: float) -> Panel:
    if uptime is None:
        body = Text("Uptime unavailable", style="yellow")
        return _panel("Uptime", body, "green")

    booted = datetime.fromtimestamp(now - uptime.seconds).astimezone()
    body = Group(
        Text(format_duration(uptime.seconds), style="bold green"),
        Text(f"booted {booted:%Y-%m-%d %H:%M}", style="dim"),
    )
    return _panel("Uptime", body, "green", uptime.source)


def _warnings_panel(warnings: tuple[str, ...]) -> Panel:
    body = Group(
        *(
            Text(f"• {warning}", style="yellow", overflow="fold")
            for warning in warnings
        )
    )
    return Panel(
        body,
        title=Text("Warnings", style="bold yellow"),
        border_style="yellow",
        padding=(0, 1),
    )


def _footer(*, live: bool, interval: float) -> Text:
    if live:
        return Text.assemble(
            ("Ctrl+C", "bold"),
            " to quit",
            ("  ·  ", "dim"),
            (f"refreshing every {interval:g}s", "dim"),
        )
    return Text(
        "Run with --watch for live updates  ·  --json for machine-readable output",
        style="dim",
        overflow="fold",
    )


def _panel(
    title: str,
    body: object,
    border_style: str,
    source: str | None = None,
) -> Panel:
    subtitle = (
        Text(f"src: {source}", style="dim", overflow="ellipsis")
        if source
        else None
    )
    return Panel(
        body,
        title=Text(title, style=f"bold {border_style}"),
        title_align="left",
        subtitle=subtitle,
        subtitle_align="left",
        border_style=border_style,
        padding=(0, 1),
    )


def _meter(percent: float | None, width: int, ascii_bars: bool) -> Text:
    if percent is None:
        return Text("n/a", style="dim")

    percent = max(0.0, min(100.0, percent))
    style = _meter_style(percent)
    filled = int(round(width * percent / 100.0))
    if 0 < percent < 100:
        filled = max(1, min(width - 1, filled))
    elif percent >= 100:
        filled = width
    else:
        filled = 0

    full = "#" if ascii_bars else "█"
    empty = "-" if ascii_bars else "░"

    line = Text()
    line.append(full * filled, style=style)
    line.append(empty * (width - filled), style="grey37")
    line.append(" ")
    line.append(format_percent(percent), style=style)
    return line


def _meter_style(percent: float) -> str:
    if percent >= 90:
        return "bold red"
    if percent >= 70:
        return "yellow"
    return "green"
