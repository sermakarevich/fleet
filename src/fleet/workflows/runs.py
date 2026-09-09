"""Run engine: the one place that opens workflow beads on the queue.

Called by the serve API, the scheduler, and the CLI: `start_run` turns a
saved workflow into beads (stage by stage, dependencies passed at creation
time so the supervisor never sees a half-wired graph), `refresh_run` folds
the beads' statuses back into the run, and `cancel_run` closes waiting
beads and kills running ones through `state.task_actions`. Pure planning
(order, labels, metadata, status table) lives in `planning.py`.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping
from datetime import UTC, datetime

from fleet.beads.client import BdError
from fleet.beads.queue import Queue
from fleet.core.errors import WorkflowInvalid
from fleet.core.task import Task, TaskStatus
from fleet.state import task_actions
from fleet.workflows.model import (
    RunStatus,
    StepRun,
    StepState,
    Trigger,
    Workflow,
    WorkflowRun,
    ensure_valid,
    new_run_id,
    step_state_of,
)
from fleet.workflows.planning import (
    META_RUN_ID,
    PlannedStep,
    derive_status,
    labels_for,
    metadata_for,
    plan,
)
from fleet.workflows.store import WorkflowStore
from fleet.workflows.templates import TemplateContext, render


def resolve_inputs(workflow: Workflow, given: Mapping[str, str] | None) -> dict[str, str]:
    """Merge operator values with input defaults; unknown/missing is invalid."""
    supplied = dict(given) if given is not None else {}
    declared = {item.name: item for item in workflow.inputs}
    unknown = sorted(set(supplied) - set(declared))
    if unknown:
        raise WorkflowInvalid(
            [
                f"input {name!r}: unknown input (declared: {', '.join(declared) or 'none'})"
                for name in unknown
            ]
        )
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for item in workflow.inputs:
        if item.name in supplied:
            resolved[item.name] = supplied[item.name]
        elif item.default is not None:
            resolved[item.name] = item.default
        elif item.required:
            missing.append(f"input {item.name!r}: required but no value given")
    if missing:
        raise WorkflowInvalid(missing)
    return resolved


def _as_utc(moment: datetime) -> datetime:
    """Return `moment` as aware UTC (naive values are assumed UTC)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _extra_args(
    priority: int | None, labels: list[str], meta: dict[str, str], dep_ids: list[str]
) -> str:
    """Extra `bd create` args: priority, labels, metadata, and dep wiring."""
    quoted = shlex.quote(json.dumps(meta))
    args = f"-p {priority} -l {','.join(labels)} --metadata {quoted}"
    if dep_ids:
        args += f" --deps {','.join(dep_ids)}"
    return args


def _open_step(
    workflow: Workflow,
    run: WorkflowRun,
    run_n: int,
    run_date: str,
    planned: PlannedStep,
    task_ids: dict[str, str],
    queue: Queue,
) -> Task:
    """Render one step's text and open its bead with dep ids already wired."""
    step = planned.step
    ctx = TemplateContext(
        workflow_name=workflow.name,
        run_id=run.id,
        run_n=run_n,
        run_date=run_date,
        step_name=step.name,
        task_ids=dict(task_ids),
        inputs=dict(run.inputs),
    )
    dep_ids = [task_ids[name] for name in planned.depends_on_names]
    meta = metadata_for(workflow.id, run.id, step)
    return queue.create_task(
        render(step.title, ctx),
        render(step.description, ctx) or None,
        cwd=step.cwd,
        coder=step.coder,
        model=step.model,
        extra_args=_extra_args(
            step.priority, labels_for(workflow.id, run.id, step.name), meta, dep_ids
        ),
    )


def _step_run(run_id: str, planned: PlannedStep, task_id: str, stamp: str) -> StepRun:
    """One fresh step row: just opened, so its task is still open."""
    return StepRun(
        run_id=run_id,
        step_name=planned.step.name,
        stage_index=planned.stage_index,
        task_id=task_id,
        task_status=TaskStatus.OPEN.value,
        updated_at=stamp,
    )


def start_run(
    workflow: Workflow,
    *,
    store: WorkflowStore,
    queue: Queue,
    now: datetime,
    trigger: Trigger,
    schedule_id: str | None = None,
    inputs: Mapping[str, str] | None = None,
) -> WorkflowRun:
    """Open every step's bead stage by stage and record the run as running."""
    ensure_valid(workflow)
    resolved = resolve_inputs(workflow, inputs)
    n = store.run_count(workflow.id) + 1
    stamp = now.isoformat()
    run = WorkflowRun(
        id=new_run_id(),
        workflow_id=workflow.id,
        n=n,
        trigger=trigger,
        schedule_id=schedule_id,
        spec=workflow,
        status=RunStatus.running,
        started_at=stamp,
        inputs=resolved,
    )
    store.save_run(run)
    run_date = _as_utc(now).date().isoformat()
    task_ids: dict[str, str] = {}
    for planned in plan(workflow):
        try:
            task = _open_step(workflow, run, n, run_date, planned, task_ids, queue)
        except BdError as exc:
            reason = f"create failed at step {planned.step.name}: {exc}"
            store.finish_run(run.id, RunStatus.attention, reason, stamp)
            raise
        task_ids[planned.step.name] = task.id
        store.save_step_runs([_step_run(run.id, planned, task.id, stamp)])
    return run


def _live_statuses(queue: Queue, run_id: str) -> dict[str, str]:
    """Current task statuses for one run, keyed by task id (one bd call)."""
    return {task.id: task.status for task in queue.list_by_metadata(META_RUN_ID, run_id)}


def refresh_run_with_tasks(
    run: WorkflowRun, *, store: WorkflowStore, queue: Queue, now: datetime
) -> tuple[WorkflowRun, list[Task]]:
    """Refresh a run and return the fetched tasks (one bd call, shared)."""
    if run.status in (RunStatus.cancelled, RunStatus.succeeded):
        return run, []
    stamp = now.isoformat()
    try:
        tasks = queue.list_by_metadata(META_RUN_ID, run.id)
    except BdError:
        tasks = []
    live = {task.id: task.status for task in tasks}
    steps = store.step_runs(run.id)
    for step in steps:
        status = live.get(step.task_id)
        if status is not None and status != step.task_status:
            store.update_step_status(run.id, step.step_name, status, stamp)
    states = [step_state_of(live.get(step.task_id, step.task_status)) for step in steps]
    status = derive_status(states, cancelled=False)
    if run.status == RunStatus.running and status is not RunStatus.running:
        store.finish_run(run.id, status, run.reason, stamp)
        finished = store.get_run(run.id)
        return (finished if finished is not None else run), tasks
    return run, tasks


def enrich(run: WorkflowRun, tasks: list[Task]) -> dict[str, Task]:
    """Tasks of one run keyed by task id (titles for the run detail view)."""
    _ = run
    return {task.id: task for task in tasks}


def refresh_run(
    run: WorkflowRun, *, store: WorkflowStore, queue: Queue, now: datetime
) -> WorkflowRun:
    """Fold the beads' statuses into the run; finished runs are untouched."""
    refreshed, _ = refresh_run_with_tasks(run, store=store, queue=queue, now=now)
    return refreshed


def cancel_run(
    run: WorkflowRun,
    *,
    store: WorkflowStore,
    queue: Queue,
    now: datetime,
    reason: str = "cancelled by operator",
    supervisor_running: bool = False,
) -> WorkflowRun:
    """Close waiting beads, kill running ones, and mark the run cancelled."""
    fleet_home = store.db_path.parent
    for step in store.step_runs(run.id):
        if step.task_status == TaskStatus.CLOSED.value:
            continue
        if step.task_status == TaskStatus.IN_PROGRESS.value:
            task_actions.kill(
                fleet_home,
                queue,
                step.task_id,
                status=step.task_status,
                supervisor_running=supervisor_running,
            )
        else:
            queue.close(step.task_id, reason)
    store.finish_run(run.id, RunStatus.cancelled, reason, now.isoformat())
    finished = store.get_run(run.id)
    return finished if finished is not None else run


def step_states(run: WorkflowRun, *, store: WorkflowStore) -> dict[str, StepState]:
    """One run's step states by step name, for the API run detail view."""
    return {step.step_name: step_state_of(step.task_status) for step in store.step_runs(run.id)}
