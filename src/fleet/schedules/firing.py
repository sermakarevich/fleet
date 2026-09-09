"""Firing policy for schedules: what is due, overlap, and opening the task.

Pure `decide()` answers "is this schedule due now, and should it open a task
or record a skip" (ADR 0006 rule "pure policy is a pure function"); `fire()`
is the one writer of cron and manual runs, and `fire_due()` ticks every
enabled schedule. Called by the supervisor's scheduler service (cron runs)
and, later, the serve API / CLI (manual "Run now"); both share this path.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fleet.beads.client import BdError
from fleet.beads.queue import Queue
from fleet.core.errors import WorkflowInvalid
from fleet.schedules.cron import next_fire
from fleet.schedules.model import (
    OverlapPolicy,
    Schedule,
    ScheduleRun,
    TargetKind,
    Trigger,
    render,
)
from fleet.schedules.store import ScheduleStore
from fleet.workflows.model import RunStatus
from fleet.workflows.model import Trigger as WorkflowTrigger
from fleet.workflows.runs import start_run
from fleet.workflows.store import WorkflowStore


class Action(StrEnum):
    """What the firing policy wants: open a task, record a skip, or wait."""

    open = "open"
    skip = "skip"
    wait = "wait"


@dataclass(frozen=True, slots=True)
class Decision:
    """The pure outcome of `decide()`: an action plus when and why."""

    action: Action
    scheduled_for: datetime | None
    reason: str


def _as_utc(moment: datetime) -> datetime:
    """Return `moment` as aware UTC (naive values are assumed UTC)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _parse_moment(raw: str) -> datetime:
    """Parse a stored ISO-8601 timestamp as aware UTC."""
    return _as_utc(datetime.fromisoformat(raw))


def _coalesce(schedule: Schedule, first_due: datetime, now: datetime) -> datetime:
    """Advance past missed minutes so the run covers the latest one."""
    due = first_due
    while next_fire(schedule.cron, due, schedule.timezone) <= now:
        due = next_fire(schedule.cron, due, schedule.timezone)
    return due


def decide(
    schedule: Schedule,
    last_cron_run: ScheduleRun | None,
    previous_task_status: str | None,
    now: datetime,
) -> Decision:
    """Say whether `schedule` is due at `now`, and open, skip, or wait."""
    moment = _as_utc(now)
    if not schedule.enabled:
        return Decision(Action.wait, None, "disabled")
    if last_cron_run is not None:
        baseline = _parse_moment(last_cron_run.scheduled_for)
    else:
        baseline = _parse_moment(schedule.created_at)
    first_due = next_fire(schedule.cron, baseline, schedule.timezone)
    due = _coalesce(schedule, first_due, moment)
    if due > moment:
        return Decision(Action.wait, None, f"next at {due.isoformat()}")
    if schedule.overlap == OverlapPolicy.skip and previous_task_status not in (None, "closed"):
        return Decision(Action.skip, due, f"previous task is {previous_task_status}")
    return Decision(Action.open, due, "due")


def next_due(
    schedule: Schedule,
    last_cron_run: ScheduleRun | None,
    now: datetime,
) -> datetime | None:
    """Next firing for display: None when disabled, else after baseline or now."""
    if not schedule.enabled:
        return None
    moment = _as_utc(now)
    if last_cron_run is not None:
        baseline = _parse_moment(last_cron_run.scheduled_for)
    else:
        baseline = _parse_moment(schedule.created_at)
    first = next_fire(schedule.cron, baseline, schedule.timezone)
    if first <= moment:
        return next_fire(schedule.cron, moment, schedule.timezone)
    return first


def _metadata(schedule: Schedule, run_n: int) -> dict[str, Any]:
    """Bead metadata mirroring `beads/create_args.py` fleet_* keys."""
    meta: dict[str, Any] = {
        "fleet_schedule_id": schedule.id,
        "fleet_schedule_run": run_n,
    }
    if schedule.cwd is not None:
        meta["fleet_cwd"] = schedule.cwd
    if schedule.coder is not None:
        meta["fleet_coder"] = schedule.coder
    if schedule.model is not None:
        meta["fleet_model"] = schedule.model
    return meta


def _extra_args(schedule: Schedule, run_n: int) -> str:
    """Extra `bd create` args: priority, labels, and quoted metadata JSON."""
    labels = f"recurring,schedule:{schedule.id}"
    metadata = shlex.quote(json.dumps(_metadata(schedule, run_n)))
    return f"-p {schedule.priority} -l {labels} --metadata {metadata}"


def open_task(schedule: Schedule, queue: Queue, run_n: int, when: datetime) -> str:
    """Render the template, open one bead from it, and return the task id."""
    title = render(schedule.title, schedule, run_n, when)
    description = render(schedule.description, schedule, run_n, when)
    task = queue.create_task(
        title,
        description or None,
        cwd=schedule.cwd,
        coder=schedule.coder,
        model=schedule.model,
        extra_args=_extra_args(schedule, run_n),
    )
    return task.id


def _previous_task_open(
    store: ScheduleStore, schedule_id: str, queue: Queue
) -> tuple[str | None, str | None]:
    """Task id and status of the last run that opened a task, if any."""
    for run in store.runs(schedule_id, limit=10_000):
        if run.task_id is None:
            continue
        try:
            return run.task_id, queue.get(run.task_id).status
        except BdError:
            return run.task_id, "closed"
    return None, None


def _previous_workflow_run(
    store: ScheduleStore, schedule_id: str, workflow_store: WorkflowStore | None
) -> tuple[str | None, str | None]:
    """Run id and mapped status of the last run that started a workflow."""
    if workflow_store is None:
        return None, None
    for run in store.runs(schedule_id, limit=10_000):
        if run.workflow_run_id is None:
            continue
        workflow_run = workflow_store.get_run(run.workflow_run_id)
        if workflow_run is None or workflow_run.status in (
            RunStatus.succeeded,
            RunStatus.cancelled,
        ):
            return run.workflow_run_id, "closed"
        return run.workflow_run_id, workflow_run.status.value
    return None, None


def _previous_for_task(
    store: ScheduleStore, schedule: Schedule, queue: Queue, workflow_store: WorkflowStore | None
) -> tuple[str | None, str | None]:
    """Previous status for a task schedule: the last opened bead's status."""
    _ = workflow_store
    return _previous_task_open(store, schedule.id, queue)


def _previous_for_workflow(
    store: ScheduleStore, schedule: Schedule, queue: Queue, workflow_store: WorkflowStore | None
) -> tuple[str | None, str | None]:
    """Previous status for a workflow schedule: the last run's mapped status."""
    _ = queue
    return _previous_workflow_run(store, schedule.id, workflow_store)


_PREVIOUS_STATUS_BY_TARGET = {
    TargetKind.task: _previous_for_task,
    TargetKind.workflow: _previous_for_workflow,
}
"""Dispatch over schedule targets for the overlap-policy baseline."""


def previous_task_status(
    store: ScheduleStore,
    schedule: Schedule | str,
    queue: Queue,
    workflow_store: WorkflowStore | None = None,
) -> tuple[str | None, str | None]:
    """Id and status the overlap policy compares against, by target.

    A plain id means the old task behaviour; a workflow schedule reports its
    last workflow run (mapped to "closed" once finished) instead of a bead.
    """
    if isinstance(schedule, str):
        return _previous_task_open(store, schedule, queue)
    return _PREVIOUS_STATUS_BY_TARGET[schedule.target](store, schedule, queue, workflow_store)


def _record(  # noqa: PLR0913, PLR0917  # one row, one call site shape
    store: ScheduleStore,
    schedule: Schedule,
    run_n: int,
    scheduled_for: datetime,
    now: datetime,
    trigger: Trigger,
    task_id: str | None,
    skipped: bool,
    reason: str,
    workflow_run_id: str | None = None,
) -> ScheduleRun:
    """Append one run row to the store and hand it back."""
    run = ScheduleRun(
        schedule_id=schedule.id,
        n=run_n,
        scheduled_for=scheduled_for.isoformat(),
        fired_at=_as_utc(now).isoformat(),
        trigger=trigger,
        task_id=task_id,
        skipped=skipped,
        reason=reason,
        workflow_run_id=workflow_run_id,
    )
    store.append_run(run)
    return run


def _fire_workflow(  # noqa: PLR0913, PLR0917  # one row, one call site shape
    schedule: Schedule,
    *,
    store: ScheduleStore,
    run_n: int,
    moment: datetime,
    now: datetime,
    trigger: Trigger,
    reason: str,
    queue: Queue,
    workflow_store: WorkflowStore | None,
) -> ScheduleRun:
    """Start one workflow run, or record a skip when its workflow is gone."""
    reason = f"workflow {schedule.workflow_id} not found"
    if workflow_store is None:
        return _record(store, schedule, run_n, moment, now, trigger, None, True, reason)
    workflow = workflow_store.get(schedule.workflow_id or "")
    if workflow is None:
        return _record(store, schedule, run_n, moment, now, trigger, None, True, reason)
    try:
        workflow_run = start_run(
            workflow,
            store=workflow_store,
            queue=queue,
            now=now,
            trigger=WorkflowTrigger(trigger.value),
            schedule_id=schedule.id,
            inputs=dict(schedule.inputs),
        )
    except BdError as exc:
        _record(store, schedule, run_n, moment, now, trigger, None, True, f"bd error: {exc}")
        raise
    except WorkflowInvalid as exc:
        reason = f"inputs invalid: {'; '.join(exc.problems)}"
        _record(store, schedule, run_n, moment, now, trigger, None, True, reason)
        raise
    return _record(
        store,
        schedule,
        run_n,
        moment,
        now,
        trigger,
        None,
        False,
        reason,
        workflow_run.id,
    )


def fire(  # noqa: PLR0913, PLR0917  # one row, one call site shape
    schedule: Schedule,
    *,
    store: ScheduleStore,
    queue: Queue,
    now: datetime,
    trigger: Trigger,
    scheduled_for: datetime | None = None,
    reason: str = "",
    skipped: bool = False,
    workflow_store: WorkflowStore | None = None,
) -> ScheduleRun:
    """Write one run: open a task, start a workflow run, or record a skip."""
    run_n = store.run_count(schedule.id) + 1
    moment = scheduled_for if scheduled_for is not None else now
    if trigger is Trigger.manual:
        moment, skipped = now, False
    if skipped:
        return _record(store, schedule, run_n, moment, now, trigger, None, True, reason)
    if schedule.target is TargetKind.workflow:
        return _fire_workflow(
            schedule,
            store=store,
            run_n=run_n,
            moment=moment,
            now=now,
            trigger=trigger,
            reason=reason,
            queue=queue,
            workflow_store=workflow_store,
        )
    try:
        task_id = open_task(schedule, queue, run_n, moment)
    except BdError as exc:
        _record(store, schedule, run_n, moment, now, trigger, None, True, f"bd error: {exc}")
        raise
    return _record(store, schedule, run_n, moment, now, trigger, task_id, False, reason)


def fire_due(
    *,
    store: ScheduleStore,
    queue: Queue,
    now: datetime,
    log: Any,
    workflow_store: WorkflowStore | None = None,
) -> list[ScheduleRun]:
    """Decide and fire every enabled schedule; one failure never stops the rest."""
    fired: list[ScheduleRun] = []
    for schedule in store.list():
        try:
            last = store.last_run(schedule.id, Trigger.cron)
            _, status = previous_task_status(store, schedule, queue, workflow_store)
            decision = decide(schedule, last, status, now)
            if decision.action is Action.wait:
                continue
            run = fire(
                schedule,
                store=store,
                queue=queue,
                now=now,
                trigger=Trigger.cron,
                scheduled_for=decision.scheduled_for,
                reason=decision.reason,
                skipped=decision.action is Action.skip,
                workflow_store=workflow_store,
            )
        except Exception as exc:
            log.error("schedule_fire_failed", schedule_id=schedule.id, error=str(exc))
            continue
        if run.skipped:
            log.info("schedule_skipped", schedule_id=schedule.id, reason=run.reason, n=run.n)
        else:
            log.info(
                "schedule_fired",
                schedule_id=schedule.id,
                task_id=run.task_id,
                workflow_run_id=run.workflow_run_id,
                n=run.n,
            )
        fired.append(run)
    return fired
