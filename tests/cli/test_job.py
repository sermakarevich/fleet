"""Tests for `fleet job`. Mirrors the CLI surface."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from fleet.beads.client import BdError
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


def _run_job(tmp_path, task, children=None, pending=None, argv=None, queue=None):
    queue = queue or MagicMock()
    queue.get.return_value = task
    queue.list_children.return_value = children or []
    store = MagicMock()
    store.fetch_pending_for_task.return_value = pending or []
    with (
        patch("fleet.cli.bootstrap.BeadsQueue", return_value=queue),
        patch("fleet.cli.tasks.QuestionStore", return_value=store),
    ):
        old = os.environ.get("FLEET_HOME")
        os.environ["FLEET_HOME"] = str(tmp_path)
        try:
            return runner.invoke(app, argv or ["job", "view", task.id])
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


def test_job_prints_shortlist_and_runs_tables(tmp_path) -> None:
    artifacts = tmp_path / "tasks" / "job-1" / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "RESEARCH.md").write_text("r")
    (artifacts / "tasks.json").write_text("{}")
    candidates = {
        "candidates": [
            {
                "url": "https://a.example/paper",
                "title": "A" * 70,
                "kind": "paper",
                "status": "shortlist",
                "subtopic": "topic-a",
                "scores": {"relevance": 0.9},
            },
            {
                "url": "https://b.example/blog",
                "title": "Blog post",
                "kind": "opinion",
                "status": "rejected",
                "subtopic": "topic-b",
                "scores": {"relevance": 0.99},
            },
            {
                "url": "https://c.example/paper",
                "title": "In KB source",
                "kind": "paper",
                "status": "in_kb",
                "subtopic": "topic-a",
                "scores": {"relevance": 0.4},
            },
        ]
    }
    (artifacts / "candidates.json").write_text(json.dumps(candidates))
    (artifacts / "children_runs.json").write_text(
        json.dumps({"src-01": {"run_id": "run-1", "task_ids": ["t1", "t2"]}})
    )

    def _get(task_id: str):
        if task_id == "job-1":
            return _task()
        return SimpleNamespace(id=task_id, status="closed" if task_id == "t1" else "open")

    queue = MagicMock()
    queue.get.side_effect = _get
    result = _run_job(tmp_path, _task(), queue=queue)
    assert result.exit_code == 0, result.output
    assert "Shortlist" in result.output
    assert "A" * 70 not in result.output  # truncated to 60 chars with an ellipsis
    assert "..." in result.output
    assert "https://a.example/paper" in result.output
    # rejected candidates are excluded from the shortlist table.
    assert "https://b.example/blog" not in result.output
    assert "In KB source" in result.output
    assert "Runs" in result.output
    assert "src-01" in result.output and "1/2" in result.output


def test_job_omits_tables_when_files_missing(tmp_path) -> None:
    result = _run_job(tmp_path, _task())
    assert result.exit_code == 0, result.output
    assert "Shortlist" not in result.output
    assert "Runs" not in result.output


def test_research_command_prints_same_tables(tmp_path) -> None:
    artifacts = tmp_path / "tasks" / "job-1" / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "candidates.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "url": "https://a.example",
                        "title": "A",
                        "kind": "paper",
                        "status": "shortlist",
                        "subtopic": "t",
                        "scores": {"relevance": 0.5},
                    }
                ]
            }
        )
    )
    result = _run_job(tmp_path, _task(), argv=["research", "job-1"])
    assert result.exit_code == 0, result.output
    assert "Shortlist" in result.output


def test_job_missing_bead_exits_nonzero(tmp_path) -> None:

    queue = MagicMock()
    queue.get.side_effect = BdError("no such bead")
    with patch("fleet.cli.bootstrap.BeadsQueue", return_value=queue):
        old = os.environ.get("FLEET_HOME")
        os.environ["FLEET_HOME"] = str(tmp_path)
        try:
            result = runner.invoke(app, ["job", "view", "ghost"])
        finally:
            if old is None:
                del os.environ["FLEET_HOME"]
            else:
                os.environ["FLEET_HOME"] = old
    assert result.exit_code != 0
