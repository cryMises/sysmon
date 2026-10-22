from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sysmon import __version__, cli
from sysmon.models import Snapshot


class FakeCollector:
    def __init__(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self.detailed_calls: list[bool] = []

    def collect(self, detailed: bool = False) -> Snapshot:
        self.detailed_calls.append(detailed)
        return self.snapshot


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
    assert data["memory"]["used_percent"] == 37.5
    assert data["disks"][0]["used_percent"] == 42.0
    assert data["uptime"]["seconds"] == 90_061.0
    assert data["network"] is None
    assert data["processes"] is None
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
    assert data["processes"]["running"] == 2
    assert data["processes"]["top"][0]["command"] == "python"
    assert data["processes"]["top"][0]["cpu_percent"] == 12.5


def test_json_rejects_watch_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--json", "--watch"])
    assert exc.value.code == 2
    assert "cannot be combined" in capsys.readouterr().err


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
    assert captured["paths"] == (Path.home() / "data", Path("."))
