"""Tests for `fleet schedule` commands (unit under test: cli/schedule.py).

Every test points FLEET_HOME at tmp_path and injects FakeQueue where the
CLI builds its queue, so no test ever reaches the real `bd`.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from fleet.cli.main import app
from fleet.schedules.store import ScheduleStore
from tests.cli.conftest import runner
from tests.conftest import FakeQueue

wide_runner = CliRunner(env={"COLUMNS": "160"})


def _create(schedule_args: list[str] | None = None) -> str:
    """Create a schedule via the CLI and return its printed id."""
    args = [
        "schedule",
        "create",
        "--name",
        "triage",
        "--cron",
        "0 9 * * 1-5",
        "--title",
        "Triage {date}",
    ]
    result = runner.invoke(app, args + (schedule_args or []))
    assert result.exit_code == 0, result.output
    return result.output.strip()


def test_create_prints_id_and_writes_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    schedule_id = _create(["--cwd", str(tmp_path)])
    assert schedule_id.startswith("sch-")
    assert (tmp_path / "schedules" / f"{schedule_id}.json").is_file()


def test_list_shows_created_schedule(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    schedule_id = _create(["--cwd", str(tmp_path)])
    result = wide_runner.invoke(app, ["schedule", "list"])
    assert result.exit_code == 0, result.output
    assert schedule_id in result.output
    assert "triage" in result.output


def test_list_json_has_schedule(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    schedule_id = _create(["--cwd", str(tmp_path)])
    result = runner.invoke(app, ["schedule", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [item["id"] for item in payload] == [schedule_id]


def test_preview_prints_five_lines(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    result = runner.invoke(app, ["schedule", "preview", "0 9 * * *"])
    assert result.exit_code == 0, result.output
    assert len(result.output.strip().splitlines()) == 5


def test_preview_bad_cron_fails_with_message(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    result = runner.invoke(app, ["schedule", "preview", "bogus"])
    assert result.exit_code != 0
    assert result.output.strip() != ""


def test_create_bad_cron_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    result = runner.invoke(
        app,
        ["schedule", "create", "--name", "x", "--cron", "bogus", "--title", "T"],
    )
    assert result.exit_code != 0
    assert "cron" in result.output.lower()


def test_create_bad_coder_and_cwd_and_priority_fail(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    base = ["schedule", "create", "--name", "x", "--cron", "0 9 * * *", "--title", "T"]
    assert runner.invoke(app, [*base, "--coder", "nope"]).exit_code != 0
    assert runner.invoke(app, [*base, "--cwd", "/no/such/dir"]).exit_code != 0
    assert runner.invoke(app, [*base, "-p", "9"]).exit_code != 0


def test_run_prints_task_id_and_records_manual_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    schedule_id = _create(["--cwd", str(tmp_path)])
    queue = FakeQueue()
    with patch("fleet.cli.bootstrap.BeadsQueue", return_value=queue):
        result = runner.invoke(app, ["schedule", "run", schedule_id])
    assert result.exit_code == 0, result.output
    task_id = result.output.strip()
    assert task_id.startswith("fake-")
    runs = ScheduleStore(tmp_path).runs(schedule_id)
    assert len(runs) == 1
    assert runs[0].trigger.value == "manual"
    assert runs[0].task_id == task_id


def test_show_lists_runs_with_task_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    schedule_id = _create(["--cwd", str(tmp_path)])
    queue = FakeQueue()
    with patch("fleet.cli.bootstrap.BeadsQueue", return_value=queue):
        run_result = runner.invoke(app, ["schedule", "run", schedule_id])
        assert run_result.exit_code == 0, run_result.output
        result = runner.invoke(app, ["schedule", "show", schedule_id])
    assert result.exit_code == 0, result.output
    assert run_result.output.strip() in result.output
    assert "open" in result.output


def test_edit_changes_only_given_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    schedule_id = _create(["--cwd", str(tmp_path)])
    result = runner.invoke(app, ["schedule", "edit", schedule_id, "--cron", "0 10 * * *"])
    assert result.exit_code == 0, result.output
    schedule = ScheduleStore(tmp_path).get(schedule_id)
    assert schedule is not None
    assert schedule.cron == "0 10 * * *"
    assert schedule.name == "triage"


def test_enable_disable_flip_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    schedule_id = _create(["--cwd", str(tmp_path)])
    assert runner.invoke(app, ["schedule", "disable", schedule_id]).exit_code == 0
    assert ScheduleStore(tmp_path).get(schedule_id).enabled is False
    assert runner.invoke(app, ["schedule", "enable", schedule_id]).exit_code == 0
    assert ScheduleStore(tmp_path).get(schedule_id).enabled is True


def test_rm_removes_schedule(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    schedule_id = _create(["--cwd", str(tmp_path)])
    result = runner.invoke(app, ["schedule", "rm", schedule_id])
    assert result.exit_code == 0, result.output
    assert ScheduleStore(tmp_path).get(schedule_id) is None
    assert runner.invoke(app, ["schedule", "show", schedule_id]).exit_code != 0


def test_unknown_id_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    assert runner.invoke(app, ["schedule", "show", "sch-abcdef"]).exit_code == 3
    assert runner.invoke(app, ["schedule", "rm", "sch-abcdef"]).exit_code == 3
    assert runner.invoke(app, ["schedule", "enable", "sch-abcdef"]).exit_code == 3
