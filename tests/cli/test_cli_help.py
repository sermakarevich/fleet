"""Tests for CLI help and task show commands (unit under test: cli/main.py, tasks show)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fleet.beads.client import BdError
from fleet.cli.main import app
from fleet.core.task import Task
from tests.cli.conftest import runner


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


def test_show_missing_task_exits_nonzero() -> None:
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.get.side_effect = BdError("task not found: missing-task")
        result = runner.invoke(app, ["show", "missing-task"])
    assert result.exit_code == 3


def test_show_missing_task_prints_error_message() -> None:
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.get.side_effect = BdError("task not found: missing-task")
        result = runner.invoke(app, ["show", "missing-task"])
    assert "missing-task" in result.output or "not found" in result.output


def test_show_existing_task_prints_fields() -> None:
    task = Task(id="t-001", title="My task", description="A desc", status="open")
    with patch("fleet.cli.bootstrap.BeadsQueue") as mock_cls:
        mock_q = MagicMock()
        mock_cls.return_value = mock_q
        mock_q.get.return_value = task
        result = runner.invoke(app, ["show", "t-001"])
    assert result.exit_code == 0
    assert "t-001" in result.output
    assert "My task" in result.output
