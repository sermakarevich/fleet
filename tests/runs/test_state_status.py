"""Tests for step status and check verdicts in fleet.runs.state.context."""

from __future__ import annotations

import json
from pathlib import Path

from fleet.flows.model import Flow, Step
from fleet.flows.templates import render
from fleet.runs.run_dir import NO_ITEM, attempt_dir, check_file, create_step_dir
from fleet.runs.state import context
from fleet.runs.store import Run, RunStatus, StepRun, StepStatus


def _flow(*names: str) -> Flow:
    """A flow with one plain step per name."""
    return Flow(
        name="demo",
        description="",
        inputs=(),
        defaults={},
        steps=tuple(Step(name=name, prompt=f"do {name}") for name in names),
    )


def _run() -> Run:
    """A running Run row with no inputs."""
    return Run(
        id="run-20260928-aaaaaa",
        flow="demo",
        status=RunStatus.running,
        inputs={},
        started_at="2026-09-28T07:00:00+00:00",
    )


def _step_run(step: str, status: StepStatus, item_index: int = NO_ITEM) -> StepRun:
    """A StepRun row for one step or item."""
    return StepRun(
        run_id="run-20260928-aaaaaa",
        step=step,
        item_index=item_index,
        status=status,
    )


def _write_verdict(step_dir: Path, attempt_n: int, name: str, payload: dict) -> None:
    """Write one check verdict file into an attempt's checks folder."""
    path = check_file(attempt_dir(step_dir, attempt_n), name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_plain_step_status_pending_without_rows(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    found = context(_flow("a"), _run(), run_dir, [])
    assert found["steps"]["a"]["status"] == "pending"


def test_plain_step_status_values(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    for status in (
        StepStatus.pending,
        StepStatus.running,
        StepStatus.succeeded,
        StepStatus.failed,
        StepStatus.skipped,
    ):
        found = context(_flow("a"), _run(), run_dir, [_step_run("a", status)])
        assert found["steps"]["a"]["status"] == status.value


def test_for_each_status_failed_when_one_item_failed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    rows = [_step_run("b", StepStatus.succeeded, 0), _step_run("b", StepStatus.failed, 1)]
    found = context(_flow("b"), _run(), run_dir, rows)
    assert found["steps"]["b"]["status"] == "failed"


def test_for_each_status_succeeded_when_all_succeeded(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    rows = [_step_run("b", StepStatus.succeeded, 0), _step_run("b", StepStatus.succeeded, 1)]
    found = context(_flow("b"), _run(), run_dir, rows)
    assert found["steps"]["b"]["status"] == "succeeded"


def test_for_each_status_running_when_one_running(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    rows = [_step_run("b", StepStatus.succeeded, 0), _step_run("b", StepStatus.running, 1)]
    found = context(_flow("b"), _run(), run_dir, rows)
    assert found["steps"]["b"]["status"] == "running"


def test_for_each_status_pending_when_nothing_finished(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    rows = [_step_run("b", StepStatus.pending, 0), _step_run("b", StepStatus.pending, 1)]
    found = context(_flow("b"), _run(), run_dir, rows)
    assert found["steps"]["b"]["status"] == "pending"


def test_checks_read_from_latest_attempt(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    step = create_step_dir(run_dir, "a")
    _write_verdict(step, 0, "voice", {"name": "voice", "ok": True, "message": "fine"})
    _write_verdict(step, 1, "voice", {"name": "voice", "ok": False, "message": "off tone"})
    found = context(_flow("a"), _run(), run_dir, [_step_run("a", StepStatus.succeeded)])
    assert found["steps"]["a"]["checks"] == {
        "voice": {"name": "voice", "ok": False, "message": "off tone"}
    }


def test_item_checks_parallel_to_items(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    first = create_step_dir(run_dir, "b", 0)
    create_step_dir(run_dir, "b", 1)
    _write_verdict(first, 0, "fresh", {"name": "fresh", "ok": True, "message": "new"})
    rows = [_step_run("b", StepStatus.succeeded, 1), _step_run("b", StepStatus.succeeded, 0)]
    found = context(_flow("b"), _run(), run_dir, rows)
    assert found["steps"]["b"]["item_checks"] == [
        {"fresh": {"name": "fresh", "ok": True, "message": "new"}},
        {},
    ]
    # Per-item outputs stay as they are (outputs only, no verdicts mixed in).
    assert found["steps"]["b"]["items"] == [{}, {}]


def test_outputs_argument_at_top_level(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    plain = context(_flow("a"), _run(), run_dir, [])
    assert "outputs" not in plain
    with_outputs = context(_flow("a"), _run(), run_dir, [], outputs={"reply": "hello"})
    assert with_outputs["outputs"] == {"reply": "hello"}
    assert render("{{ outputs.reply }}", with_outputs) == "hello"


def test_status_and_checks_render_through_templates(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    step = create_step_dir(run_dir, "a")
    _write_verdict(
        step,
        0,
        "voice",
        {"name": "voice", "ok": True, "message": "fine", "outputs": {"score": 1}},
    )
    found = context(_flow("a"), _run(), run_dir, [_step_run("a", StepStatus.succeeded)])
    assert render("{{ steps.a.status }}", found) == "succeeded"
    assert render("{{ steps.a.checks.voice.message }}", found) == "fine"
