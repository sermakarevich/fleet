"""Tests for `fleet trigger` commands (unit under test: cli/trigger.py).

Every test points FLEET_HOME at tmp_path and injects FakeQueue where the
CLI builds its queue, so no test ever reaches the real `bd`.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fleet.cli.main import app
from fleet.triggers.model import TriggerEvent
from fleet.triggers.store import TriggerStore
from tests.cli.conftest import runner
from tests.conftest import FakeQueue


def _create(extra: list[str] | None = None) -> str:
    """Create a trigger via the CLI and return its printed id."""
    args = [
        "trigger",
        "create",
        "--name",
        "invest",
        "--source",
        "blocked_task",
        "--title",
        "Investigate",
    ]
    result = runner.invoke(app, args + (extra or []))
    assert result.exit_code == 0, result.output
    return result.output.strip()


def test_sources_lists_blocked_task(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    result = runner.invoke(app, ["trigger", "sources"])
    assert result.exit_code == 0, result.output
    assert "blocked_task" in result.output


def test_create_prints_id_and_writes_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    trigger_id = _create(["--cwd", str(tmp_path)])
    assert trigger_id.startswith("trg-")
    assert (tmp_path / "triggers" / f"{trigger_id}.json").is_file()


def test_create_unknown_source_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    result = runner.invoke(
        app,
        [
            "trigger",
            "create",
            "--name",
            "x",
            "--source",
            "nope",
            "--title",
            "T",
        ],
    )
    assert result.exit_code == 2


def test_import_then_show(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    doc = tmp_path / "trigger.json"
    doc.write_text(
        json.dumps({"name": "invest", "source": "blocked_task", "title": "Investigate"}),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["trigger", "import", str(doc)])
    assert result.exit_code == 0, result.output
    trigger_id = result.output.strip()
    assert (tmp_path / "triggers" / f"{trigger_id}.json").is_file()
    shown = runner.invoke(app, ["trigger", "show", trigger_id])
    assert shown.exit_code == 0, shown.output
    assert "invest" in shown.output


def test_body_file_sets_description(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    body = tmp_path / "body.md"
    body.write_text("look closely", encoding="utf-8")
    trigger_id = _create(["--cwd", str(tmp_path), "--body-file", str(body)])
    stored = TriggerStore(tmp_path).get(trigger_id)
    assert stored is not None
    assert stored.description == "look closely"


def test_enable_disable_flip_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    trigger_id = _create(["--cwd", str(tmp_path)])
    assert runner.invoke(app, ["trigger", "disable", trigger_id]).exit_code == 0
    assert TriggerStore(tmp_path).get(trigger_id).enabled is False
    assert runner.invoke(app, ["trigger", "enable", trigger_id]).exit_code == 0
    assert TriggerStore(tmp_path).get(trigger_id).enabled is True


def test_remove_deletes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    trigger_id = _create(["--cwd", str(tmp_path)])
    result = runner.invoke(app, ["trigger", "remove", trigger_id])
    assert result.exit_code == 0, result.output
    assert TriggerStore(tmp_path).get(trigger_id) is None
    assert runner.invoke(app, ["trigger", "show", trigger_id]).exit_code != 0


class _FakeSource:
    """One canned event, so `fleet trigger test` never touches `bd`."""

    def poll(self, ctx) -> list[TriggerEvent]:
        _ = ctx
        return [
            TriggerEvent(
                source="blocked_task",
                key="evt-1",
                occurred_at="2026-09-09T00:00:00+00:00",
                payload={},
            )
        ]


def test_test_prints_event_and_opens_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    trigger_id = _create(["--cwd", str(tmp_path)])
    queue = FakeQueue()
    with (
        patch("fleet.cli.bootstrap.BeadsQueue", return_value=queue),
        patch("fleet.cli.trigger.source_for", return_value=_FakeSource()),
    ):
        result = runner.invoke(app, ["trigger", "test", trigger_id])
    assert result.exit_code == 0, result.output
    assert "evt-1" in result.output
    assert "open" in result.output
    assert queue.created == []
    tasks_dir = tmp_path / "tasks"
    assert not tasks_dir.is_dir() or list(tasks_dir.iterdir()) == []
