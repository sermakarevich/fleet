"""Tests for engine.recover_running_steps: restart re-launches orphaned rows."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fleet.flows.model import Flow, Input, Step
from fleet.runs import engine
from fleet.runs.engine import RESTART_REASON
from fleet.runs.run_dir import NO_ITEM
from fleet.runs.store import RunStore, StepStatus

NOW = datetime(2026, 9, 28, 7, 0, 0, tzinfo=UTC)


def test_recover_running_steps_touches_only_running(tmp_path: Path) -> None:
    """Two running rows go ready with RESTART_REASON; the succeeded row is untouched."""
    fleet_home = tmp_path / "fleet-home"
    source = tmp_path / "demo.yaml"
    source.write_text("fleet_flow: 2\n", encoding="utf-8")
    flow = Flow(
        name="demo",
        inputs=(Input(name="repo", required=True),),
        steps=(
            Step(name="a", prompt="do it"),
            Step(name="b", prompt="do it"),
            Step(name="c", prompt="do it"),
        ),
        source=str(source),
    )
    store = RunStore(fleet_home / "runs.db")
    run = engine.start_run(store, fleet_home, flow, {"repo": "x"}, NOW)
    store.set_step_status(run.id, "a", NO_ITEM, StepStatus.running, NOW.isoformat())
    store.set_step_status(run.id, "b", NO_ITEM, StepStatus.running, NOW.isoformat())
    store.set_step_status(run.id, "c", NO_ITEM, StepStatus.succeeded, NOW.isoformat())

    touched = engine.recover_running_steps(store, NOW)

    assert {(row.step) for row in touched} == {"a", "b"}
    for row in touched:
        assert row.status is StepStatus.ready
        assert row.reason == RESTART_REASON
    assert RESTART_REASON == "supervisor restarted; step re-launched"
    finished = store.get_step_run(run.id, "c", NO_ITEM)
    assert finished is not None and finished.status is StepStatus.succeeded
