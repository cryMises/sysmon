from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from sysmon import __version__, cli
from sysmon.models import Snapshot


class FakeCollector:
    def __init__(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self.detailed_calls: list[bool] = []

    def collect(self, detailed: bool = False) -> Snapshot:
        self.detailed_calls.append(detailed)
        return self.snapshot


class FakeLive:
    """Minimal stand-in for :class:`rich.live.Live`."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.updates: list[object] = []

    def __enter__(self) -> FakeLive:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def update(self, renderable: object, refresh: bool = False) -> None:
        self.updates.append(renderable)


def install_fake_collector(
    monkeypatch: pytest.MonkeyPatch, snapshot: Snapshot
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def factory(**kwargs: Any) -> FakeCollector:
        captured.update(kwargs)
        collector = FakeCollector(snapshot)
        captured["collector"] = collector
        return collector

    monkeypatch.setattr(cli, "SystemCollector", factory)
    return captured


def test_once_prints_dashboard(
    sample_snapshot: Snapshot,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_collector(monkeypatch, sample_snapshot)
    assert cli.main(["--once", "--no-color"]) == 0
    output = capsys.readouterr().out
    assert "sysmon" in output
    assert "CPU" in output
    assert "Uptime" in output


def test_json_output_is_machine_readable(
    sample_snapshot: Snapshot,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured = install_fake_collector(monkeypatch, sample_snapshot)
    assert cli.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["hostname"] == "termux"
    assert data["cpu"]["load_1m"] == 1.25
    assert data["cpu"]["usage_percent"] == 37.5
    assert data["cpu"]["clusters"][0]["label"] == "CPU 0-3"
    assert data["cpu"]["clusters"][0]["current_khz"] == 1_800_000
    assert data["memory"]["used_percent"] == 37.5
    assert data["disks"][0]["used_percent"] == 42.0
    assert data["uptime"]["seconds"] == 90_061.0
    assert data["network"] is None
    assert data["processes"] is None
    assert data["battery"]["percentage"] == 45.0
    assert data["battery"]["status"] == "DISCHARGING"
    assert data["battery"]["current_average_ua"] == -3000
    assert data["battery"]["charge_counter_uah"] == 2_015_000
    assert data["battery"]["power_w"] == 3.1
    assert data["battery"]["time_remaining_seconds"] == 9056
    assert data["battery"]["source"] == "termux-battery-status"
    assert data["warnings"] == []
    assert captured["collector"].detailed_calls == [True]


def test_json_includes_live_metrics(
    live_snapshot: Snapshot,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_collector(monkeypatch, live_snapshot)
    assert cli.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["network"]["rx_bytes_per_sec"] == 1536.0
    assert data["network"]["interfaces"] == 2
    assert data["network"]["interface_details"][0]["name"] == "rmnet0"
    assert data["network"]["interface_details"][0]["rx_bytes_per_sec"] == 136.0
    assert data["network"]["interface_details"][1]["name"] == "wlan0"
    assert data["processes"]["running"] == 2
    assert data["processes"]["top"][0]["command"] == "python"
    assert data["processes"]["top"][0]["cpu_percent"] == 12.5
    assert data["processes"]["sort"] == "cpu"
    assert data["processes"]["limit"] == 5
    assert data["processes"]["filter"] is None


def test_json_watch_emits_json_lines(
    live_snapshot: Snapshot,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured = install_fake_collector(monkeypatch, live_snapshot)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    assert (
        cli.main(
            ["--watch", "--json", "--count", "2", "--interval", "0.5"]
        )
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    frames = [json.loads(line) for line in lines]
    assert frames[0]["hostname"] == "termux"
    assert frames[1]["network"]["rx_bytes_per_sec"] == 1536.0
    assert captured["collector"].detailed_calls == [True, True]


def test_interval_is_validated() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--interval", "0.1"])
    assert exc.value.code == 2


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_watch_falls_back_to_one_snapshot_when_not_a_terminal(
    sample_snapshot: Snapshot,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_fake_collector(monkeypatch, sample_snapshot)
    assert cli.main(["--watch"]) == 0
    output = capsys.readouterr().out
    assert "needs an interactive terminal" in output
    assert "sysmon" in output


def test_paths_are_expanded_and_passed_to_collector(
    sample_snapshot: Snapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = install_fake_collector(monkeypatch, sample_snapshot)
    assert cli.main(["--once", "--path", "~/data", "--path", "."]) == 0
    assert captured["paths"] == (Path.home() / "data", Path())


def test_no_battery_flag_disables_battery_collection(
    sample_snapshot: Snapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = install_fake_collector(monkeypatch, sample_snapshot)
    assert cli.main(["--once", "--no-battery"]) == 0
    assert captured["battery_command"] is None


def test_config_values_are_loaded(
    sample_snapshot: Snapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "interval": 5.0,
                "paths": ["/data"],
                "battery": False,
                "processes": {
                    "limit": 9,
                    "sort": "mem",
                    "filter": "python",
                    "full_command": True,
                },
                "trends": {"samples": 20},
                "thresholds": {
                    "cpu": {"warning": 10, "critical": 20},
                },
            }
        )
    )
    captured = install_fake_collector(monkeypatch, sample_snapshot)

    assert cli.main(["--once", "--config", str(config_path)]) == 0

    assert captured["paths"] == (Path("/data"),)
    assert captured["process_limit"] == 9
    assert captured["process_sort"] == "mem"
    assert captured["process_filter"] == "python"
    assert captured["full_command"] is True
    assert captured["battery_command"] is None
    assert "Alerts" in capsys.readouterr().out


def test_cli_process_options_override_config(
    sample_snapshot: Snapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "processes": {
                    "limit": 9,
                    "sort": "mem",
                    "filter": "python",
                }
            }
        )
    )
    captured = install_fake_collector(monkeypatch, sample_snapshot)

    assert (
        cli.main(
            [
                "--once",
                "--config",
                str(config_path),
                "--top",
                "2",
                "--sort",
                "pid",
                "--filter",
                "bash",
                "--path",
                ".",
            ]
        )
        == 0
    )

    assert captured["paths"] == (Path(),)
    assert captured["process_limit"] == 2
    assert captured["process_sort"] == "pid"
    assert captured["process_filter"] == "bash"


def test_cli_empty_filter_clears_config(
    sample_snapshot: Snapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"processes": {"filter": "python"}}))
    captured = install_fake_collector(monkeypatch, sample_snapshot)

    assert cli.main(["--once", "--config", str(config_path), "--filter", ""]) == 0
    assert captured["process_filter"] is None


def test_invalid_config_is_reported_as_parser_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"processes": {"limit": 0}}))

    with pytest.raises(SystemExit) as exc:
        cli.main(["--once", "--config", str(config_path)])

    assert exc.value.code == 2
    assert "processes.limit" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ["--filter", "["],
        ["--top", "0"],
        ["--top", "51"],
        ["--trend-samples", "1"],
        ["--trend-samples", "1001"],
        ["--count", "0"],
    ],
)
def test_new_options_are_validated(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(arguments)
    assert exc.value.code == 2


def _render_updates(updates: list[object]) -> str:
    console = Console(
        record=True,
        width=100,
        force_terminal=False,
        color_system=None,
        highlight=False,
    )
    for update in updates:
        console.print(update)
    return console.export_text()


def test_watch_mode_renders_trends_until_count_is_reached(
    live_snapshot: Snapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = FakeLive()
    monkeypatch.setattr(cli, "Live", lambda **kwargs: live)
    monkeypatch.setattr(
        cli,
        "Console",
        lambda **kwargs: Console(force_terminal=True, width=100, **kwargs),
    )
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    install_fake_collector(monkeypatch, live_snapshot)

    assert cli.main(["--watch", "--count", "2", "--interval", "0.5"]) == 0

    assert len(live.updates) == 2
    output = _render_updates(live.updates)
    assert "Trends" in output
    assert "sample #2" in output


def test_watch_mode_can_disable_trends(
    live_snapshot: Snapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = FakeLive()
    monkeypatch.setattr(cli, "Live", lambda **kwargs: live)
    monkeypatch.setattr(
        cli,
        "Console",
        lambda **kwargs: Console(force_terminal=True, width=100, **kwargs),
    )
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    install_fake_collector(monkeypatch, live_snapshot)

    assert cli.main(["--watch", "--count", "1", "--no-trends"]) == 0

    output = _render_updates(live.updates)
    assert "Trends" not in output
    assert "sample #1" in output
