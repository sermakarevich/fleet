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
import logging
import re
import shlex
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from fleet.beads.client import BdError
from fleet.beads.queue import Queue
from fleet.core.errors import WorkflowInvalid, WorkflowSourceUnavailable
from fleet.core.task import Task, TaskStatus
from fleet.state import task_actions
from fleet.state.paths import read_outputs, task_dir
from fleet.workflows import builders
from fleet.workflows.builders.sources import SourceError
from fleet.workflows.model import (
    RunStatus,
    Step,
    StepRun,
    StepState,
    Trigger,
    Workflow,
    WorkflowRun,
    dependencies_of,
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
from fleet.workflows.templates import TemplateContext, render, render_with_missing

logger = logging.getLogger(__name__)

#: Far-future deferral for later-stage beads: parked until the release pass
#: renders their text and un-defers them (never claimed while deferred).
DEFER_FAR = "+30d"

#: One `outputs_missing` entry (`steps.<name>.outputs.<key>`) back to its
#: upstream step name; mirrors the entry shape built by `templates.py`.
_MISSING_OUTPUT_RE = re.compile(r"steps\.([a-z0-9][a-z0-9_-]*)\.outputs\.(.+)")


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
    priority: int | None,
    labels: list[str],
    meta: dict[str, str],
    dep_ids: list[str],
    defer: str | None = None,
) -> str:
    """Extra `bd create` args: priority, labels, metadata, dep wiring, deferral."""
    quoted = shlex.quote(json.dumps(meta))
    args = f"-p {priority} -l {','.join(labels)} --metadata {quoted}"
    if dep_ids:
        args += f" --deps {','.join(dep_ids)}"
    if defer is not None:
        args += f" --defer {defer}"
    return args


def _open_step(
    workflow: Workflow,
    run: WorkflowRun,
    run_n: int,
    run_date: str,
    planned: PlannedStep,
    task_ids: dict[str, str],
    queue: Queue,
    defer: str | None = None,
) -> Task:
    """Open one step's bead with dep ids already wired.

    Stage-1 steps render their text now; deferred (stage 2+) steps keep
    their raw placeholders — the release pass renders them once the
    dependencies close and their outputs exist.
    """
    step = planned.step
    if defer is not None:
        title, description = step.title, step.description
    else:
        ctx = TemplateContext(
            workflow_name=workflow.name,
            run_id=run.id,
            run_n=run_n,
            run_date=run_date,
            step_name=step.name,
            task_ids=dict(task_ids),
            inputs=dict(run.inputs),
        )
        title, description = render(step.title, ctx), render(step.description, ctx)
    dep_ids = [task_ids[name] for name in planned.depends_on_names]
    meta = metadata_for(workflow.id, run.id, step)
    return queue.create_task(
        title,
        description or None,
        cwd=step.cwd,
        coder=step.coder,
        model=step.model,
        extra_args=_extra_args(
            step.priority, labels_for(workflow.id, run.id, step.name), meta, dep_ids, defer
        ),
    )


def _step_run(
    run_id: str, planned: PlannedStep, task_id: str, stamp: str, released: bool
) -> StepRun:
    """One fresh step row: just opened, so its task is still open."""
    return StepRun(
        run_id=run_id,
        step_name=planned.step.name,
        stage_index=planned.stage_index,
        task_id=task_id,
        task_status=TaskStatus.OPEN.value,
        updated_at=stamp,
        released=released,
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
    run_id = new_run_id()
    ctx = builders.BuildContext(
        run_id=run_id, fleet_home=store.db_path.parent, now=now, inputs=resolved
    )
    try:
        expanded = builders.expand(workflow, ctx)
    except WorkflowSourceUnavailable:
        raise
    except (SourceError, ValueError) as exc:
        problem = f"builder {workflow.builder}: {exc}"
        if isinstance(exc, SourceError) and exc.transient:
            raise WorkflowSourceUnavailable([problem]) from exc
        raise WorkflowInvalid([problem]) from exc
    if expanded is not workflow:
        expanded = replace(expanded, builder=None)  # concrete stages now; no re-expansion
        ensure_valid(expanded)
    n = store.run_count(workflow.id) + 1
    stamp = now.isoformat()
    run = WorkflowRun(
        id=run_id,
        workflow_id=workflow.id,
        n=n,
        trigger=trigger,
        schedule_id=schedule_id,
        spec=expanded,
        status=RunStatus.running,
        started_at=stamp,
        inputs=resolved,
    )
    store.save_run(run)
    run_date = _as_utc(now).date().isoformat()
    task_ids: dict[str, str] = {}
    for planned in plan(expanded):
        # Stage 1 renders and opens now; later stages park deferred with
        # raw text until the release pass renders them (ADR 0010).
        defer = None if planned.stage_index == 0 else DEFER_FAR
        try:
            task = _open_step(expanded, run, n, run_date, planned, task_ids, queue, defer)
        except BdError as exc:
            reason = f"create failed at step {planned.step.name}: {exc}"
            store.finish_run(run.id, RunStatus.failed, reason, stamp)
            raise
        task_ids[planned.step.name] = task.id
        store.save_step_runs([_step_run(run.id, planned, task.id, stamp, defer is None)])
    return run


def _run_date_of(run: WorkflowRun, now: datetime) -> str:
    """The run's calendar date (stage 1 rendered its text with the start date)."""
    try:
        return _as_utc(datetime.fromisoformat(run.started_at)).date().isoformat()
    except ValueError:
        return _as_utc(now).date().isoformat()


def _step_by_name(run: WorkflowRun) -> dict[str, Step]:
    """Frozen spec steps by name (the text source for the release render)."""
    return {step.name: step for stage in run.spec.stages for step in stage.steps}


def _collect_outputs(
    run: WorkflowRun,
    steps: list[StepRun],
    live: dict[str, str],
    fleet_home: Path,
    store: WorkflowStore,
    stamp: str,
) -> list[StepRun]:
    """Read outputs.json for freshly closed steps; return steps with new outputs."""
    fresh: list[StepRun] = []
    for step in steps:
        status = live.get(step.task_id, step.task_status)
        if status != TaskStatus.CLOSED.value or step.outputs:
            fresh.append(step)
            continue
        outputs = read_outputs(task_dir(fleet_home, step.task_id))
        if outputs != step.outputs:
            store.set_step_outputs(run.id, step.step_name, outputs, stamp)
            fresh.append(replace(step, outputs=outputs, updated_at=stamp))
        else:
            fresh.append(step)
    return fresh


def _missing_step_name(entry: str) -> str | None:
    """Upstream step name of an `outputs_missing` entry, or None when foreign."""
    match = _MISSING_OUTPUT_RE.fullmatch(entry)
    return match.group(1) if match is not None else None


def _release_ready(
    run: WorkflowRun,
    steps: list[StepRun],
    live: dict[str, str],
    store: WorkflowStore,
    queue: Queue,
    now: datetime,
    stamp: str,
) -> str | None:
    """Render and un-defer steps whose dependencies all closed.

    Text is written to the bead before it is un-deferred, so no claim
    can ever see unrendered placeholders. One failing bead never stops
    the rest of the pass; it retries on the next one.

    A step whose text needs an upstream output that does not exist yet is
    held deferred (its `outputs_missing` warning is still recorded) so no
    worker ever receives a prompt with an empty substitution; the next
    refresh releases it once the output lands. When the upstream step
    already closed without writing that key, the output can never arrive:
    the step stays held and the returned reason asks the caller to finish
    the run as `failed` instead of stalling silently. None means no step
    is doomed.
    """
    by_name = _step_by_name(run)
    by_step = {item.step_name: item for item in steps}
    closed = {
        item.step_name
        for item in steps
        if live.get(item.task_id, item.task_status) == TaskStatus.CLOSED.value
    }
    doomed: list[str] = []
    for step in steps:
        if step.released:
            continue
        defined = by_name.get(step.step_name)
        if defined is None:
            continue
        needs = dependencies_of(run.spec, step.stage_index, defined)
        if any(name not in closed for name in needs):
            continue
        ctx = TemplateContext(
            workflow_name=run.spec.name,
            run_id=run.id,
            run_n=run.n,
            run_date=_run_date_of(run, now),
            step_name=step.step_name,
            task_ids={item.step_name: item.task_id for item in steps},
            inputs=dict(run.inputs),
            step_outputs={item.step_name: dict(item.outputs) for item in steps},
        )
        title, missing_title = render_with_missing(defined.title, ctx)
        description, missing_description = render_with_missing(defined.description, ctx)
        missing = sorted(set(missing_title) | set(missing_description))
        warning = f"outputs_missing: {', '.join(missing)}" if missing else None
        if step.step_name in closed:
            # The bead closed before release (manual close or cancel):
            # nothing to un-defer, just record the warning and move on.
            store.mark_step_released(run.id, step.step_name, warning, stamp)
            continue
        if missing:
            # Hold the bead deferred: releasing it now would hand a worker
            # instructions with an empty substitution. The warning stays so
            # the stall is visible on the run detail view.
            store.set_step_warning(run.id, step.step_name, warning, stamp)
            dead = sorted(
                {
                    entry
                    for entry in missing
                    if (_missing_step_name(entry) not in by_step)
                    or (_missing_step_name(entry) in closed)
                }
            )
            if dead:
                doomed.append(
                    f"step {step.step_name} needs {', '.join(dead)} "
                    "from a closed step that never wrote it"
                )
            continue
        try:
            queue.update_task(step.task_id, title=title, description=description, undefer=True)
        except BdError as exc:
            logger.warning(
                "workflow_step_release_failed: run %s step %s (%s)",
                run.id,
                step.step_name,
                exc,
            )
            continue
        store.mark_step_released(run.id, step.step_name, warning, stamp)
    if doomed:
        return f"outputs_missing: {'; '.join(doomed)}"
    return None


def refresh_run_with_tasks(
    run: WorkflowRun, *, store: WorkflowStore, queue: Queue, now: datetime
) -> tuple[WorkflowRun, list[Task]]:
    """Refresh a run and return the fetched tasks (one bd call, shared).

    `running` and `attention` are both live: attention is transient by
    design (it holds only while some step is blocked), so an attention run
    whose block clears re-derives `running` and reopens.
    """
    if run.status in (RunStatus.cancelled, RunStatus.succeeded, RunStatus.failed):
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
    if run.status in (RunStatus.running, RunStatus.attention):
        fleet_home = store.db_path.parent
        fresh = _collect_outputs(run, steps, live, fleet_home, store, stamp)
        doomed = _release_ready(run, fresh, live, store, queue, now, stamp)
        if doomed is not None:
            store.finish_run(run.id, RunStatus.failed, doomed, stamp)
            finished = store.get_run(run.id)
            return (finished if finished is not None else run), tasks
    states = [step_state_of(live.get(step.task_id, step.task_status)) for step in steps]
    status = derive_status(states, cancelled=False)
    if run.status == RunStatus.running and status is not RunStatus.running:
        store.finish_run(run.id, status, run.reason, stamp)
        finished = store.get_run(run.id)
        return (finished if finished is not None else run), tasks
    if run.status == RunStatus.attention and status is not RunStatus.attention:
        if status is RunStatus.running:
            store.reopen_run(run.id)
        else:
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


def _close_cancelled_step(
    store: WorkflowStore,
    queue: Queue,
    run_id: str,
    step: StepRun,
    reason: str,
    stamp: str,
) -> None:
    """Close one step's bead and sync its stored row; one failure never aborts."""
    try:
        queue.close(step.task_id, reason)
    except BdError as exc:
        logger.warning(
            "workflow_cancel_close_failed: run %s step %s (%s): %s",
            run_id,
            step.step_name,
            step.task_id,
            exc,
        )
        return
    store.update_step_status(run_id, step.step_name, TaskStatus.CLOSED.value, stamp)


def cancel_run(
    run: WorkflowRun,
    *,
    store: WorkflowStore,
    queue: Queue,
    now: datetime,
    reason: str = "cancelled by operator",
    supervisor_running: bool = False,
) -> WorkflowRun:
    """Close every live step bead, kill running ones, mark the run cancelled.

    Live status (from the run's beads) wins over the stored step rows, so a
    bead the db thinks is closed but is actually open still gets closed.
    Deferred (not yet released) beads count as live and close like any other
    waiting bead. Each close is best effort: one failing bead is logged and
    never orphans the rest. Stored rows are synced to closed, so cancelling
    twice is a no-op. Bead close reason is always
    ``workflow run <run id> cancelled``; ``reason`` only labels the run.
    """
    fleet_home = store.db_path.parent
    stamp = now.isoformat()
    close_reason = f"workflow run {run.id} cancelled"
    steps = store.step_runs(run.id)
    try:
        live = {task.id: task.status for task in queue.list_by_metadata(META_RUN_ID, run.id)}
    except BdError as exc:
        logger.warning("workflow_cancel_list_failed: run %s: %s", run.id, exc)
        live = {}
    step_ids = {step.task_id for step in steps}
    for step in steps:
        status = live.get(step.task_id, step.task_status)
        if status == TaskStatus.CLOSED.value:
            if step.task_status != TaskStatus.CLOSED.value:
                store.update_step_status(run.id, step.step_name, TaskStatus.CLOSED.value, stamp)
            continue
        if status == TaskStatus.IN_PROGRESS.value:
            try:
                task_actions.kill(
                    fleet_home,
                    queue,
                    step.task_id,
                    status=status,
                    supervisor_running=supervisor_running,
                )
            except task_actions.TaskNotFound:
                # Task dir is gone so no worker can hold it: close directly.
                logger.warning(
                    "workflow_cancel_missing_task_dir: run %s step %s (%s)",
                    run.id,
                    step.step_name,
                    step.task_id,
                )
                _close_cancelled_step(store, queue, run.id, step, close_reason, stamp)
            continue
        _close_cancelled_step(store, queue, run.id, step, close_reason, stamp)
    for task_id, status in live.items():
        if task_id in step_ids or status == TaskStatus.CLOSED.value:
            continue
        if status == TaskStatus.IN_PROGRESS.value:
            continue  # running beads are killed through their step rows above
        try:
            queue.close(task_id, close_reason)
        except BdError as exc:
            logger.warning(
                "workflow_cancel_close_failed: run %s orphan %s: %s", run.id, task_id, exc
            )
    store.finish_run(run.id, RunStatus.cancelled, reason, stamp)
    finished = store.get_run(run.id)
    return finished if finished is not None else run


def step_states(run: WorkflowRun, *, store: WorkflowStore) -> dict[str, StepState]:
    """One run's step states by step name, for the API run detail view."""
    return {step.step_name: step_state_of(step.task_status) for step in store.step_runs(run.id)}
