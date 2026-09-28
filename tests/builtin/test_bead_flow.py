"""Tests for the bead flow and its tools (builtin catalog)."""

from __future__ import annotations

from typing import Any

from fleet.flows import folders
from fleet.flows.templates import render, render_bool
from fleet.flows.tools import command_for

_RUN_ID = "run-20260928-bead"
_BEAD_ID = "fleet-abc"


def _context(isolation: str) -> dict[str, Any]:
    """Fake run context mirroring runs/state.context for the bead flow."""
    inputs = {
        "id": _BEAD_ID,
        "title": "Fix login redirect",
        "description": "The redirect drops the query string.",
        "coder": "opencode",
        "model": "muse-spark",
        "cwd": "/repo",
        "isolation": isolation,
    }
    steps = {
        name: {
            "outputs": {},
            "items": [],
            "status": status,
            "checks": {},
            "item_checks": [],
        }
        for name, status in (
            ("claim", "succeeded"),
            ("work", "failed"),
            ("merge", "failed"),
            ("close", "pending"),
            ("drop", "pending"),
            ("block", "pending"),
        )
    }
    return {
        "inputs": inputs,
        "run": {"id": _RUN_ID, "date": "2026-09-28", "flow": "bead"},
        "defaults": {"isolation": "worktree", "retries": 2},
        "steps": steps,
    }


def test_bead_flow_parses_disabled_with_six_steps_in_order() -> None:
    """bead.yaml is disabled with claim, work, merge, close, drop, block in order."""
    catalog = folders.load(["builtin"])
    assert catalog.problems == []
    flow = catalog.flows["bead"]
    assert flow.enabled is False
    assert [step.name for step in flow.steps] == [
        "claim",
        "work",
        "merge",
        "close",
        "drop",
        "block",
    ]


def test_bead_flow_starts_from_bd_ready_keyed_by_bead_id() -> None:
    """The start polls bd_ready with one run per bead id."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    assert flow.on.tool is not None
    assert flow.on.tool.name == "bd_ready"
    key = render(flow.on.tool.key, {"item": {"id": _BEAD_ID}})
    assert key == _BEAD_ID


def test_bead_flow_inputs_are_seven_with_three_required() -> None:
    """The flow declares the seven ready-listing keys; id/title/description required."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    assert {item.name for item in flow.inputs} == {
        "id",
        "title",
        "description",
        "coder",
        "model",
        "cwd",
        "isolation",
    }
    assert {item.name for item in flow.inputs if item.required} == {
        "id",
        "title",
        "description",
    }


def test_bead_flow_defaults_pin_worktree_and_two_retries() -> None:
    """Defaults carry worktree isolation and two retries (three attempts)."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    assert flow.defaults["isolation"] == "worktree"
    assert flow.defaults["retries"] == 2


def test_bead_flow_failure_steps_run_when_failed() -> None:
    """drop and block run on the failure path; the rest run on ok."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    assert flow.step("drop").when == "failed"
    assert flow.step("block").when == "failed"
    for name in ("claim", "work", "merge", "close"):
        assert flow.step(name).when == "ok"


def test_bead_flow_step_edges_and_tools() -> None:
    """claim->work->merge->close with drop/block on the (work, merge) failure path."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    claim, work, merge, close, drop, block = flow.steps
    assert (claim.kind, claim.tool) == ("tool", "bd_claim")
    assert work.needs == ("claim",)
    assert (merge.kind, merge.tool) == ("tool", "worktree_merge")
    assert merge.needs == ("work",)
    assert (close.kind, close.tool) == ("tool", "bd_close")
    assert close.needs == ("merge",)
    assert (drop.kind, drop.tool) == ("tool", "worktree_drop")
    assert drop.needs == ("work",)
    assert (block.kind, block.tool) == ("tool", "bd_block")
    assert block.needs == ("work", "merge")


def test_bead_flow_templates_render_without_leftovers() -> None:
    """Every prompt/arg/skip_if renders over the fake context with no leftover templates."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    for isolation in ("", "none"):
        ctx = _context(isolation)
        for step in flow.steps:
            if step.prompt:
                assert "{{" not in render(step.prompt, ctx)
            for value in step.args.values():
                assert "{{" not in render(value, ctx)
            if step.skip_if is not None:
                assert isinstance(render_bool(step.skip_if, ctx), bool)


def test_bead_flow_merge_and_drop_skip_without_worktree() -> None:
    """merge/drop run for isolation='' and skip for isolation='none'."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    assert render_bool(flow.step("merge").skip_if or "false", _context("")) is False
    assert render_bool(flow.step("merge").skip_if or "false", _context("none")) is True
    assert render_bool(flow.step("drop").skip_if or "false", _context("")) is False
    assert render_bool(flow.step("drop").skip_if or "false", _context("none")) is True


def test_bead_flow_work_prompt_names_bead_and_merge_rules() -> None:
    """The work prompt names the bead and tells the coder to commit by path, in ≤12 lines."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    prompt = render(flow.step("work").prompt, _context(""))
    assert _BEAD_ID in prompt
    assert "commit" in prompt.lower()
    assert "nothing outside" in prompt
    assert len(prompt.splitlines()) <= 12


def test_bead_flow_work_isolation_falls_back_to_defaults() -> None:
    """Empty inputs.isolation renders the work isolation to the worktree default."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    assert flow.step("work").isolation is not None
    assert render(flow.step("work").isolation or "", _context("")) == "worktree"
    assert render(flow.step("work").isolation or "", _context("none")) == "none"


def test_bead_flow_merge_task_arg_is_run_dot_work() -> None:
    """merge/drop task args render to the work step's task id."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    ctx = _context("")
    assert render(flow.step("merge").args["task"], ctx) == f"{_RUN_ID}.work"
    assert render(flow.step("drop").args["task"], ctx) == f"{_RUN_ID}.work"


def test_bead_flow_close_reason_carries_run_id() -> None:
    """The close reason renders with the run id and the bead id."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    ctx = _context("")
    assert render(flow.step("close").args["id"], ctx) == _BEAD_ID
    assert _RUN_ID in render(flow.step("close").args["reason"], ctx)


def test_bead_flow_block_reason_names_run_and_step_statuses() -> None:
    """The block reason renders with the run id and the work/merge statuses."""
    catalog = folders.load(["builtin"])
    flow = catalog.flows["bead"]
    reason = render(flow.step("block").args["reason"], _context(""))
    assert _RUN_ID in reason
    assert "work failed" in reason
    assert "merge failed" in reason
    assert "fleet flow status" in reason


def test_bd_claim_tool_claims_by_id() -> None:
    """bd_claim runs `bd update <id> --claim` with a 60s text timeout."""
    catalog = folders.load(["builtin"])
    assert catalog.problems == []
    tool = catalog.tools["bd_claim"]
    assert tool.output == "text"
    assert tool.timeout == 60
    assert command_for(tool, {"id": _BEAD_ID}) == ["bd", "update", _BEAD_ID, "--claim"]


def test_bd_ready_tool_polls_fleet_ready_json() -> None:
    """bd_ready runs `fleet ready --json` (task.json context bd ready cannot give)."""
    catalog = folders.load(["builtin"])
    tool = catalog.tools["bd_ready"]
    assert tool.output == "json"
    assert command_for(tool, {}) == ["fleet", "ready", "--json"]
    assert "bd ready" in tool.description


def test_bd_block_tool_blocks_with_reason() -> None:
    """bd_block runs `fleet block <id> --reason <reason>` with required id and reason."""
    catalog = folders.load(["builtin"])
    tool = catalog.tools["bd_block"]
    assert tool.output == "text"
    assert {arg.name for arg in tool.args if arg.required} == {"id", "reason"}
    assert command_for(tool, {"id": _BEAD_ID, "reason": "stuck"}) == [
        "fleet",
        "block",
        _BEAD_ID,
        "--reason",
        "stuck",
    ]
