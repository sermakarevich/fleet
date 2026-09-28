"""Tests for advance over plain steps: linear flow, skip, defaults, finish."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

from fleet.flows.model import Flow, Input, Step
from fleet.runs import engine
from fleet.runs.run_dir import NO_ITEM
from fleet.runs.store import RunStatus, RunStore, StepRun, StepStatus

NOW = datetime(2026, 9, 28, 7, 0, 0, tzinfo=UTC)

DEFAULTS = {
    "coder": "cli-coder",
    "model": "cli-model",
    "cwd": "/tmp/fleet-cwd",
    "isolation": "none",
    "retries": 2,
}


def _flow(tmp_path: Path, steps: tuple[Step, ...]) -> Flow:
    source = tmp_path / "demo.yaml"
    source.write_text("fleet_flow: 2\n", encoding="utf-8")
    return Flow(
        name="demo",
        inputs=(Input(name="repo", required=True),),
        steps=steps,
        source=str(source),
    )


def _start(
    tmp_path: Path, steps: tuple[Step, ...], **overrides: object
) -> tuple[RunStore, Flow, str, Path]:
    """Start a run in a tmp fleet home; return store, flow, run id, run dir."""
    fleet_home = tmp_path / "fleet-home"
    flow_kwargs: dict[str, object] = {}
    if "flow_defaults" in overrides:
        flow_kwargs["defaults"] = overrides["flow_defaults"]
    flow = _flow(tmp_path, steps)
    if flow_kwargs:
        flow = dataclasses.replace(flow, **flow_kwargs)  # type: ignore[arg-type]
    store = RunStore(fleet_home / "runs.db")
    run = engine.start_run(store, fleet_home, flow, {"repo": "x"}, NOW)
    return store, flow, run.id, fleet_home / "runs" / run.id


def _get(store: RunStore, run_id: str, step: str) -> StepRun:
    row = store.get_step_run(run_id, step, NO_ITEM)
    assert row is not None
    return row


def _linear_steps() -> tuple[Step, ...]:
    return (
        Step(name="a", prompt="do {{ inputs.repo }}"),
        Step(name="b", prompt="after a", needs=("a",)),
        Step(name="c", prompt="after b", needs=("b",)),
    )


def test_linear_flow_advances_one_launch_per_finish(tmp_path: Path) -> None:
    store, flow, run_id, run_dir = _start(tmp_path, _linear_steps())
    run = store.get_run(run_id)
    assert run is not None

    first = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert [launch.step.name for launch in first.launches] == ["a"]
    assert first.run_status is None
    assert first.skipped == ()
    launch = first.launches[0]
    assert launch.attempt == 1
    assert launch.prompt == "do x"
    assert launch.step_dir.is_dir()
    assert _get(store, run_id, "a").status is StepStatus.running
    assert _get(store, run_id, "b").status is StepStatus.pending

    engine.finish_step_run(store, launch.step_run, StepStatus.succeeded, NOW)
    second = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert [item.step.name for item in second.launches] == ["b"]

    engine.finish_step_run(store, second.launches[0].step_run, StepStatus.succeeded, NOW)
    third = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert [item.step.name for item in third.launches] == ["c"]

    engine.finish_step_run(store, third.launches[0].step_run, StepStatus.succeeded, NOW)
    done = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert done.launches == ()
    assert done.run_status is RunStatus.succeeded
    assert store.get_run(run_id) is not None
    finished = store.get_run(run_id)
    assert finished is not None and finished.status is RunStatus.succeeded


def test_failed_step_fails_run(tmp_path: Path) -> None:
    store, flow, run_id, run_dir = _start(tmp_path, (Step(name="solo", prompt="do it"),))
    run = store.get_run(run_id)
    assert run is not None
    first = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert len(first.launches) == 1
    engine.finish_step_run(store, first.launches[0].step_run, StepStatus.failed, NOW, reason="boom")
    done = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert done.launches == ()
    assert done.run_status is RunStatus.failed
    finished = store.get_run(run_id)
    assert finished is not None and finished.status is RunStatus.failed


def test_blocked_downstream_leaves_run_running(tmp_path: Path) -> None:
    store, flow, run_id, run_dir = _start(tmp_path, _linear_steps())
    run = store.get_run(run_id)
    assert run is not None
    first = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    engine.finish_step_run(store, first.launches[0].step_run, StepStatus.succeeded, NOW)
    second = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    engine.finish_step_run(
        store, second.launches[0].step_run, StepStatus.failed, NOW, reason="boom"
    )
    done = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert done.launches == ()
    assert done.run_status is None  # "c" can never run; flow_status stays unfinished


def test_skip_if_marks_skipped_and_continues(tmp_path: Path) -> None:
    steps = (
        Step(name="a", prompt="do a"),
        Step(name="b", prompt="do b", needs=("a",), skip_if="true"),
        Step(name="c", prompt="do c", needs=("b",)),
    )
    store, flow, run_id, run_dir = _start(tmp_path, steps)
    run = store.get_run(run_id)
    assert run is not None
    engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    engine.finish_step_run(store, _get(store, run_id, "a"), StepStatus.succeeded, NOW)
    tick = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert [row.step for row in tick.skipped] == ["b"]
    assert _get(store, run_id, "b").status is StepStatus.skipped
    assert _get(store, run_id, "b").reason == "skip_if"
    assert tick.launches == ()  # "c" becomes ready on the next tick
    follow = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert [item.step.name for item in follow.launches] == ["c"]


def test_defaults_fallback_and_empty_is_unset(tmp_path: Path) -> None:
    steps = (
        Step(name="a", prompt="hi", model="{{ inputs.repo }}"),
        Step(name="b", prompt="hi", coder="", model="{{ inputs.missing | default('') }}"),
    )
    store, flow, run_id, run_dir = _start(tmp_path, steps, flow_defaults={"coder": "flow-coder"})
    run = store.get_run(run_id)
    assert run is not None
    tick = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert len(tick.launches) == 2
    by_name = {launch.step.name: launch for launch in tick.launches}
    assert by_name["a"].coder == "flow-coder"  # flow defaults win over caller defaults
    assert by_name["a"].model == "x"  # rendered template
    assert by_name["a"].cwd == Path("/tmp/fleet-cwd")
    assert by_name["a"].isolation == "none"
    assert by_name["a"].retries == 2
    assert by_name["a"].tools == ()
    assert "item" not in by_name["a"].ctx and "index" not in by_name["a"].ctx
    # An empty string after rendering means "unset".
    assert by_name["b"].coder is None
    assert by_name["b"].model is None


def test_empty_string_after_rendering_is_unset(tmp_path: Path) -> None:
    steps = (Step(name="a", prompt="hi", model="{{ inputs.missing | default('') }}"),)
    flow = _flow(tmp_path, steps)
    fleet_home = tmp_path / "fleet-home"
    store = RunStore(fleet_home / "runs.db")
    run = engine.start_run(store, fleet_home, flow, {"repo": "x"}, NOW)
    tick = engine.advance(store, flow, run, fleet_home / "runs" / run.id, NOW, defaults={})
    (launch,) = tick.launches
    assert launch.model is None
    assert launch.coder is None
    assert launch.retries == 0
    assert launch.cwd == fleet_home / "runs" / run.id


def test_cancel_run_cancels_open_rows(tmp_path: Path) -> None:
    store, flow, run_id, run_dir = _start(tmp_path, _linear_steps())
    run = store.get_run(run_id)
    assert run is not None
    engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    engine.finish_step_run(store, _get(store, run_id, "a"), StepStatus.succeeded, NOW)
    engine.cancel_run(store, run, NOW, "operator stop")
    assert _get(store, run_id, "a").status is StepStatus.succeeded
    assert _get(store, run_id, "b").status is StepStatus.cancelled
    assert _get(store, run_id, "c").status is StepStatus.cancelled
    finished = store.get_run(run_id)
    assert finished is not None and finished.status is RunStatus.cancelled


def test_retry_step_run_relaunches_with_attempt_2(tmp_path: Path) -> None:
    store, flow, run_id, run_dir = _start(tmp_path, _linear_steps())
    run = store.get_run(run_id)
    assert run is not None
    first = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    engine.finish_step_run(store, first.launches[0].step_run, StepStatus.failed, NOW, reason="bad")
    engine.retry_step_run(store, first.launches[0].step_run, NOW, "try again")
    assert _get(store, run_id, "a").status is StepStatus.ready
    second = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    (relaunch,) = second.launches
    assert relaunch.step.name == "a"
    assert relaunch.attempt == 2
    assert relaunch.step_run.attempt == 2
