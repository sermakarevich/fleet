"""Planning tests: creation order, deps, labels/metadata, status table."""

from __future__ import annotations

from fleet.workflows.model import Defaults, RunStatus, Stage, Step, StepState, Workflow
from fleet.workflows.planning import derive_status, labels_for, metadata_for, plan


def _workflow() -> Workflow:
    """Two stages: collect+tests in parallel, then a summary fan-in."""
    return Workflow(
        id="wf-plan0001",
        name="nightly",
        description="d",
        defaults=Defaults(cwd="/repo", coder="opencode", model="m", priority=2),
        stages=(
            Stage(
                name="checks",
                steps=(
                    Step(name="lint", title="Lint"),
                    Step(name="tests", title="Tests", coder="claude"),
                ),
            ),
            Stage(
                name="report",
                steps=(Step(name="summary", title="Summary"),),
            ),
        ),
    )


def test_plan_creation_order_stage_by_stage() -> None:
    planned = plan(_workflow())
    assert [item.step.name for item in planned] == ["lint", "tests", "summary"]
    assert [item.stage_index for item in planned] == [0, 0, 1]


def test_plan_default_deps_fan_in_from_previous_stage() -> None:
    planned = {item.step.name: item for item in plan(_workflow())}
    assert planned["lint"].depends_on_names == ()
    assert planned["tests"].depends_on_names == ()
    assert planned["summary"].depends_on_names == ("lint", "tests")


def test_plan_explicit_needs_subset_only() -> None:
    workflow = _workflow()
    fast = Stage(name="fast", steps=(Step(name="quick", title="Q", needs=("lint",)),))
    workflow = Workflow(
        id=workflow.id,
        name=workflow.name,
        defaults=workflow.defaults,
        stages=(*workflow.stages, fast),
    )
    planned = {item.step.name: item for item in plan(workflow)}
    assert planned["quick"].depends_on_names == ("lint",)


def test_plan_fills_effective_defaults() -> None:
    planned = {item.step.name: item for item in plan(_workflow())}
    assert (planned["lint"].step.cwd, planned["lint"].step.coder) == ("/repo", "opencode")
    assert planned["tests"].step.coder == "claude"
    assert planned["summary"].step.priority == 2


def test_labels_for_shape() -> None:
    assert labels_for("wf-1", "wfr-2", "lint") == [
        "workflow:wf-1",
        "run:wfr-2",
        "step:lint",
    ]


def test_metadata_for_carries_routing_keys_when_set() -> None:
    step = Step(name="lint", title="T", cwd="/repo", coder="opencode", model="m")
    assert metadata_for("wf-1", "wfr-2", step) == {
        "fleet_workflow_id": "wf-1",
        "fleet_workflow_run": "wfr-2",
        "fleet_workflow_step": "lint",
        "fleet_cwd": "/repo",
        "fleet_coder": "opencode",
        "fleet_model": "m",
    }


def test_metadata_for_omits_unset_routing_keys() -> None:
    assert metadata_for("wf-1", "wfr-2", Step(name="lint", title="T")) == {
        "fleet_workflow_id": "wf-1",
        "fleet_workflow_run": "wfr-2",
        "fleet_workflow_step": "lint",
    }


def test_derive_status_table() -> None:
    waiting, running, done, blocked = (
        StepState.waiting,
        StepState.running,
        StepState.done,
        StepState.attention,
    )
    assert derive_status([done, done], cancelled=False) is RunStatus.succeeded
    assert derive_status([done, blocked], cancelled=False) is RunStatus.attention
    assert derive_status([done, waiting], cancelled=False) is RunStatus.running
    assert derive_status([waiting, running], cancelled=False) is RunStatus.running
    assert derive_status([], cancelled=False) is RunStatus.running
    assert derive_status([done, done], cancelled=True) is RunStatus.cancelled
    assert derive_status([blocked], cancelled=True) is RunStatus.cancelled
