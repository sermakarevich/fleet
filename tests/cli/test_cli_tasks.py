"""Tests for ready/log/tasks/task commands (unit under test: cli/tasks.py)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from fleet.beads.client import BdError
from fleet.cli.main import app
from fleet.core.task import Task
from tests.cli.conftest import runner
from tests.helpers.task_dir import make_attempt

wide_runner = CliRunner(env={"COLUMNS": "160"})


def _seed_log_dir(fleet_home: Path, filename: str, content: str) -> Path:
    log_dir = fleet_home / "logging"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def _seed_task_dir(fleet_home: Path, task_id: str) -> Path:
    task_dir = fleet_home / "tasks" / task_id
    (task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    return task_dir


def test_ready_no_tasks_prints_message() -> None:
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_ready.return_value = []
        result = runner.invoke(app, ["ready"])
    assert result.exit_code == 0
    assert "No ready tasks" in result.output


def test_log_prints_full_file_when_no_argument(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    body = "line1\nline2\nline3\n"
    _seed_log_dir(tmp_path, "fleet-2026-05-23.jsonl", body)

    result = runner.invoke(app, ["log"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert result.output == body


def test_log_tails_last_n_lines(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    body = "".join(f"line{i}\n" for i in range(1, 11))
    _seed_log_dir(tmp_path, "fleet-2026-05-23.jsonl", body)

    result = runner.invoke(app, ["log", "3"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert result.output == "line8\nline9\nline10\n"


def test_log_picks_most_recent_file(tmp_path, monkeypatch) -> None:

    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    older = _seed_log_dir(tmp_path, "fleet-2026-05-22.jsonl", "old\n")
    newer = _seed_log_dir(tmp_path, "fleet-2026-05-23.jsonl", "new\n")
    # Force older mtime to be earlier in case the FS coarse-grains it.
    os.utime(older, (older.stat().st_atime, newer.stat().st_mtime - 1))

    result = runner.invoke(app, ["log"])
    assert result.exit_code == 0
    assert result.output == "new\n"


def test_log_errors_when_no_log_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    result = runner.invoke(app, ["log"])
    assert result.exit_code == 3
    assert "No log" in result.output


def test_log_errors_when_log_dir_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    (tmp_path / "logging").mkdir()
    result = runner.invoke(app, ["log"])
    assert result.exit_code == 3
    assert "No log files" in result.output


def test_log_rejects_non_positive_tail(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _seed_log_dir(tmp_path, "fleet-2026-05-23.jsonl", "x\n")
    result = runner.invoke(app, ["log", "0"])
    assert result.exit_code == 2


def test_tasks_no_running_prints_message() -> None:
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_in_progress.return_value = []
        result = runner.invoke(app, ["tasks"])
    assert result.exit_code == 0
    assert "No running tasks" in result.output


def test_tasks_lists_in_progress_tasks(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks = [
        Task(id="t-001", title="First", description=None, status="in_progress"),
        Task(
            id="t-002",
            title="Second",
            description=None,
            status="in_progress",
            cwd="/x",
            coder="agy",
            model="opus",
        ),
    ]
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_in_progress.return_value = tasks
        result = wide_runner.invoke(app, ["tasks"])
    assert result.exit_code == 0
    assert "t-001" in result.output
    assert "First" in result.output
    assert "t-002" in result.output
    assert "Second" in result.output
    assert "/x" in result.output
    # Per-task overrides surface in the Coder/Model columns.
    assert "agy" in result.output
    assert "opus" in result.output
    # New header columns should be present (including Coder/Model):
    for header in ("Started", "Elapsed", "Idle", "Context", "Events", "Coder", "Model", "Title"):
        assert header in result.output, header


def test_tasks_renders_runtime_stats(tmp_path, monkeypatch) -> None:
    """`fleet tasks` reads log.jsonl and events.jsonl to surface started/elapsed/events."""

    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_id = "t-stats"
    task_dir = _seed_task_dir(tmp_path, task_id)
    attempt_dir = make_attempt(task_dir, 1)
    log_path = attempt_dir / "log.jsonl"
    log_path.write_text(
        json.dumps({"event": "subprocess_started", "timestamp": "2026-05-23T11:22:33Z"}) + "\n",
        encoding="utf-8",
    )

    # 3 normalized events with a peak prompt size of 40k tokens (20% of 200k).
    events = attempt_dir / "events.jsonl"
    lines = [
        json.dumps(
            {
                "kind": "assistant_text",
                "ts": "2026-05-23T11:22:34Z",
                "usage": {
                    "input_tokens": 1000,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            }
        ),
        json.dumps(
            {
                "kind": "tool_use",
                "ts": "2026-05-23T11:22:35Z",
                "usage": {
                    "input_tokens": 5000,
                    "cache_read_input_tokens": 25000,
                    "cache_creation_input_tokens": 10000,
                },
            }
        ),
        json.dumps(
            {
                "kind": "assistant_text",
                "ts": "2026-05-23T11:22:36Z",
                "usage": {
                    "input_tokens": 2000,
                    "cache_read_input_tokens": 30000,
                    "cache_creation_input_tokens": 5000,
                },
            }
        ),
    ]
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tasks = [Task(id=task_id, title="Hello", description=None, status="in_progress")]
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_in_progress.return_value = tasks
        result = wide_runner.invoke(app, ["tasks"])

    assert result.exit_code == 0, result.output
    assert "Hello" in result.output
    assert " 3 " in result.output  # event count column
    # peak context = 5k + 25k + 10k = 40k → 20% of 200k.
    assert "40.0k" in result.output
    assert "20%" in result.output
    # started should reflect the log's first-line timestamp (2026-05-23 11:22:33 UTC),
    # rendered in the local tz; check the HH:MM portion is plausible.
    assert "2026" in result.output or "May" in result.output or ":" in result.output


def test_tasks_beads_error_exits_nonzero() -> None:
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_in_progress.side_effect = BdError("bd boom")
        result = runner.invoke(app, ["tasks"])
    assert result.exit_code == 4
    assert "bd boom" in result.output


def test_task_state_prints_state_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _seed_task_dir(tmp_path, "t-001")
    body = "# t-001 — STATE\n\n## Next\ndo the thing\n"
    (task_dir / "STATE.md").write_text(body, encoding="utf-8")

    result = runner.invoke(app, ["task", "t-001", "state"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert result.output == body


def test_task_state_falls_back_to_legacy_view(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _seed_task_dir(tmp_path, "t-001")
    (task_dir / "artifacts" / "KNOWLEDGE.md").write_text("old fact\n", encoding="utf-8")

    result = runner.invoke(app, ["task", "t-001", "state"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert "old fact" in result.output


def test_task_log_prints_log_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _seed_task_dir(tmp_path, "t-001")
    attempt_dir = make_attempt(task_dir, 1)
    (attempt_dir / "log.jsonl").write_text("line1\nline2\n", encoding="utf-8")

    result = runner.invoke(app, ["task", "t-001", "log"])
    assert result.exit_code == 0
    assert result.output == "line1\nline2\n"


def test_task_missing_task_dir_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    result = runner.invoke(app, ["task", "t-missing", "state"])
    assert result.exit_code == 3
    assert "No task directory" in result.output


def test_task_state_missing_file_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _seed_task_dir(tmp_path, "t-001")
    result = runner.invoke(app, ["task", "t-001", "state"])
    assert result.exit_code == 3
    assert "STATE.md" in result.output


def test_task_result_prints_result_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _seed_task_dir(tmp_path, "t-001")
    body = '{"schema": 1, "status": "done", "summary": "shipped"}'
    (task_dir / "RESULT.json").write_text(body, encoding="utf-8")

    result = runner.invoke(app, ["task", "t-001", "result"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert result.output == body


def test_task_log_missing_file_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _seed_task_dir(tmp_path, "t-001")
    result = runner.invoke(app, ["task", "t-001", "log"])
    assert result.exit_code == 3
    assert "No log for task" in result.output


def test_task_invalid_action_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _seed_task_dir(tmp_path, "t-001")
    result = runner.invoke(app, ["task", "t-001", "bogus"])
    assert result.exit_code != 0


def test_task_help_lists_running_task_ids() -> None:
    """`fleet task --help` should include currently running task IDs."""
    tasks = [
        Task(id="t-aaa", title="Alpha title", description=None, status="in_progress"),
        Task(id="t-bbb", title="Bravo title", description=None, status="in_progress"),
    ]
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_in_progress.return_value = tasks
        result = runner.invoke(app, ["task", "--help"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert "Currently running tasks" in result.output
    assert "t-aaa" in result.output
    assert "t-bbb" in result.output
    assert "Alpha title" in result.output
    assert "Bravo title" in result.output
    # Standard help boilerplate should still be present.
    assert "TASK_ID" in result.output or "task_id" in result.output
    assert "ACTION" in result.output or "action" in result.output


def test_task_help_shows_none_when_no_running_tasks() -> None:
    """`fleet task --help` shows a "none" placeholder when nothing is running."""
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_in_progress.return_value = []
        result = runner.invoke(app, ["task", "--help"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert "Currently running tasks" in result.output
    assert "(none)" in result.output


def test_task_help_tolerates_beads_error() -> None:
    """`fleet task --help` still exits 0 if bd queue query blows up."""
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_in_progress.side_effect = BdError("bd unavailable")
        result = runner.invoke(app, ["task", "--help"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert "Currently running tasks" in result.output
    assert "unable to query" in result.output
