from __future__ import annotations

import json
from pathlib import Path

import pytest

from sysmon.config import (
    AppConfig,
    ConfigError,
    ProcessSettings,
    TrendSettings,
    load_config,
    parse_config,
)
from sysmon.models import MetricThreshold, Thresholds


def test_default_config() -> None:
    config = AppConfig()
    assert config.interval == 2.0
    assert config.paths == ()
    assert config.battery is True
    assert config.processes == ProcessSettings()
    assert config.trends == TrendSettings()
    assert config.thresholds == Thresholds()
    assert config.ascii is False
    assert config.no_color is False


def test_load_full_config(tmp_path: Path) -> None:
    path = tmp_path / "sysmon.json"
    path.write_text(
        json.dumps(
            {
                "interval": 3.5,
                "paths": ["/", "/data"],
                "battery": False,
                "processes": {
                    "limit": 12,
                    "sort": "mem",
                    "filter": "python",
                    "full_command": True,
                },
                "trends": {"enabled": False, "samples": 120},
                "thresholds": {
                    "cpu": {"warning": 60, "critical": 80},
                    "battery": {"warning": 20, "critical": 10},
                },
                "ascii": True,
                "no_color": True,
            }
        )
    )

    config = load_config(path)

    assert config.interval == 3.5
    assert config.paths == (Path("/"), Path("/data"))
    assert config.battery is False
    assert config.processes == ProcessSettings(
        limit=12,
        sort="mem",
        filter="python",
        full_command=True,
    )
    assert config.trends == TrendSettings(enabled=False, samples=120)
    assert config.thresholds.cpu == MetricThreshold(60.0, 80.0)
    assert config.thresholds.memory == MetricThreshold(80.0, 92.0)
    assert config.thresholds.battery == MetricThreshold(20.0, 10.0)
    assert config.ascii is True
    assert config.no_color is True


def test_docker_can_be_disabled_in_config() -> None:
    assert parse_config({}).docker is True
    assert parse_config({"docker": False}).docker is False


def test_load_empty_config_uses_defaults(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("{}")
    assert load_config(path) == AppConfig()


def test_config_errors_are_clean(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ConfigError, match="cannot read config"):
        load_config(missing)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{")
    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(invalid)

    with pytest.raises(ConfigError, match="must be a JSON object"):
        parse_config([])


@pytest.mark.parametrize(
    "payload",
    [
        {"interval": 0.1},
        {"interval": "fast"},
        {"paths": []},
        {"paths": "/"},
        {"paths": [""]},
        {"paths": [10]},
        {"battery": "yes"},
        {"processes": []},
        {"processes": {"limit": 0}},
        {"processes": {"limit": 51}},
        {"processes": {"limit": 2.5}},
        {"processes": {"sort": "io"}},
        {"processes": {"sort": []}},
        {"processes": {"filter": 42}},
        {"processes": {"filter": "["}},
        {"processes": {"full_command": "yes"}},
        {"processes": {"unknown": True}},
        {"trends": []},
        {"trends": {"enabled": 1}},
        {"trends": {"samples": 1}},
        {"trends": {"samples": 1001}},
        {"trends": {"unknown": True}},
        {"thresholds": []},
        {"thresholds": {"cpu": []}},
        {"thresholds": {"cpu": {"warning": 90, "critical": 80}}},
        {"thresholds": {"cpu": {"warning": 101, "critical": 110}}},
        {"thresholds": {"battery": {"warning": 10, "critical": 20}}},
        {"thresholds": {"battery": {"warning": 10, "critical": 10}}},
        {"thresholds": {"disk": {"unknown": 1}}},
        {"ascii": "yes"},
        {"no_color": 1},
        {"unknown": True},
    ],
)
def test_invalid_config_is_rejected(payload: object) -> None:
    with pytest.raises(ConfigError):
        parse_config(payload)
