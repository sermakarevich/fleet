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


def _import_workflow(tmp_path: Path) -> str:
    """Import a two-step workflow via the CLI and return its printed id."""
    doc = tmp_path / "flow.yaml"
    doc.write_text(
        "fleet_workflow: 1\n"
        "name: nightly\n"
        "stages:\n"
        "  - name: s1\n"
        "    steps:\n"
        "      - name: a\n"
        "        title: A\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["workflow", "import", str(doc)])
    assert result.exit_code == 0, result.output
    return result.output.strip()


def test_create_workflow_writes_workflow_target(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    workflow_id = _import_workflow(tmp_path)
    result = runner.invoke(
        app,
        [
            "schedule",
            "create",
            "--name",
            "nightly",
            "--cron",
            "0 9 * * *",
            "--workflow",
            "nightly",
        ],
    )
    assert result.exit_code == 0, result.output
    schedule = ScheduleStore(tmp_path).get(result.output.strip())
    assert schedule is not None
    assert schedule.target.value == "workflow"
    assert schedule.workflow_id == workflow_id


def test_create_workflow_unknown_name_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    result = runner.invoke(
        app,
        [
            "schedule",
            "create",
            "--name",
            "nightly",
            "--cron",
            "0 9 * * *",
            "--workflow",
            "nope",
        ],
    )
    assert result.exit_code == 3


def test_show_prints_workflow_target(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _import_workflow(tmp_path)
    created = runner.invoke(
        app,
        [
            "schedule",
            "create",
            "--name",
            "nightly",
            "--cron",
            "0 9 * * *",
            "--workflow",
            "nightly",
        ],
    )
    assert created.exit_code == 0, created.output
    result = runner.invoke(app, ["schedule", "show", created.output.strip()])
    assert result.exit_code == 0, result.output
    assert "workflow nightly" in result.output


def _import_inputs_workflow(tmp_path: Path) -> None:
    """Import a workflow with a required and a defaulted input."""
    doc = tmp_path / "paper.yaml"
    doc.write_text(
        "fleet_workflow: 1\n"
        "name: paper\n"
        "inputs:\n"
        "  - name: paper_url\n"
        "    required: true\n"
        "  - name: focus\n"
        "    default: methods\n"
        "stages:\n"
        "  - name: s1\n"
        "    steps:\n"
        "      - name: a\n"
        '        title: "Fetch {{inputs.paper_url}}"\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["workflow", "import", str(doc)])
    assert result.exit_code == 0, result.output


def _create_workflow_schedule(tmp_path: Path, extra: list[str]) -> str:
    """Create a paper-workflow schedule with extra flags; return its id."""
    result = runner.invoke(
        app,
        [
            "schedule",
            "create",
            "--name",
            "paper-nightly",
            "--cron",
            "0 9 * * *",
            "--workflow",
            "paper",
            *extra,
        ],
    )
    assert result.exit_code == 0, result.output
    return result.output.strip()


def test_create_workflow_with_inputs_stores_them(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _import_inputs_workflow(tmp_path)
    schedule_id = _create_workflow_schedule(tmp_path, ["--input", "paper_url=https://x.test"])
    schedule = ScheduleStore(tmp_path).get(schedule_id)
    assert schedule is not None
    assert schedule.inputs == {"paper_url": "https://x.test"}
    shown = runner.invoke(app, ["schedule", "show", schedule_id, "--json"])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["inputs"] == {"paper_url": "https://x.test"}


def test_create_workflow_missing_required_input_refuses(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _import_inputs_workflow(tmp_path)
    result = runner.invoke(
        app,
        [
            "schedule",
            "create",
            "--name",
            "paper-nightly",
            "--cron",
            "0 9 * * *",
            "--workflow",
            "paper",
        ],
    )
    assert result.exit_code != 0
    assert "paper_url" in result.output


def test_create_workflow_unknown_input_refuses(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _import_inputs_workflow(tmp_path)
    result = runner.invoke(
        app,
        [
            "schedule",
            "create",
            "--name",
            "paper-nightly",
            "--cron",
            "0 9 * * *",
            "--workflow",
            "paper",
            "--input",
            "paper_url=https://x.test",
            "--input",
            "ghost=1",
        ],
    )
    assert result.exit_code != 0
    assert "ghost" in result.output


def test_edit_workflow_merges_inputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _import_inputs_workflow(tmp_path)
    schedule_id = _create_workflow_schedule(tmp_path, ["--input", "paper_url=https://x.test"])
    edited = runner.invoke(app, ["schedule", "edit", schedule_id, "--input", "focus=results"])
    assert edited.exit_code == 0, edited.output
    schedule = ScheduleStore(tmp_path).get(schedule_id)
    assert schedule is not None
    assert schedule.inputs == {"paper_url": "https://x.test", "focus": "results"}


def test_schedule_run_passes_inputs_to_workflow_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _import_inputs_workflow(tmp_path)
    schedule_id = _create_workflow_schedule(tmp_path, ["--input", "paper_url=https://x.test"])
    queue = FakeQueue()
    with patch("fleet.cli.bootstrap.BeadsQueue", return_value=queue):
        fired = runner.invoke(app, ["schedule", "run", schedule_id])
    assert fired.exit_code == 0, fired.output
    assert queue.created[0]["title"] == "Fetch https://x.test"
