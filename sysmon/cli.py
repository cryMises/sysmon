"""Command-line entry point for sysmon."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import deque
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.text import Text

from . import __version__
from .collectors import SystemCollector
from .config import AppConfig, ConfigError, load_config
from .dashboard import render_dashboard
from .models import Thresholds, TrendSample

_UNSET = object()


def positive_interval(value: str) -> float:
    try:
        interval = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if interval < 0.5:
        raise argparse.ArgumentTypeError("must be at least 0.5 seconds")
    return interval


def process_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= count <= 50:
        raise argparse.ArgumentTypeError("must be between 1 and 50")
    return count


def trend_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 2 <= count <= 1000:
        raise argparse.ArgumentTypeError("must be between 2 and 1000")
    return count


def sample_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if count < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return count


def process_filter(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    try:
        re.compile(text)
    except re.error as exc:
        raise argparse.ArgumentTypeError(
            f"must be a valid regular expression: {exc}"
        ) from exc
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sysmon",
        description=(
            "Read-only Linux system monitor with a Rich dashboard. "
            "No root permissions required."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help=(
            "refresh continuously with live network/process/trend details "
            "until Ctrl+C; combine with --json for JSON Lines (default: one "
            "snapshot)"
        ),
    )
    mode.add_argument(
        "--once",
        action="store_true",
        help="print one snapshot and exit (default)",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=positive_interval,
        default=None,
        metavar="SECONDS",
        help="watch refresh interval in seconds (default: 2.0, minimum: 0.5)",
    )
    parser.add_argument(
        "-p",
        "--path",
        dest="paths",
        action="append",
        type=Path,
        metavar="PATH",
        help="filesystem path to report; repeat for multiple paths (default: /)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help="JSON configuration file (CLI options override its values)",
    )
    parser.add_argument(
        "--top",
        type=process_count,
        default=None,
        metavar="N",
        help="number of processes to show (default: 5, maximum: 50)",
    )
    parser.add_argument(
        "--sort",
        choices=("cpu", "mem", "pid"),
        default=None,
        help="process sort order (default: cpu)",
    )
    parser.add_argument(
        "--filter",
        type=process_filter,
        default=_UNSET,
        metavar="REGEX",
        help=(
            "only show processes whose command matches this regular expression; "
            "an empty value clears a configured filter"
        ),
    )
    parser.add_argument(
        "--full-command",
        action="store_true",
        help="show the full command line instead of only the process name",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "print raw data as JSON; with --watch, emit one compact JSON object "
            "per refresh (JSON Lines)"
        ),
    )
    parser.add_argument(
        "--no-battery",
        action="store_true",
        help="skip the termux-battery-status query",
    )
    parser.add_argument(
        "--no-docker",
        action="store_true",
        help="skip the docker stats query for running containers",
    )
    parser.add_argument(
        "--no-trends",
        action="store_true",
        help="disable the in-memory watch-mode trend strips",
    )
    parser.add_argument(
        "--trend-samples",
        type=trend_count,
        default=None,
        metavar="N",
        help="number of trend samples to retain (default: 60, range: 2-1000)",
    )
    parser.add_argument(
        "--count",
        type=sample_count,
        default=None,
        metavar="N",
        help="stop watch/JSON Lines after N samples",
    )
    parser.add_argument(
        "--ascii",
        action="store_true",
        help="use ASCII bars and sparklines instead of Unicode characters",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable colors",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = (
            load_config(args.config.expanduser())
            if args.config is not None
            else AppConfig()
        )
    except ConfigError as exc:
        parser.error(str(exc))

    interval = args.interval if args.interval is not None else config.interval
    if args.paths is not None:
        paths = tuple(path.expanduser() for path in args.paths)
    else:
        paths = config.paths or (Path("/"),)
    process_limit = (
        args.top if args.top is not None else config.processes.limit
    )
    process_sort = (
        args.sort if args.sort is not None else config.processes.sort
    )
    process_pattern = (
        config.processes.filter
        if args.filter is _UNSET
        else args.filter
    )
    full_command = args.full_command or config.processes.full_command
    trends_enabled = config.trends.enabled and not args.no_trends
    trend_samples = (
        args.trend_samples
        if args.trend_samples is not None
        else config.trends.samples
    )
    ascii_bars = args.ascii or config.ascii
    no_color = args.no_color or config.no_color

    battery_command = (
        ("termux-battery-status",)
        if config.battery and not args.no_battery
        else None
    )
    docker_enabled = config.docker and not args.no_docker
    collector = SystemCollector(
        paths=paths,
        process_limit=process_limit,
        process_sort=process_sort,
        process_filter=process_pattern,
        full_command=full_command,
        battery_command=battery_command,
        docker_command=(
            ("docker", "stats", "--no-stream", "--format", "{{json .}}")
            if docker_enabled
            else None
        ),
    )
    console = Console(
        highlight=False,
        no_color=True if no_color else None,
    )

    try:
        if args.json and not args.watch:
            print(
                json.dumps(
                    collector.collect(detailed=True).to_dict(),
                    indent=2,
                )
            )
            return 0

        if args.watch:
            if args.json:
                return _watch_json(collector, interval=interval, count=args.count)
            return _watch(
                collector,
                console,
                interval=interval,
                ascii_bars=ascii_bars,
                thresholds=config.thresholds,
                trends_enabled=trends_enabled,
                trend_samples=trend_samples,
                count=args.count,
            )

        snapshot = collector.collect()
        console.print(
            render_dashboard(
                snapshot,
                width=console.width,
                ascii_bars=ascii_bars,
                thresholds=config.thresholds,
            )
        )
        return 0
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


def _watch(
    collector: SystemCollector,
    console: Console,
    *,
    interval: float,
    ascii_bars: bool,
    thresholds: Thresholds,
    trends_enabled: bool,
    trend_samples: int,
    count: int | None,
) -> int:
    if not console.is_terminal:
        console.print(
            Text(
                "Watch mode needs an interactive terminal; showing one snapshot.",
                style="yellow",
            )
        )
        console.print(
            render_dashboard(
                collector.collect(),
                width=console.width,
                ascii_bars=ascii_bars,
                thresholds=thresholds,
            )
        )
        return 0

    history: deque[TrendSample] = deque(maxlen=trend_samples)
    samples = 0
    try:
        with Live(
            console=console,
            screen=True,
            auto_refresh=False,
            refresh_per_second=4,
            vertical_overflow="ellipsis",
        ) as live:
            started = time.monotonic()
            while count is None or samples < count:
                cycle_started = time.monotonic()
                snapshot = collector.collect(detailed=True)
                samples += 1
                if trends_enabled:
                    history.append(TrendSample.from_snapshot(snapshot))
                live.update(
                    render_dashboard(
                        snapshot,
                        width=console.width,
                        ascii_bars=ascii_bars,
                        live=True,
                        interval=interval,
                        sample=samples,
                        session_seconds=time.monotonic() - started,
                        trends=tuple(history) if trends_enabled else None,
                        thresholds=thresholds,
                    ),
                    refresh=True,
                )
                if count is not None and samples >= count:
                    break
                elapsed = time.monotonic() - cycle_started
                time.sleep(max(0.0, interval - elapsed))
    except KeyboardInterrupt:
        console.print(Text("sysmon stopped.", style="dim"))
    return 0


def _watch_json(
    collector: SystemCollector,
    *,
    interval: float,
    count: int | None,
) -> int:
    samples = 0
    while count is None or samples < count:
        cycle_started = time.monotonic()
        snapshot = collector.collect(detailed=True)
        print(
            json.dumps(snapshot.to_dict(), separators=(",", ":")),
            flush=True,
        )
        samples += 1
        if count is not None and samples >= count:
            break
        elapsed = time.monotonic() - cycle_started
        time.sleep(max(0.0, interval - elapsed))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
