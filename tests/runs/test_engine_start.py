"""Tests for fleet.runs.engine.start_run."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fleet.core.errors import FlowInvalid
from fleet.flows.model import Flow, Input, Step
from fleet.runs import engine
from fleet.runs.run_dir import NO_ITEM, flow_copy, inputs_file
from fleet.runs.store import RunStatus, RunStore, StepStatus

NOW = datetime(2026, 9, 28, 7, 0, 0, tzinfo=UTC)


def _flow(tmp_path: Path, steps: tuple[Step, ...] = ()) -> Flow:
    """A flow with a real source file the run dir can freeze."""
    source = tmp_path / "demo.yaml"
    source.write_text("fleet_flow: 2\n", encoding="utf-8")
    return Flow(
        name="demo",
        inputs=(Input(name="repo", required=True), Input(name="feature", required=True)),
        defaults={"coder": "opencode"},
        steps=steps or (Step(name="a", prompt="do a"), Step(name="b", prompt="do b")),
        source=str(source),
    )


def _store(fleet_home: Path) -> RunStore:
    return RunStore(fleet_home / "runs.db")


def test_start_run_rows_and_files(tmp_path: Path) -> None:
    fleet_home = tmp_path / "fleet-home"
    flow = _flow(tmp_path)
    run = engine.start_run(_store(fleet_home), fleet_home, flow, {"repo": "x", "feature": "f"}, NOW)
    assert run.status is RunStatus.running
    assert run.flow == "demo"
    assert run.inputs == {"repo": "x", "feature": "f"}
    assert run.started_at == NOW.isoformat()

    store = _store(fleet_home)
    assert store.get_run(run.id) == run
    rows = store.step_runs(run.id)
    assert [(row.step, row.item_index, row.status) for row in rows] == [
        ("a", NO_ITEM, StepStatus.pending),
        ("b", NO_ITEM, StepStatus.pending),
    ]
    run_dir = fleet_home / "runs" / run.id
    assert flow_copy(run_dir).read_text(encoding="utf-8") == "fleet_flow: 2\n"
    saved: dict[str, Any] = json.loads(inputs_file(run_dir).read_text(encoding="utf-8"))
    assert saved == {"repo": "x", "feature": "f"}


def test_start_run_missing_required_input(tmp_path: Path) -> None:
    fleet_home = tmp_path / "fleet-home"
    with pytest.raises(FlowInvalid, match=r"input feature: required"):
        engine.start_run(_store(fleet_home), fleet_home, _flow(tmp_path), {"repo": "x"}, NOW)


def test_start_run_remembers_start_key(tmp_path: Path) -> None:
    fleet_home = tmp_path / "fleet-home"
    run = engine.start_run(
        _store(fleet_home),
        fleet_home,
        _flow(tmp_path),
        {"repo": "x", "feature": "f"},
        NOW,
        start_key="bead-1",
    )
    assert run.start_key == "bead-1"
    assert _store(fleet_home).has_start_key("demo", "bead-1")
