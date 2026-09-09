"""Pure run planning: order steps, label beads, derive run status.

Called by `runs.py` (the run engine) before it touches the queue: `plan`
turns a saved workflow into creation-order steps with resolved dependencies,
`labels_for` / `metadata_for` stamp each step's bead so one metadata query
finds the whole run, and `derive_status` folds step states into the run
status table from ADR 0008. No I/O here, so every function is unit-testable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from fleet.workflows.model import RunStatus, Step, StepState, Workflow, dependencies_of, effective

#: Bead metadata keys stamping every step task back to its workflow run.
META_WORKFLOW_ID = "fleet_workflow_id"
META_RUN_ID = "fleet_workflow_run"
META_STEP_NAME = "fleet_workflow_step"

#: Worker routing keys, reused from the `fleet bd create` wrapper
#: (beads/create_args.py flag specs); only set when the step defines them.
META_CWD = "fleet_cwd"
META_CODER = "fleet_coder"
META_MODEL = "fleet_model"


@dataclass(frozen=True, slots=True)
class PlannedStep:
    """One step ready to open: its stage, effective step, and dep names."""

    stage_index: int
    step: Step
    depends_on_names: tuple[str, ...] = ()


def plan(workflow: Workflow) -> list[PlannedStep]:
    """List every step in creation order with worker defaults filled in."""
    planned: list[PlannedStep] = []
    for stage_index, stage in enumerate(workflow.stages):
        for step in stage.steps:
            planned.append(
                PlannedStep(
                    stage_index=stage_index,
                    step=effective(step, workflow.defaults),
                    depends_on_names=dependencies_of(workflow, stage_index, step),
                )
            )
    return planned


def labels_for(workflow_id: str, run_id: str, step_name: str) -> list[str]:
    """Bead labels stamping one step task back to its workflow run."""
    return [f"workflow:{workflow_id}", f"run:{run_id}", f"step:{step_name}"]


def metadata_for(workflow_id: str, run_id: str, step: Step) -> dict[str, str]:
    """Bead metadata for one step task; routing keys only when set."""
    meta = {
        META_WORKFLOW_ID: workflow_id,
        META_RUN_ID: run_id,
        META_STEP_NAME: step.name,
    }
    if step.cwd is not None:
        meta[META_CWD] = step.cwd
    if step.coder is not None:
        meta[META_CODER] = step.coder
    if step.model is not None:
        meta[META_MODEL] = step.model
    return meta


def derive_status(step_states: Iterable[StepState], cancelled: bool) -> RunStatus:
    """Fold step states into a run status (cancelled wins, then the table)."""
    if cancelled:
        return RunStatus.cancelled
    states = list(step_states)
    if states and all(state is StepState.done for state in states):
        return RunStatus.succeeded
    if any(state is StepState.attention for state in states):
        return RunStatus.attention
    return RunStatus.running
