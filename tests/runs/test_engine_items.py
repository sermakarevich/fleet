"""Tests for advance over for_each steps: expansion, ordering, aggregate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fleet.flows.model import Flow, Input, Step
from fleet.runs import engine
from fleet.runs.run_dir import NO_ITEM, create_step_dir, outputs_file
from fleet.runs.store import RunStatus, RunStore, StepRun, StepStatus

NOW = datetime(2026, 9, 28, 7, 0, 0, tzinfo=UTC)

DEFAULTS = {
    "coder": "cli-coder",
    "model": "cli-model",
    "cwd": "/tmp/fleet-cwd",
    "isolation": "none",
    "retries": 0,
}

UNITS = [
    {"unit": "M1"},
    {"unit": "M2"},
    {"unit": "R3", "after": ["M1"]},
]


def _flow(tmp_path: Path, parallel: bool | str = False) -> Flow:
    source = tmp_path / "demo.yaml"
    source.write_text("fleet_flow: 2\n", encoding="utf-8")
    return Flow(
        name="demo",
        inputs=(Input(name="repo", required=True),),
        steps=(
            Step(name="gen", prompt="plan {{ inputs.repo }}"),
            Step(
                name="work",
                prompt="build {{ item.unit }}",
                needs=("gen",),
                for_each="{{ steps.gen.outputs.units }}",
                key="{{ item.unit }}",
                after="{{ item.after | default([]) }}",
                parallel=parallel,
            ),
            Step(name="done", prompt="wrap up", needs=("work",)),
        ),
        source=str(source),
    )


def _start(tmp_path: Path, parallel: bool | str = False) -> tuple[RunStore, Flow, str, Path]:
    fleet_home = tmp_path / "fleet-home"
    flow = _flow(tmp_path, parallel)
    store = RunStore(fleet_home / "runs.db")
    run = engine.start_run(store, fleet_home, flow, {"repo": "x"}, NOW)
    return store, flow, run.id, fleet_home / "runs" / run.id


def _succeed_gen(store: RunStore, run_id: str, run_dir: Path, flow: Flow) -> None:
    outputs_file(create_step_dir(run_dir, "gen")).write_text(
        json.dumps({"units": UNITS}), encoding="utf-8"
    )
    row = store.get_step_run(run_id, "gen", NO_ITEM)
    assert row is not None
    engine.finish_step_run(store, row, StepStatus.succeeded, NOW)


def _items(store: RunStore, run_id: str) -> list[StepRun]:
    """Item rows of the work step."""
    return [
        row for row in store.step_runs(run_id) if row.step == "work" and row.item_index != NO_ITEM
    ]


def test_for_each_expands_object_items_with_keys(tmp_path: Path) -> None:
    store, flow, run_id, run_dir = _start(tmp_path)
    run = store.get_run(run_id)
    assert run is not None
    engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    _succeed_gen(store, run_id, run_dir, flow)
    tick = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    rows = _items(store, run_id)
    # Non-parallel expansion chains each item after its predecessor.
    assert [(row.item_index, row.key, tuple(row.after)) for row in rows] == [
        (0, "M1", ()),
        (1, "M2", ("M1",)),
        (2, "R3", ("M1", "M2")),
    ]
    summary = store.get_step_run(run_id, "work", NO_ITEM)
    assert summary is not None and summary.status is StepStatus.running
    # Non-parallel: only the first ready item launches while none is running.
    assert [(item.step_run.key, item.attempt) for item in tick.launches] == [("M1", 1)]
    (launch,) = tick.launches
    assert launch.prompt == "build M1"
    assert launch.ctx["item"] == {"unit": "M1"}
    assert launch.ctx["index"] == 0


def test_non_parallel_runs_one_at_a_time_in_after_order(tmp_path: Path) -> None:
    store, flow, run_id, run_dir = _start(tmp_path)
    run = store.get_run(run_id)
    assert run is not None
    engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    _succeed_gen(store, run_id, run_dir, flow)

    first = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert [item.step_run.key for item in first.launches] == ["M1"]
    # Non-parallel items run strictly one at a time in chain order.
    engine.finish_step_run(store, first.launches[0].step_run, StepStatus.succeeded, NOW)

    second = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert [item.step_run.key for item in second.launches] == ["M2"]
    engine.finish_step_run(store, second.launches[0].step_run, StepStatus.succeeded, NOW)

    third = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert [item.step_run.key for item in third.launches] == ["R3"]
    engine.finish_step_run(store, third.launches[0].step_run, StepStatus.succeeded, NOW)

    folded = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    summary = store.get_step_run(run_id, "work", NO_ITEM)
    assert summary is not None and summary.status is StepStatus.succeeded
    assert [item.step.name for item in folded.launches] == ["done"]
    assert folded.run_status is None


def test_non_parallel_blocks_second_launch_while_running(tmp_path: Path) -> None:
    store, flow, run_id, run_dir = _start(tmp_path)
    run = store.get_run(run_id)
    assert run is not None
    engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    _succeed_gen(store, run_id, run_dir, flow)
    engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    again = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert again.launches == ()


def test_aggregate_failed_when_one_item_fails(tmp_path: Path) -> None:
    store, flow, run_id, run_dir = _start(tmp_path, parallel=True)
    run = store.get_run(run_id)
    assert run is not None
    engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    _succeed_gen(store, run_id, run_dir, flow)
    first = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert [item.step_run.key for item in first.launches] == ["M1", "M2"]  # R3 waits for M1
    engine.finish_step_run(store, first.launches[0].step_run, StepStatus.succeeded, NOW)
    engine.finish_step_run(store, first.launches[1].step_run, StepStatus.failed, NOW, reason="bad")
    second = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    assert [item.step_run.key for item in second.launches] == ["R3"]
    engine.finish_step_run(store, second.launches[0].step_run, StepStatus.succeeded, NOW)
    tick = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    summary = store.get_step_run(run_id, "work", NO_ITEM)
    assert summary is not None and summary.status is StepStatus.failed
    assert tick.launches == ()
    done_row = store.get_step_run(run_id, "done", NO_ITEM)
    assert done_row is not None and done_row.status is StepStatus.cancelled
    assert done_row.reason == "need work failed"
    assert tick.run_status is RunStatus.failed


def test_template_error_on_for_each_fails_summary_row(tmp_path: Path) -> None:
    source = tmp_path / "demo.yaml"
    source.write_text("fleet_flow: 2\n", encoding="utf-8")
    flow = Flow(
        name="demo",
        inputs=(Input(name="repo", required=True),),
        steps=(
            Step(name="gen", prompt="plan"),
            Step(
                name="work",
                prompt="build",
                needs=("gen",),
                for_each="{{ steps.gen.outputs.nope }}",
            ),
        ),
        source=str(source),
    )
    fleet_home = tmp_path / "fleet-home"
    store = RunStore(fleet_home / "runs.db")
    run = engine.start_run(store, fleet_home, flow, {"repo": "x"}, NOW)
    run_dir = fleet_home / "runs" / run.id
    engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    row = store.get_step_run(run.id, "gen", NO_ITEM)
    assert row is not None
    engine.finish_step_run(store, row, StepStatus.succeeded, NOW)
    tick = engine.advance(store, flow, run, run_dir, NOW, defaults=DEFAULTS)
    summary = store.get_step_run(run.id, "work", NO_ITEM)
    assert summary is not None and summary.status is StepStatus.failed
    assert summary.reason
    assert tick.launches == ()


def test_template_error_on_launch_marks_row_failed(tmp_path: Path) -> None:
    source = tmp_path / "demo.yaml"
    source.write_text("fleet_flow: 2\n", encoding="utf-8")
    flow = Flow(
        name="demo",
        inputs=(Input(name="repo", required=True),),
        steps=(Step(name="a", prompt="hello {{ inputs.missing }}"),),
        source=str(source),
    )
    fleet_home = tmp_path / "fleet-home"
    store = RunStore(fleet_home / "runs.db")
    run = engine.start_run(store, fleet_home, flow, {"repo": "x"}, NOW)
    tick = engine.advance(store, flow, run, fleet_home / "runs" / run.id, NOW, defaults={})
    assert tick.launches == ()
    row = store.get_step_run(run.id, "a", NO_ITEM)
    assert row is not None and row.status is StepStatus.failed
