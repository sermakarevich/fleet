"""Tests for the `fleet` CLI surface (FR-32)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from fleet.cli import app
from fleet.queue import BeadsError
from fleet.schemas import Task

runner = CliRunner()
wide_runner = CliRunner(env={"COLUMNS": "160"})


# ---------------------------------------------------------------------------
# Help output (FR-32)
# ---------------------------------------------------------------------------


def test_help_lists_required_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in (
        "ready",
        "show",
        "run",
        "config",
        "tasks",
        "task",
    ):
        assert cmd in result.output, f"Expected '{cmd}' in fleet --help output"


def test_help_does_not_list_forbidden_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "block" not in result.output
    assert "answer" not in result.output


def test_help_does_not_list_create_command() -> None:
    """`fleet create` was removed; only `fleet bd create` should exist."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for line in result.output.splitlines():
        stripped = line.lstrip()
        assert not stripped.startswith("create "), (
            f"Expected no top-level `create` command, found: {line!r}"
        )


def test_create_command_invocation_fails() -> None:
    result = runner.invoke(app, ["create", "Some task"])
    assert result.exit_code != 0


def test_config_help_lists_show_and_set() -> None:
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "show" in result.output
    assert "set" in result.output


# ---------------------------------------------------------------------------
# fleet show
# ---------------------------------------------------------------------------


def test_show_missing_task_exits_nonzero() -> None:
    with patch("fleet.cli.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.get.side_effect = BeadsError("task not found: missing-task")
        result = runner.invoke(app, ["show", "missing-task"])
    assert result.exit_code != 0


def test_show_missing_task_prints_error_message() -> None:
    with patch("fleet.cli.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.get.side_effect = BeadsError("task not found: missing-task")
        result = runner.invoke(app, ["show", "missing-task"])
    assert "missing-task" in result.output or "not found" in result.output


def test_show_existing_task_prints_fields() -> None:
    task = Task(id="t-001", title="My task", description="A desc", status="open")
    with patch("fleet.cli.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.get.return_value = task
        result = runner.invoke(app, ["show", "t-001"])
    assert result.exit_code == 0
    assert "t-001" in result.output
    assert "My task" in result.output


# ---------------------------------------------------------------------------
# fleet run
# ---------------------------------------------------------------------------


def test_run_invalid_config_coder_exits_nonzero(tmp_path, monkeypatch) -> None:
    """`fleet run` fails fast if the configured default coder is unknown."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    cfg_dir = tmp_path
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "runtime.toml").write_text('coder = "does-not-exist"\n')
    with patch("fleet.cli.BeadsQueue"):
        result = runner.invoke(app, ["run"])
    assert result.exit_code != 0
    assert "Available" in result.output or "claude" in result.output


def test_run_uses_configured_coder(tmp_path, monkeypatch) -> None:
    """`fleet run` constructs Supervisor with no per-run coder override."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.BeadsQueue"):
        with patch("fleet.cli.Supervisor") as mock_cls:
            mock_sup = MagicMock()
            mock_sup.run = AsyncMock(return_value=0)
            mock_cls.return_value = mock_sup
            result = runner.invoke(app, ["run"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    _, kwargs = mock_cls.call_args
    assert "coder_override" not in kwargs


# ---------------------------------------------------------------------------
# fleet ready (smoke tests)
# ---------------------------------------------------------------------------


def test_ready_no_tasks_prints_message() -> None:
    with patch("fleet.cli.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_ready.return_value = []
        result = runner.invoke(app, ["ready"])
    assert result.exit_code == 0
    assert "No ready tasks" in result.output


# ---------------------------------------------------------------------------
# fleet bd (passthrough)
# ---------------------------------------------------------------------------


def test_bd_passthrough_forwards_args_with_fleet_home_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    completed = MagicMock(returncode=0)
    with patch("fleet.cli.subprocess.run", return_value=completed) as mock_run:
        result = runner.invoke(app, ["bd", "ready", "--limit", "5", "--json"])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == ["bd", "ready", "--limit", "5", "--json"]
    assert kwargs["cwd"] == Path(tmp_path).resolve()


def test_bd_passthrough_propagates_nonzero_exit_code(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    completed = MagicMock(returncode=2)
    with patch("fleet.cli.subprocess.run", return_value=completed):
        result = runner.invoke(app, ["bd", "show", "missing-id"])
    assert result.exit_code == 2


def test_bd_passthrough_does_not_intercept_help_flag(tmp_path, monkeypatch) -> None:
    """A `--help` after `bd` should be passed to bd, not handled by typer."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    completed = MagicMock(returncode=0)
    with patch("fleet.cli.subprocess.run", return_value=completed) as mock_run:
        runner.invoke(app, ["bd", "--help"])
    mock_run.assert_called_once()
    args, _ = mock_run.call_args
    assert args[0] == ["bd", "--help"]


def test_bd_passthrough_listed_in_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "bd" in result.output


# ---------------------------------------------------------------------------
# fleet bd create — cwd capture
# ---------------------------------------------------------------------------


def _fake_create_result(task_id: str, title: str = "T") -> MagicMock:
    import json as _json

    body = {"id": task_id, "title": title, "status": "open"}
    completed = MagicMock(returncode=0, stdout=_json.dumps(body), stderr="")
    return completed


def test_bd_create_captures_invocation_cwd_into_task_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    invocation_dir = tmp_path / "user-project"
    invocation_dir.mkdir()
    monkeypatch.chdir(invocation_dir)

    with patch("fleet.cli.subprocess.run", return_value=_fake_create_result("fleet-abc", "My task")):
        result = runner.invoke(app, ["bd", "create", "My task"])

    assert result.exit_code == 0, result.output + (result.stderr or "")
    meta_path = tmp_path / "tasks" / "fleet-abc" / "task.json"
    assert meta_path.exists()
    import json as _json
    meta = _json.loads(meta_path.read_text())
    assert meta["cwd"] == str(invocation_dir)
    assert meta["id"] == "fleet-abc"


def test_bd_create_injects_json_flag_when_user_did_not_pass_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.subprocess.run", return_value=_fake_create_result("fleet-xyz")) as mock_run:
        runner.invoke(app, ["bd", "create", "title"])
    args, _ = mock_run.call_args
    assert "--json" in args[0]


def test_bd_create_preserves_user_json_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.subprocess.run", return_value=_fake_create_result("fleet-xyz", "Hi")):
        result = runner.invoke(app, ["bd", "create", "--json", "Hi"])
    assert result.exit_code == 0
    # When user passed --json, fleet should NOT replace bd's JSON with a human line.
    assert '"id": "fleet-xyz"' in result.output


def test_bd_create_emits_human_summary_when_no_json_requested(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    invocation_dir = tmp_path / "project-a"
    invocation_dir.mkdir()
    monkeypatch.chdir(invocation_dir)
    with patch("fleet.cli.subprocess.run", return_value=_fake_create_result("fleet-q1", "Do thing")):
        result = runner.invoke(app, ["bd", "create", "Do thing"])
    assert result.exit_code == 0
    assert "fleet-q1" in result.output
    assert "Do thing" in result.output
    assert str(invocation_dir) in result.output


def test_bd_create_dry_run_does_not_write_task_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.subprocess.run", return_value=_fake_create_result("fleet-dry")):
        runner.invoke(app, ["bd", "create", "--dry-run", "title"])
    meta_path = tmp_path / "tasks" / "fleet-dry" / "task.json"
    assert not meta_path.exists()


def test_bd_create_nonzero_exit_does_not_write_task_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    completed = MagicMock(returncode=1, stdout="", stderr="some bd error\n")
    with patch("fleet.cli.subprocess.run", return_value=completed):
        result = runner.invoke(app, ["bd", "create", "boom"])
    assert result.exit_code == 1
    assert not (tmp_path / "tasks").exists() or not list((tmp_path / "tasks").iterdir())


def test_bd_non_create_subcommand_uses_simple_passthrough(tmp_path, monkeypatch) -> None:
    """`bd show ...` must NOT be intercepted — keeps stdout flowing to the terminal."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    completed = MagicMock(returncode=0)
    with patch("fleet.cli.subprocess.run", return_value=completed) as mock_run:
        runner.invoke(app, ["bd", "show", "fleet-1"])
    # Simple passthrough: no capture_output kwarg.
    _, kwargs = mock_run.call_args
    assert "capture_output" not in kwargs


# ---------------------------------------------------------------------------
# fleet bd create — --coder / --model interception
# ---------------------------------------------------------------------------


def test_bd_create_strips_coder_and_model_from_bd_args(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch(
        "fleet.cli.subprocess.run",
        return_value=_fake_create_result("fleet-c1", "T"),
    ) as mock_run:
        result = runner.invoke(
            app,
            ["bd", "create", "--coder", "agy", "--model", "opus", "T"],
        )
    assert result.exit_code == 0, result.output
    args, _ = mock_run.call_args
    forwarded = args[0]
    assert "--coder" not in forwarded
    assert "--model" not in forwarded
    assert "agy" not in forwarded
    assert "opus" not in forwarded


def test_bd_create_persists_coder_and_model_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.subprocess.run", return_value=_fake_create_result("fleet-c2", "T")):
        result = runner.invoke(
            app,
            ["bd", "create", "--coder", "agy", "--model", "opus", "T"],
        )
    assert result.exit_code == 0, result.output
    import json as _json
    meta = _json.loads((tmp_path / "tasks" / "fleet-c2" / "task.json").read_text())
    assert meta["coder"] == "agy"
    assert meta["model"] == "opus"


def test_bd_create_accepts_equals_form_for_coder(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch(
        "fleet.cli.subprocess.run",
        return_value=_fake_create_result("fleet-c3", "T"),
    ) as mock_run:
        result = runner.invoke(app, ["bd", "create", "--coder=agy", "T"])
    assert result.exit_code == 0, result.output
    forwarded = mock_run.call_args[0][0]
    assert not any(a.startswith("--coder") for a in forwarded)
    import json as _json
    meta = _json.loads((tmp_path / "tasks" / "fleet-c3" / "task.json").read_text())
    assert meta["coder"] == "agy"


def test_bd_create_rejects_unknown_coder(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.subprocess.run") as mock_run:
        result = runner.invoke(
            app,
            ["bd", "create", "--coder", "does-not-exist", "T"],
        )
    # bd must not be called when the coder is invalid.
    mock_run.assert_not_called()
    assert result.exit_code != 0
    assert "does-not-exist" in result.output or "Available" in result.output


def test_bd_create_without_overrides_does_not_write_them(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.subprocess.run", return_value=_fake_create_result("fleet-c4", "T")):
        runner.invoke(app, ["bd", "create", "T"])
    import json as _json
    meta = _json.loads((tmp_path / "tasks" / "fleet-c4" / "task.json").read_text())
    assert "coder" not in meta or meta["coder"] is None
    assert "model" not in meta or meta["model"] is None


def test_bd_create_human_summary_includes_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    with patch("fleet.cli.subprocess.run", return_value=_fake_create_result("fleet-c5", "Do")):
        result = runner.invoke(
            app,
            ["bd", "create", "--coder", "agy", "--model", "opus", "Do"],
        )
    assert result.exit_code == 0, result.output
    assert "coder: agy" in result.output
    assert "model: opus" in result.output


# ---------------------------------------------------------------------------
# fleet log
# ---------------------------------------------------------------------------


def _seed_log_dir(home: Path, filename: str, content: str) -> Path:
    log_dir = home / "logging"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


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
    import os
    import time

    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    older = _seed_log_dir(tmp_path, "fleet-2026-05-22.jsonl", "old\n")
    time.sleep(0.01)
    newer = _seed_log_dir(tmp_path, "fleet-2026-05-23.jsonl", "new\n")
    # Force older mtime to be earlier in case the FS coarse-grains it.
    os.utime(older, (older.stat().st_atime, newer.stat().st_mtime - 1))

    result = runner.invoke(app, ["log"])
    assert result.exit_code == 0
    assert result.output == "new\n"


def test_log_errors_when_no_log_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    result = runner.invoke(app, ["log"])
    assert result.exit_code != 0
    assert "No log" in result.output


def test_log_errors_when_log_dir_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    (tmp_path / "logging").mkdir()
    result = runner.invoke(app, ["log"])
    assert result.exit_code != 0
    assert "No log files" in result.output


def test_log_rejects_non_positive_tail(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _seed_log_dir(tmp_path, "fleet-2026-05-23.jsonl", "x\n")
    result = runner.invoke(app, ["log", "0"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# fleet tasks / fleet task <id> <action>
# ---------------------------------------------------------------------------


def test_tasks_no_running_prints_message() -> None:
    with patch("fleet.cli.BeadsQueue") as mock_cls:
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
    with patch("fleet.cli.BeadsQueue") as mock_cls:
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


def _seed_task_dir(home: Path, task_id: str) -> Path:
    task_dir = home / "tasks" / task_id
    (task_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    return task_dir


def test_tasks_renders_runtime_stats(tmp_path, monkeypatch) -> None:
    """`fleet tasks` reads log.jsonl and events.jsonl to surface started/elapsed/events."""
    import json as _json

    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_id = "t-stats"
    task_dir = _seed_task_dir(tmp_path, task_id)
    log_path = task_dir / "log.jsonl"
    log_path.write_text(
        _json.dumps({"event": "subprocess_started", "timestamp": "2026-05-23T11:22:33Z"}) + "\n",
        encoding="utf-8",
    )

    # 3 normalized events with a peak prompt size of 40k tokens (20% of 200k).
    events = task_dir / "events.jsonl"
    lines = [
        _json.dumps({"kind": "assistant_text", "ts": "2026-05-23T11:22:34Z",
                     "usage": {"input_tokens": 1000, "cache_read_input_tokens": 0,
                               "cache_creation_input_tokens": 0}}),
        _json.dumps({"kind": "tool_use", "ts": "2026-05-23T11:22:35Z",
                     "usage": {"input_tokens": 5000, "cache_read_input_tokens": 25000,
                               "cache_creation_input_tokens": 10000}}),
        _json.dumps({"kind": "assistant_text", "ts": "2026-05-23T11:22:36Z",
                     "usage": {"input_tokens": 2000, "cache_read_input_tokens": 30000,
                               "cache_creation_input_tokens": 5000}}),
    ]
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tasks = [Task(id=task_id, title="Hello", description=None, status="in_progress")]
    with patch("fleet.cli.BeadsQueue") as mock_cls:
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
    with patch("fleet.cli.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_in_progress.side_effect = BeadsError("bd boom")
        result = runner.invoke(app, ["tasks"])
    assert result.exit_code != 0
    assert "bd boom" in result.output


def test_task_plan_prints_plan_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _seed_task_dir(tmp_path, "t-001")
    body = "# t-001 — PLAN_AND_STATUS\n\nstuff\n"
    (task_dir / "artifacts" / "PLAN_AND_STATUS.md").write_text(body, encoding="utf-8")

    result = runner.invoke(app, ["task", "t-001", "plan"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert result.output == body


def test_task_knowledge_prints_knowledge_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _seed_task_dir(tmp_path, "t-001")
    body = "# t-001 — KNOWLEDGE\n\nthings\n"
    (task_dir / "artifacts" / "KNOWLEDGE.md").write_text(body, encoding="utf-8")

    result = runner.invoke(app, ["task", "t-001", "knowledge"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert result.output == body


def test_task_log_prints_log_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _seed_task_dir(tmp_path, "t-001")
    (task_dir / "log.jsonl").write_text("line1\nline2\n", encoding="utf-8")

    result = runner.invoke(app, ["task", "t-001", "log"])
    assert result.exit_code == 0
    assert result.output == "line1\nline2\n"


def test_task_missing_task_dir_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    result = runner.invoke(app, ["task", "t-missing", "plan"])
    assert result.exit_code != 0
    assert "No task directory" in result.output


def test_task_plan_missing_file_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _seed_task_dir(tmp_path, "t-001")
    result = runner.invoke(app, ["task", "t-001", "plan"])
    assert result.exit_code != 0
    assert "PLAN_AND_STATUS" in result.output


def test_task_log_missing_file_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _seed_task_dir(tmp_path, "t-001")
    result = runner.invoke(app, ["task", "t-001", "log"])
    assert result.exit_code != 0
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
    with patch("fleet.cli.BeadsQueue") as mock_cls:
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
    with patch("fleet.cli.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_in_progress.return_value = []
        result = runner.invoke(app, ["task", "--help"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert "Currently running tasks" in result.output
    assert "(none)" in result.output


def test_task_help_tolerates_beads_error() -> None:
    """`fleet task --help` still exits 0 if bd queue query blows up."""
    with patch("fleet.cli.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.list_in_progress.side_effect = BeadsError("bd unavailable")
        result = runner.invoke(app, ["task", "--help"])
    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert "Currently running tasks" in result.output
    assert "unable to query" in result.output
