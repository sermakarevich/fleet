"""Tests for fleet.runs.state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet.core.errors import FlowInvalid
from fleet.flows.model import Flow, Input, Step
from fleet.flows.templates import render
from fleet.runs.run_dir import create_step_dir, outputs_file
from fleet.runs.state import context, resolve_inputs
from fleet.runs.store import Run, RunStatus, StepRun, StepStatus


def _flow() -> Flow:
    """A two-step flow with a required, defaulted and optional input."""
    return Flow(
        name="autocode",
        description="",
        inputs=(
            Input(name="repo", required=True),
            Input(name="feature", required=True),
            Input(name="coder", default="opencode"),
            Input(name="note"),
        ),
        defaults={"model": "muse-spark", "coder": "opencode"},
        steps=(Step(name="a", prompt="do a"), Step(name="b", prompt="do b")),
    )


def _run(flow_name: str = "autocode", inputs: dict | None = None) -> Run:
    """A running Run row with realistic inputs."""
    return Run(
        id="run-20260928-aaaaaa",
        flow=flow_name,
        status=RunStatus.running,
        inputs=dict(inputs) if inputs is not None else {"repo": "x", "feature": "f"},
        started_at="2026-09-28T07:00:00+00:00",
    )


def _step_run(step: str, item_index: int) -> StepRun:
    """A succeeded StepRun row for one step or item."""
    return StepRun(
        run_id="run-20260928-aaaaaa",
        step=step,
        item_index=item_index,
        status=StepStatus.succeeded,
    )


def _write_outputs(step_dir: Path, payload: dict) -> None:
    """Write an outputs.json payload into an existing step directory."""
    outputs_file(step_dir).write_text(json.dumps(payload), encoding="utf-8")


def test_resolve_inputs_fills_defaults_and_keeps_values() -> None:
    resolved = resolve_inputs(_flow(), {"repo": "x", "feature": "f", "note": 7})
    assert resolved == {"repo": "x", "feature": "f", "coder": "opencode", "note": 7}


def test_resolve_inputs_given_value_wins_over_default() -> None:
    resolved = resolve_inputs(_flow(), {"repo": "x", "feature": "f", "coder": "codex"})
    assert resolved["coder"] == "codex"


def test_resolve_inputs_missing_required() -> None:
    with pytest.raises(FlowInvalid, match=r"input feature: required"):
        resolve_inputs(_flow(), {"repo": "x"})


def test_resolve_inputs_unknown_name() -> None:
    with pytest.raises(FlowInvalid, match=r"input nope: unknown"):
        resolve_inputs(_flow(), {"repo": "x", "feature": "f", "nope": 1})


def test_context_reads_outputs_and_keeps_types(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    payload = {"units": ["M1", "M2"], "count": 2, "ok": True}
    _write_outputs(create_step_dir(run_dir, "a"), payload)
    run = _run(inputs={"repo": "x", "feature": "f"})
    found = context(_flow(), run, run_dir, [_step_run("a", -1)])
    assert found["steps"]["a"]["outputs"] == payload
    assert isinstance(found["steps"]["a"]["outputs"]["units"], list)
    assert isinstance(found["steps"]["a"]["outputs"]["count"], int)
    assert isinstance(found["steps"]["a"]["outputs"]["ok"], bool)
    assert found["steps"]["a"]["items"] == []
    assert found["inputs"] == {"repo": "x", "feature": "f", "coder": "opencode"}
    assert found["run"] == {"id": run.id, "date": "2026-09-28", "flow": "autocode"}
    assert found["defaults"] == {"model": "muse-spark", "coder": "opencode"}
    assert "item" not in found
    assert "index" not in found


def test_context_items_ordered_by_index(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    _write_outputs(create_step_dir(run_dir, "b", 1), {"unit": "M2"})
    _write_outputs(create_step_dir(run_dir, "b", 0), {"unit": "M1"})
    found = context(_flow(), _run(), run_dir, [_step_run("b", 1), _step_run("b", 0)])
    assert found["steps"]["b"]["items"] == [{"unit": "M1"}, {"unit": "M2"}]
    assert found["steps"]["b"]["outputs"] == {}


def test_context_step_without_runs_has_empty_outputs(tmp_path: Path) -> None:
    found = context(_flow(), _run(), tmp_path / "run-20260928-aaaaaa", [])
    assert found["steps"]["a"] == {
        "outputs": {},
        "items": [],
        "status": "pending",
        "checks": {},
        "item_checks": [],
    }
    assert found["steps"]["b"] == {
        "outputs": {},
        "items": [],
        "status": "pending",
        "checks": {},
        "item_checks": [],
    }


def test_context_item_and_index_only_when_given(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    plain = context(_flow(), _run(), run_dir, [])
    assert "item" not in plain
    assert "index" not in plain
    with_item = context(_flow(), _run(), run_dir, [], item={"unit": "M1"}, index=0)
    assert with_item["item"] == {"unit": "M1"}
    assert with_item["index"] == 0


def test_context_renders_through_templates(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-20260928-aaaaaa"
    _write_outputs(create_step_dir(run_dir, "a"), {"units": ["M1", "M2"]})
    found = context(_flow(), _run(), run_dir, [_step_run("a", -1)])
    assert render("{{ steps.a.outputs.units[0] }}", found) == "M1"
