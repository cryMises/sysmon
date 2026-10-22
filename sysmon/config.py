"""Optional JSON configuration for sysmon.

The configuration file is deliberately small and dependency-free. Command-line
options take precedence over values loaded here; omitted values use the
defaults below.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import MetricThreshold, Thresholds


class ConfigError(ValueError):
    """Raised when a config file cannot be parsed or validated."""


@dataclass(frozen=True)
class ProcessSettings:
    limit: int = 5
    sort: str = "cpu"
    filter: str | None = None
    full_command: bool = False


@dataclass(frozen=True)
class TrendSettings:
    enabled: bool = True
    samples: int = 60


@dataclass(frozen=True)
class AppConfig:
    interval: float = 2.0
    paths: tuple[Path, ...] = ()
    battery: bool = True
    processes: ProcessSettings = ProcessSettings()
    trends: TrendSettings = TrendSettings()
    thresholds: Thresholds = field(default_factory=Thresholds)
    ascii: bool = False
    no_color: bool = False


def load_config(path: Path) -> AppConfig:
    """Load and validate a JSON config file."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    return parse_config(raw)


def parse_config(raw: object) -> AppConfig:
    """Validate a parsed JSON document and return an :class:`AppConfig`."""

    data = _mapping(raw, "config")
    _reject_unknown(
        data,
        {
            "interval",
            "paths",
            "battery",
            "processes",
            "trends",
            "thresholds",
            "ascii",
            "no_color",
        },
        "config",
    )

    interval = _number(data.get("interval", 2.0), "interval", minimum=0.5)
    paths = _paths(data.get("paths"))
    battery = _boolean(data.get("battery", True), "battery")
    processes = _processes(data.get("processes", {}))
    trends = _trends(data.get("trends", {}))
    thresholds = _thresholds(data.get("thresholds", {}))
    ascii_bars = _boolean(data.get("ascii", False), "ascii")
    no_color = _boolean(data.get("no_color", False), "no_color")

    return AppConfig(
        interval=interval,
        paths=paths,
        battery=battery,
        processes=processes,
        trends=trends,
        thresholds=thresholds,
        ascii=ascii_bars,
        no_color=no_color,
    )


def _processes(value: object) -> ProcessSettings:
    data = _mapping(value, "processes")
    _reject_unknown(
        data,
        {"limit", "sort", "filter", "full_command"},
        "processes",
    )

    limit = _integer(
        data.get("limit", 5), "processes.limit", minimum=1, maximum=50
    )
    sort = data.get("sort", "cpu")
    if not isinstance(sort, str) or sort not in {"cpu", "mem", "pid"}:
        raise ConfigError("processes.sort must be one of: cpu, mem, pid")

    raw_filter = data.get("filter")
    if raw_filter is None:
        process_filter = None
    elif isinstance(raw_filter, str):
        process_filter = raw_filter.strip() or None
        if process_filter is not None:
            try:
                re.compile(process_filter)
            except re.error as exc:
                raise ConfigError(
                    f"processes.filter is not a valid regular expression: {exc}"
                ) from exc
    else:
        raise ConfigError("processes.filter must be a string or null")

    full_command = _boolean(
        data.get("full_command", False), "processes.full_command"
    )
    return ProcessSettings(
        limit=limit,
        sort=sort,
        filter=process_filter,
        full_command=full_command,
    )


def _trends(value: object) -> TrendSettings:
    data = _mapping(value, "trends")
    _reject_unknown(data, {"enabled", "samples"}, "trends")
    enabled = _boolean(data.get("enabled", True), "trends.enabled")
    samples = _integer(
        data.get("samples", 60), "trends.samples", minimum=2, maximum=1000
    )
    return TrendSettings(enabled=enabled, samples=samples)


def _thresholds(value: object) -> Thresholds:
    data = _mapping(value, "thresholds")
    _reject_unknown(
        data,
        {"cpu", "memory", "disk", "battery"},
        "thresholds",
    )
    defaults = Thresholds()
    return Thresholds(
        cpu=_metric_threshold(
            data.get("cpu", {}), "thresholds.cpu", defaults.cpu, inverted=False
        ),
        memory=_metric_threshold(
            data.get("memory", {}),
            "thresholds.memory",
            defaults.memory,
            inverted=False,
        ),
        disk=_metric_threshold(
            data.get("disk", {}),
            "thresholds.disk",
            defaults.disk,
            inverted=False,
        ),
        battery=_metric_threshold(
            data.get("battery", {}),
            "thresholds.battery",
            defaults.battery,
            inverted=True,
        ),
    )


def _metric_threshold(
    value: object,
    name: str,
    default: MetricThreshold,
    *,
    inverted: bool,
) -> MetricThreshold:
    data = _mapping(value, name)
    _reject_unknown(data, {"warning", "critical"}, name)
    warning = _number(data.get("warning", default.warning), f"{name}.warning")
    critical = _number(
        data.get("critical", default.critical), f"{name}.critical"
    )
    if not 0.0 <= warning <= 100.0 or not 0.0 <= critical <= 100.0:
        raise ConfigError(f"{name} values must be between 0 and 100")
    if warning == critical:
        raise ConfigError(f"{name}.warning and critical must differ")
    if inverted and critical > warning:
        raise ConfigError(
            f"{name}.critical must be less than or equal to warning "
            "for a low-battery alert"
        )
    if not inverted and warning > critical:
        raise ConfigError(
            f"{name}.warning must be less than or equal to critical"
        )
    return MetricThreshold(warning=warning, critical=critical)


def _paths(value: object) -> tuple[Path, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ConfigError("paths must be a list of strings")
    if not value:
        raise ConfigError("paths must contain at least one path")
    paths: list[Path] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"paths[{index}] must be a non-empty string")
        paths.append(Path(item).expanduser())
    return tuple(paths)


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a JSON object")
    return value


def _reject_unknown(
    data: dict[str, Any], allowed: set[str], name: str
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"unknown {name} key: {unknown[0]}")


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be true or false")
    return value


def _number(
    value: object,
    name: str,
    *,
    minimum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigError(f"{name} must be finite")
    if minimum is not None and number < minimum:
        raise ConfigError(f"{name} must be at least {minimum:g}")
    return number


def _integer(
    value: object,
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value
