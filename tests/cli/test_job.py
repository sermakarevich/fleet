"""Tests for `fleet job`. Mirrors the CLI surface."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from fleet.beads.client import BeadsError
from fleet.cli.main import app
from fleet.core.task import Task

runner = CliRunner()


def _task(**kw) -> Task:
    base = {
        "id": "job-1",
        "title": "job",
        "description": "goal",
        "status": "in_progress",
        "type": "epic",
        "worker": "job",
    }
    base.update(kw)
    return Task(**base)


def _run_job(tmp_path, task, children=None, pending=None):
    queue = MagicMock()
    queue.get.return_value = task
    queue.list_children.return_value = children or []
    store = MagicMock()
    store.fetch_pending_for_task.return_value = pending or []
    with (
        patch("fleet.cli.tasks.BeadsQueue", return_value=queue),
        patch("fleet.cli.tasks.QuestionStore", return_value=store),
    ):
        old = os.environ.get("FLEET_HOME")
        os.environ["FLEET_HOME"] = str(tmp_path)
        try:
            return runner.invoke(app, ["job", task.id])
        finally:
            if old is None:
                del os.environ["FLEET_HOME"]
            else:
                os.environ["FLEET_HOME"] = old


def test_job_prints_research_phase(tmp_path) -> None:
    result = _run_job(tmp_path, _task())
    assert result.exit_code == 0, result.output
    assert "phase:  research" in result.output
    assert "children: (none)" in result.output


def test_job_prints_children_and_gate(tmp_path) -> None:
    artifacts = tmp_path / "tasks" / "job-1" / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "RESEARCH.md").write_text("r")
    (artifacts / "tasks.json").write_text("{}")
    children = [
        SimpleNamespace(id="kid-1", status="open"),
        SimpleNamespace(id="kid-2", status="closed"),
    ]
    pending = [{"id": "q1", "prompt": "Job job-1: approve 2 tasks?\n- a"}]
    result = _run_job(tmp_path, _task(), children=children, pending=pending)
    assert result.exit_code == 0, result.output
    assert "phase:  observe" in result.output
    assert "kid-1" in result.output and "kid-2" in result.output
    assert "gate: 1 pending question" in result.output


def test_job_missing_bead_exits_nonzero(tmp_path) -> None:

    queue = MagicMock()
    queue.get.side_effect = BeadsError("no such bead")
    with patch("fleet.cli.tasks.BeadsQueue", return_value=queue):
        old = os.environ.get("FLEET_HOME")
        os.environ["FLEET_HOME"] = str(tmp_path)
        try:
            result = runner.invoke(app, ["job", "ghost"])
        finally:
            if old is None:
                del os.environ["FLEET_HOME"]
            else:
                os.environ["FLEET_HOME"] = old
    assert result.exit_code != 0
