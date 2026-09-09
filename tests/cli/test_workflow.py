"""Tests for `fleet workflow` commands (unit under test: cli/workflow.py).

Every test points FLEET_HOME at tmp_path and injects FakeQueue where the
CLI builds its queue, so no test ever reaches the real `bd`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from fleet.cli.main import app
from fleet.workflows.yaml_io import from_yaml
from tests.cli.conftest import runner
from tests.conftest import FakeQueue

wide_runner = CliRunner(env={"COLUMNS": "160"})

EXAMPLE_YAML = """\
fleet_workflow: 1
name: nightly-quality
description: Lint, test and summarise
defaults: {cwd: /tmp, coder: opencode, model: qwen3.6:latest, priority: 2}
stages:
  - name: checks
    steps:
      - name: lint
        title: "Lint {{workflow.name}} ({{run.date}})"
        description: Run ruff and fix what it reports.
      - name: tests
        title: Run the test suite
        description: uv run pytest -q; fix failures.
  - name: report
    steps:
      - name: summary
        title: Summarise the night
        description: "Read tasks {{steps.lint.task_id}} and {{steps.tests.task_id}}."
        needs: [lint, tests]
"""

BROKEN_YAML = """\
fleet_workflow: 1
name: broken
stages:
  - name: s1
    steps:
      - name: a
        title: A
        needs: [b]
      - name: b
        title: B
"""


class DepsQueue(FakeQueue):
    """FakeQueue that records every create_task extra_args string."""

    def __init__(self) -> None:
        """Start empty with an extra_args log."""
        super().__init__()
        self.seen_extra: list[str | None] = []

    def create_task(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        """Record extra_args, then open the task as usual."""
        self.seen_extra.append(kwargs.get("extra_args"))
        return super().create_task(*args, **kwargs)


def _write(path: Path, text: str) -> Path:
    """Write *text* to *path* and hand the path back."""
    path.write_text(text, encoding="utf-8")
    return path


def _import_example(tmp_path: Path) -> str:
    """Import the ADR example via the CLI and return its printed id."""
    doc = _write(tmp_path / "nightly.yaml", EXAMPLE_YAML)
    result = runner.invoke(app, ["workflow", "import", str(doc)])
    assert result.exit_code == 0, result.output
    workflow_id = result.output.strip()
    assert workflow_id.startswith("wf-")
    return workflow_id


def test_import_prints_id_and_list_shows_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    workflow_id = _import_example(tmp_path)
    result = wide_runner.invoke(app, ["workflow", "list"])
    assert result.exit_code == 0, result.output
    assert workflow_id in result.output
    assert "nightly-quality" in result.output


def test_import_resolves_by_name_in_show(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _import_example(tmp_path)
    result = runner.invoke(app, ["workflow", "show", "nightly-quality"])
    assert result.exit_code == 0, result.output
    assert "stage 1 checks:" in result.output
    assert "- lint" in result.output
    assert "- summary (needs: lint, tests)" in result.output


def test_validate_broken_file_fails_with_problem(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    doc = _write(tmp_path / "broken.yaml", BROKEN_YAML)
    result = runner.invoke(app, ["workflow", "validate", str(doc)])
    assert result.exit_code == 1
    assert "needs" in result.output.lower()


def test_validate_good_file_prints_valid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    doc = _write(tmp_path / "nightly.yaml", EXAMPLE_YAML)
    result = runner.invoke(app, ["workflow", "validate", str(doc)])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def test_export_round_trips(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    workflow_id = _import_example(tmp_path)
    out = tmp_path / "roundtrip.yaml"
    result = runner.invoke(app, ["workflow", "export", workflow_id, "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert from_yaml(out.read_text(encoding="utf-8")).name == "nightly-quality"
    again = runner.invoke(app, ["workflow", "import", str(out)])
    assert again.exit_code != 0  # name taken without --replace
    replaced = runner.invoke(app, ["workflow", "import", str(out), "--replace", workflow_id])
    assert replaced.exit_code == 0, replaced.output
    assert replaced.output.strip() == workflow_id


def test_run_prints_run_id_and_step_lines(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _import_example(tmp_path)
    queue = DepsQueue()
    with patch("fleet.cli.bootstrap.BeadsQueue", return_value=queue):
        result = runner.invoke(app, ["workflow", "run", "nightly-quality"])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    assert lines[0].startswith("wfr-")
    assert "checks/lint -> fake-000" in lines
    assert "checks/tests -> fake-001" in lines
    assert "report/summary -> fake-002" in lines
    assert "--deps" not in (queue.seen_extra[0] or "")
    assert "--deps" not in (queue.seen_extra[1] or "")
    assert "--deps" in (queue.seen_extra[2] or "")


def test_runs_lists_run_and_run_show_has_tasks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _import_example(tmp_path)
    queue = DepsQueue()
    with patch("fleet.cli.bootstrap.BeadsQueue", return_value=queue):
        started = runner.invoke(app, ["workflow", "run", "nightly-quality"])
        assert started.exit_code == 0, started.output
        run_id = started.output.strip().splitlines()[0]
        result = wide_runner.invoke(app, ["workflow", "runs", "nightly-quality"])
    assert result.exit_code == 0, result.output
    assert run_id in result.output
    assert "running" in result.output
    detail = runner.invoke(app, ["workflow", "run-show", run_id])
    assert detail.exit_code == 0, detail.output
    assert "fake-000" in detail.output
    assert "[open]" in detail.output


def test_cancel_marks_run_cancelled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _import_example(tmp_path)
    queue = DepsQueue()
    with patch("fleet.cli.bootstrap.BeadsQueue", return_value=queue):
        started = runner.invoke(app, ["workflow", "run", "nightly-quality"])
        assert started.exit_code == 0, started.output
        run_id = started.output.strip().splitlines()[0]
        cancelled = runner.invoke(app, ["workflow", "cancel", run_id, "--reason", "stop"])
    assert cancelled.exit_code == 0, cancelled.output
    assert "cancelled" in cancelled.output
    detail = runner.invoke(app, ["workflow", "run-show", run_id])
    assert detail.exit_code == 0, detail.output
    assert "cancelled" in detail.output


def test_rm_refuses_while_running_and_force_removes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    workflow_id = _import_example(tmp_path)
    queue = DepsQueue()
    with patch("fleet.cli.bootstrap.BeadsQueue", return_value=queue):
        started = runner.invoke(app, ["workflow", "run", "nightly-quality"])
        assert started.exit_code == 0, started.output
        refused = runner.invoke(app, ["workflow", "rm", workflow_id])
        assert refused.exit_code != 0
        forced = runner.invoke(app, ["workflow", "rm", workflow_id, "--force"])
        assert forced.exit_code == 0, forced.output
    assert runner.invoke(app, ["workflow", "show", workflow_id]).exit_code == 3


def test_unknown_workflow_fails_not_found(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    assert runner.invoke(app, ["workflow", "show", "nope"]).exit_code == 3
    assert runner.invoke(app, ["workflow", "run", "nope"]).exit_code == 3
    assert runner.invoke(app, ["workflow", "run-show", "wfr-xxxxxxxx"]).exit_code == 3
    assert runner.invoke(app, ["workflow", "rm", "nope"]).exit_code == 3
