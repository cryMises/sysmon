"""Command-line entry point for sysmon."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.live import Live
from rich.text import Text

from . import __version__
from .collectors import SystemCollector
from .dashboard import render_dashboard


def positive_interval(value: str) -> float:
    try:
        interval = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if interval < 0.5:
        raise argparse.ArgumentTypeError("must be at least 0.5 seconds")
    return interval


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
            "refresh continuously with live network/process details "
            "until Ctrl+C (default: one snapshot)"
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
        default=2.0,
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
        "--json",
        action="store_true",
        help="print raw data as JSON, including network and process details",
    )
    parser.add_argument(
        "--ascii",
        action="store_true",
        help="use ASCII bars instead of Unicode block characters",
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

    if args.json and args.watch:
        parser.error("--json cannot be combined with --watch")

    paths = tuple(path.expanduser() for path in (args.paths or [Path("/")]))
    collector = SystemCollector(paths=paths)
    console = Console(
        highlight=False,
        no_color=True if args.no_color else None,
    )

    try:
        if args.json:
            print(
                json.dumps(
                    collector.collect(detailed=True).to_dict(),
                    indent=2,
                )
            )
            return 0

        if args.watch:
            return _watch(collector, console, args)

        snapshot = collector.collect()
        console.print(
            render_dashboard(
                snapshot,
                width=console.width,
                ascii_bars=args.ascii,
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
    args: argparse.Namespace,
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
                ascii_bars=args.ascii,
            )
        )
        return 0

    try:
        with Live(
            console=console,
            screen=True,
            auto_refresh=False,
            refresh_per_second=4,
            vertical_overflow="ellipsis",
        ) as live:
            started = time.monotonic()
            samples = 0
            while True:
                cycle_started = time.monotonic()
                snapshot = collector.collect(detailed=True)
                samples += 1
                live.update(
                    render_dashboard(
                        snapshot,
                        width=console.width,
                        ascii_bars=args.ascii,
                        live=True,
                        interval=args.interval,
                        sample=samples,
                        session_seconds=time.monotonic() - started,
                    ),
                    refresh=True,
                )
                elapsed = time.monotonic() - cycle_started
                time.sleep(max(0.0, args.interval - elapsed))
    except KeyboardInterrupt:
        console.print(Text("sysmon stopped.", style="dim"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
