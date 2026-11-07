"""Rich rendering for a :class:`sysmon.models.Snapshot`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .formatting import (
    format_bytes,
    format_duration,
    format_frequency,
    format_load,
    format_percent,
    format_rate,
    format_sparkline,
)
from .models import (
    BatteryStats,
    CpuClusterStats,
    CpuStats,
    DiskStats,
    DockerStats,
    MemoryStats,
    MetricThreshold,
    NetworkInterfaceStats,
    NetworkStats,
    ProcessStats,
    Snapshot,
    Thresholds,
    TrendSample,
    UptimeStats,
)


def render_dashboard(
    snapshot: Snapshot,
    *,
    width: int = 100,
    ascii_bars: bool = False,
    live: bool = False,
    interval: float = 2.0,
    sample: int | None = None,
    session_seconds: float | None = None,
    trends: Sequence[TrendSample] | None = None,
    thresholds: Thresholds | None = None,
) -> Group:
    """Build the complete dashboard renderable.

    Two-column layout is used on wider terminals; narrow terminals (common in
    Termux portrait mode) get a stacked layout. Network, process, and trend
    panels are only shown in live mode.
    """

    wide = width >= 92
    bar_width = max(8, min(22, width // (6 if wide else 3)))
    thresholds = thresholds or Thresholds()

    cpu_panel = _cpu_panel(
        snapshot.cpu, bar_width, ascii_bars, thresholds.cpu
    )
    memory_panel = _memory_panel(
        snapshot.memory, bar_width, ascii_bars, thresholds.memory
    )
    disk_panel = _disk_panel(
        snapshot.disks, bar_width, ascii_bars, thresholds.disk
    )
    uptime_panel = _uptime_panel(snapshot.uptime, snapshot.timestamp)
    battery_panel = _battery_panel(
        snapshot.battery, bar_width, ascii_bars, thresholds.battery
    )
    network_panel = _network_panel(snapshot.network)
    processes_panel = _processes_panel(snapshot.processes)
    docker_panel = _docker_panel(snapshot.docker)
    trends_panel = _trends_panel(trends, width, ascii_bars) if live else None
    alerts = _collect_alerts(snapshot, thresholds)

    parts: list[RenderableType] = [_header(snapshot), Rule(style="grey30")]

    if wide:
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(ratio=1)
        grid.add_column(ratio=1)
        grid.add_row(cpu_panel, memory_panel)
        grid.add_row(disk_panel, uptime_panel)
        parts.append(grid)
    else:
        parts.extend([cpu_panel, memory_panel, disk_panel, uptime_panel])

    if alerts:
        parts.append(_alerts_panel(alerts))
    if battery_panel is not None:
        parts.append(battery_panel)
    if trends_panel is not None:
        parts.append(trends_panel)
    if live:
        if wide:
            live_grid = Table.grid(expand=True, padding=(0, 1))
            live_grid.add_column(ratio=1)
            live_grid.add_column(ratio=1)
            live_grid.add_row(network_panel, processes_panel)
            parts.append(live_grid)
        else:
            parts.extend([network_panel, processes_panel])
        if docker_panel is not None:
            parts.append(docker_panel)

    if snapshot.warnings:
        parts.append(_warnings_panel(snapshot.warnings))

    parts.append(
        _footer(
            live=live,
            interval=interval,
            sample=sample,
            session_seconds=session_seconds,
        )
    )
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

    context = Text.assemble(
        (snapshot.hostname, "bold"),
        (" · ", "dim"),
        (f"{snapshot.os_name} · {snapshot.machine}", "dim"),
        overflow="ellipsis",
        no_wrap=True,
    )
    return Group(grid, context)


def _cpu_panel(
    cpu: CpuStats | None,
    bar_width: int,
    ascii_bars: bool,
    threshold: MetricThreshold,
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
        _meter(
            cpu.usage_percent,
            bar_width,
            ascii_bars,
            warning=threshold.warning,
            critical=threshold.critical,
        ),
    )
    table.add_row(
        Text("cores", style="dim"),
        Text(f"{cpu.cores:g}" if cpu.cores else "n/a"),
    )
    for cluster in cpu.clusters:
        table.add_row(
            Text(cluster.label, style="dim"),
            _cluster_line(cluster),
        )
    return _panel("CPU", table, "cyan", cpu.source)


def _cluster_line(cluster: CpuClusterStats) -> Text:
    line = Text(format_frequency(cluster.current_khz), style="bold")
    if cluster.max_khz is not None and cluster.max_khz != cluster.current_khz:
        line.append(" / ", style="dim")
        line.append(format_frequency(cluster.max_khz), style="dim")
        line.append(" max", style="dim")
    return line


def _memory_panel(
    memory: MemoryStats | None,
    bar_width: int,
    ascii_bars: bool,
    threshold: MetricThreshold,
) -> Panel:
    if memory is None:
        body = Text("Memory data unavailable", style="yellow")
        return _panel("Memory", body, "magenta")

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(no_wrap=True, min_width=5)
    table.add_column(ratio=1)

    table.add_row(
        Text("RAM", style="bold"),
        _meter(
            memory.used_percent,
            bar_width,
            ascii_bars,
            warning=threshold.warning,
            critical=threshold.critical,
        ),
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
            _meter(
                memory.swap_percent,
                bar_width,
                ascii_bars,
                warning=threshold.warning,
                critical=threshold.critical,
            ),
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
    disks: tuple[DiskStats, ...],
    bar_width: int,
    ascii_bars: bool,
    threshold: MetricThreshold,
) -> Panel:
    if not disks:
        body = Text("Disk usage unavailable", style="yellow")
        return _panel("Disk", body, "blue")

    rows: list[RenderableType] = []
    for index, disk in enumerate(disks):
        if index:
            rows.append(Text(""))
        rows.append(Text(disk.path, style="bold", overflow="fold"))
        rows.append(
            _meter(
                disk.used_percent,
                bar_width,
                ascii_bars,
                warning=threshold.warning,
                critical=threshold.critical,
            )
        )
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
        body: RenderableType = Text("Uptime unavailable", style="yellow")
        return _panel("Uptime", body, "green")

    booted = datetime.fromtimestamp(now - uptime.seconds).astimezone()
    body = Group(
        Text(format_duration(uptime.seconds), style="bold green"),
        Text(f"booted {booted:%Y-%m-%d %H:%M}", style="dim"),
    )
    return _panel("Uptime", body, "green", uptime.source)


def _battery_panel(
    battery: BatteryStats | None,
    bar_width: int,
    ascii_bars: bool,
    threshold: MetricThreshold,
) -> Panel | None:
    if battery is None or not battery.present:
        return None

    state = " · ".join(
        label
        for label in (
            _battery_label(battery.status),
            _battery_label(battery.plugged),
        )
        if label
    )

    meta: list[str] = []
    if battery.temperature_c is not None:
        meta.append(f"{battery.temperature_c:.1f}°C")
    health = _battery_label(battery.health)
    if health:
        meta.append(health)
    if battery.technology:
        meta.append(battery.technology)
    if battery.power_w is not None:
        meta.append(f"{battery.power_w:.2f} W")
    if battery.time_remaining_seconds is not None:
        meta.append(f"~{format_duration(battery.time_remaining_seconds)} left")
    if (
        battery.cache_age_seconds is not None
        and battery.cache_age_seconds >= 1.0
    ):
        meta.append(f"cached {format_duration(battery.cache_age_seconds)} ago")

    head = Table.grid(expand=True, padding=(0, 2))
    head.add_column(no_wrap=True)
    head.add_column(ratio=1)
    head.add_row(
        _meter(
            battery.percentage,
            bar_width,
            ascii_bars,
            warning=threshold.warning,
            critical=threshold.critical,
            inverted=True,
        ),
        Text(state, style="bold", overflow="fold"),
    )

    body: list[RenderableType] = [head]
    if meta:
        body.append(Text(" · ".join(meta), style="dim", overflow="fold"))
    elif not state:
        body.append(Text("Battery details unavailable", style="dim"))

    return _panel("Battery", Group(*body), "bright_green", battery.source)


def _battery_label(value: str | None) -> str | None:
    if not value:
        return None
    special = {"usb": "USB", "ac": "AC"}
    words = value.replace("_", " ").split()
    return " ".join(special.get(word.lower(), word.capitalize()) for word in words)


def _trends_panel(
    samples: Sequence[TrendSample] | None,
    width: int,
    ascii_bars: bool,
) -> Panel | None:
    if not samples:
        return None

    compact = width < 74
    full_spark_width = max(8, width - 37)
    spark_width = min(full_spark_width, max(1, len(samples)))
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(no_wrap=True, width=3)
    table.add_column(no_wrap=True, width=spark_width)
    table.add_column(no_wrap=True, ratio=1, overflow="ellipsis")

    rows: list[tuple[Text, str, Text]] = []
    candidates = (
        _trend_row(
            "CPU",
            [sample.cpu_percent for sample in samples],
            spark_width,
            ascii_bars,
            format_percent,
            maximum=100.0,
            extremum="max",
            compact=compact,
        ),
        _trend_row(
            "RAM",
            [sample.memory_percent for sample in samples],
            spark_width,
            ascii_bars,
            format_percent,
            maximum=100.0,
            extremum="max",
            compact=compact,
        ),
        _trend_row(
            "RX",
            [sample.rx_rate for sample in samples],
            spark_width,
            ascii_bars,
            format_rate,
            extremum="peak",
            compact=compact,
        ),
        _trend_row(
            "TX",
            [sample.tx_rate for sample in samples],
            spark_width,
            ascii_bars,
            format_rate,
            extremum="peak",
            compact=compact,
        ),
        _trend_row(
            "BAT",
            [sample.battery_percent for sample in samples],
            spark_width,
            ascii_bars,
            format_percent,
            maximum=100.0,
            extremum="low",
            compact=compact,
        ),
    )
    rows.extend(row for row in candidates if row is not None)
    if not rows:
        return None

    for row in rows:
        table.add_row(*row)
    return _panel("Trends", table, "bright_magenta", "in-memory history")


def _trend_row(
    label: str,
    values: Sequence[float | None],
    spark_width: int,
    ascii_bars: bool,
    formatter: Callable[[float | None], str],
    *,
    maximum: float | None = None,
    extremum: str,
    compact: bool,
) -> tuple[Text, str, Text] | None:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None

    spark = format_sparkline(
        values,
        spark_width,
        maximum=maximum,
        ascii_bars=ascii_bars,
    )
    detail = formatter(values[-1])
    if not compact:
        extreme = min(numeric) if extremum == "low" else max(numeric)
        detail = f"{detail}  {extremum} {formatter(float(extreme))}"
    return (
        Text(label, style="bold"),
        spark,
        Text(detail, style="dim"),
    )


def _collect_alerts(
    snapshot: Snapshot, thresholds: Thresholds
) -> list[tuple[str, str]]:
    alerts: list[tuple[str, str]] = []
    candidates = [
        _metric_alert(
            "CPU",
            snapshot.cpu.usage_percent if snapshot.cpu else None,
            thresholds.cpu,
        ),
        _metric_alert(
            "Memory",
            snapshot.memory.used_percent if snapshot.memory else None,
            thresholds.memory,
        ),
        _metric_alert(
            "Battery",
            snapshot.battery.percentage if snapshot.battery else None,
            thresholds.battery,
            inverted=True,
        ),
    ]

    disk_candidates = [
        (
            disk.path,
            disk.used_percent,
        )
        for disk in snapshot.disks
        if disk.used_percent is not None
    ]
    if disk_candidates:
        path, value = max(disk_candidates, key=lambda item: item[1])
        candidates.append(
            _metric_alert(f"Disk {path}", value, thresholds.disk)
        )

    alerts.extend(candidate for candidate in candidates if candidate is not None)
    return alerts


def _metric_alert(
    label: str,
    value: float | None,
    threshold: MetricThreshold,
    *,
    inverted: bool = False,
) -> tuple[str, str] | None:
    if value is None:
        return None
    if inverted:
        if value <= threshold.critical:
            return (
                "critical",
                (
                    f"{label} {format_percent(value)} ≤ "
                    f"{format_percent(threshold.critical)}"
                ),
            )
        if value <= threshold.warning:
            return (
                "warning",
                (
                    f"{label} {format_percent(value)} ≤ "
                    f"{format_percent(threshold.warning)}"
                ),
            )
        return None
    if value >= threshold.critical:
        return (
            "critical",
            (
                f"{label} {format_percent(value)} ≥ "
                f"{format_percent(threshold.critical)}"
            ),
        )
    if value >= threshold.warning:
        return (
            "warning",
            (
                f"{label} {format_percent(value)} ≥ "
                f"{format_percent(threshold.warning)}"
            ),
        )
    return None


def _alerts_panel(alerts: Sequence[tuple[str, str]]) -> Panel:
    styles = {"critical": "bold red", "warning": "yellow"}
    body = Group(
        *(
            Text(f"• {message}", style=styles.get(level, "yellow"), overflow="fold")
            for level, message in alerts
        )
    )
    border = "bold red" if any(level == "critical" for level, _ in alerts) else "yellow"
    return Panel(
        body,
        title=Text("Alerts", style=border),
        border_style=border,
        padding=(0, 1),
    )


def _network_panel(network: NetworkStats | None) -> Panel:
    if network is None:
        body = Text("Network data unavailable", style="yellow")
        return _panel("Network", body, "bright_blue")

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(no_wrap=True, min_width=3)
    table.add_column(ratio=1)
    table.add_row(
        Text("RX", style="bold bright_blue"),
        _network_line(network.rx_bytes, network.rx_rate),
    )
    table.add_row(
        Text("TX", style="bold bright_blue"),
        _network_line(network.tx_bytes, network.tx_rate),
    )
    for interface in _top_interfaces(network.interface_details):
        table.add_row(
            Text(interface.name, style="dim", no_wrap=True, overflow="ellipsis"),
            _interface_line(interface),
        )
    if network.interfaces:
        noun = "interface" if network.interfaces == 1 else "interfaces"
        extra = max(0, len(network.interface_details) - 3)
        suffix = f", +{extra} more" if extra > 0 else ""
        table.add_row("", Text(f"{network.interfaces} {noun}{suffix}", style="dim"))

    return _panel("Network", table, "bright_blue", network.source)


def _top_interfaces(
    interfaces: Sequence[NetworkInterfaceStats],
) -> tuple[NetworkInterfaceStats, ...]:
    ordered = sorted(
        interfaces,
        key=lambda interface: interface.rx_bytes + interface.tx_bytes,
        reverse=True,
    )
    return tuple(ordered[:3])


def _interface_line(interface: NetworkInterfaceStats) -> Text:
    line = Text()
    line.append("RX ", style="dim")
    if interface.rx_rate is None:
        line.append(format_bytes(interface.rx_bytes), style="bold")
        line.append(" total", style="dim")
    else:
        line.append(format_rate(interface.rx_rate), style="bold cyan")
    line.append("   TX ", style="dim")
    if interface.tx_rate is None:
        line.append(format_bytes(interface.tx_bytes), style="bold")
        line.append(" total", style="dim")
    else:
        line.append(format_rate(interface.tx_rate), style="bold cyan")
    return line


def _network_line(total: int, rate: float | None) -> Text:
    line = Text()
    line.append(format_bytes(total), style="bold")
    line.append(" total", style="dim")
    line.append("   ")
    if rate is None:
        line.append("rate pending", style="dim")
    else:
        line.append(format_rate(rate), style="bold cyan")
    return line


def _processes_panel(processes: ProcessStats | None) -> Panel:
    if processes is None:
        body: RenderableType = Text("Process data unavailable", style="yellow")
        return _panel("Processes", body, "bright_yellow")

    if processes.total is not None:
        counts: list[str] = []
        if processes.running is not None:
            counts.append(f"{processes.running} running")
        counts.append(f"{processes.total} processes")
        if processes.filter:
            counts.append(f"filter {processes.filter!r}")
        summary = Text(" · ".join(counts), style="dim")
    else:
        summary = Text("process counts unavailable", style="dim")

    if not processes.top:
        message = (
            "No matching processes"
            if processes.filter
            else "Top process list unavailable"
        )
        body = Group(summary, Text(message, style="dim"))
        return _panel("Processes", body, "bright_yellow", processes.source)

    table = Table(
        box=None,
        expand=True,
        show_header=True,
        header_style="dim",
        pad_edge=False,
        padding=(0, 1),
    )
    table.add_column("PID", justify="right", no_wrap=True, width=6)
    table.add_column("COMMAND", ratio=1, no_wrap=True, overflow="ellipsis")
    table.add_column("CPU", justify="right", no_wrap=True, width=7)
    table.add_column("MEM", justify="right", no_wrap=True, width=10)

    for process in processes.top:
        table.add_row(
            str(process.pid),
            Text(process.command, overflow="ellipsis", no_wrap=True),
            format_percent(process.cpu_percent),
            format_bytes(process.memory_bytes),
        )

    return _panel(
        "Processes",
        Group(summary, table),
        "bright_yellow",
        processes.source,
    )


def _docker_panel(docker: DockerStats | None) -> Panel | None:
    if docker is None or not docker.containers:
        return None

    noun = "container" if len(docker.containers) == 1 else "containers"
    summary = Text(f"{len(docker.containers)} running {noun}", style="dim")

    table = Table(
        box=None,
        expand=True,
        show_header=True,
        header_style="dim",
        pad_edge=False,
        padding=(0, 1),
    )
    table.add_column("CONTAINER", ratio=1, no_wrap=True, overflow="ellipsis")
    table.add_column("CPU", justify="right", no_wrap=True, width=7)
    table.add_column("MEM", justify="right", no_wrap=True, width=10)
    table.add_column("LIMIT", justify="right", no_wrap=True, width=10)
    table.add_column("MEM %", justify="right", no_wrap=True, width=6)

    for container in docker.containers:
        table.add_row(
            Text(container.name, overflow="ellipsis", no_wrap=True),
            format_percent(container.cpu_percent),
            format_bytes(container.memory_bytes),
            format_bytes(container.memory_limit_bytes),
            format_percent(container.memory_percent),
        )

    return _panel(
        "Docker",
        Group(summary, table),
        "bright_magenta",
        docker.source,
    )


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


def _footer(
    *,
    live: bool,
    interval: float,
    sample: int | None = None,
    session_seconds: float | None = None,
) -> Text:
    if not live:
        return Text(
            "Run with --watch for live updates  ·  --json for JSON",
            style="dim",
            overflow="fold",
        )

    parts: list[str | tuple[str, str]] = [
        ("Ctrl+C", "bold"),
        " to quit",
        ("  ·  ", "dim"),
        (f"refresh {interval:g}s", "dim"),
    ]
    if sample is not None:
        parts.extend([("  ·  ", "dim"), (f"sample #{sample}", "dim")])
    if session_seconds is not None:
        parts.extend(
            [("  ·  ", "dim"), (f"watching {format_duration(session_seconds)}", "dim")]
        )
    return Text.assemble(*parts, overflow="fold")


def _panel(
    title: str,
    body: RenderableType,
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


def _meter(
    percent: float | None,
    width: int,
    ascii_bars: bool,
    *,
    warning: float = 75.0,
    critical: float = 90.0,
    inverted: bool = False,
) -> Text:
    if percent is None:
        return Text("n/a", style="dim")

    percent = max(0.0, min(100.0, percent))
    style = _threshold_style(
        percent,
        warning=warning,
        critical=critical,
        inverted=inverted,
    )
    filled = round(width * percent / 100.0)
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
    line.append(format_percent(percent).rjust(6), style=f"{style} bold")
    return line


def _threshold_style(
    percent: float,
    *,
    warning: float,
    critical: float,
    inverted: bool = False,
) -> str:
    if inverted:
        if percent <= critical:
            return "bold red"
        if percent <= warning:
            return "yellow"
        return "green"
    if percent >= critical:
        return "bold red"
    if percent >= warning:
        return "yellow"
    return "green"
