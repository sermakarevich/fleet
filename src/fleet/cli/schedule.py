"""`fleet schedule` — recurring-worker schedules from the terminal.

Thin typer sub-app (ADR 0006 rule 3): each command parses flags, calls a
module-level `run_*` helper that computes through `schedules.*`, and prints
through `cli/render.py`. Time is read here via `datetime.now(UTC)` only;
everything stored is an ISO-8601 UTC string. Called by `cli/main.py`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from dataclasses import replace as dc_replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from fleet.beads.client import BdError
from fleet.cli import bootstrap, render
from fleet.cli.errors import ExitCode, fail
from fleet.coders import get_coder
from fleet.core.errors import WorkflowInvalid
from fleet.schedules import cron, firing
from fleet.schedules.model import OverlapPolicy, Schedule, TargetKind, Trigger, new_id
from fleet.schedules.store import ScheduleStore
from fleet.state.paths import workflows_db_path
from fleet.workflows.runs import resolve_inputs
from fleet.workflows.store import WorkflowStore

_MIN_PRIORITY = 0
_MAX_PRIORITY = 4
_SHOW_RUN_LIMIT = 20
_UPCOMING_COUNT = 5
_PREVIEW_MAX = 50


@dataclass(frozen=True)
class ScheduleRow:
    """One `fleet schedule list` line: the schedule plus computed columns."""

    schedule: Schedule
    next_run: str | None
    last_run: str | None
    run_count: int
    target: str = "task"


@dataclass(frozen=True)
class RunLine:
    """One run for `fleet schedule show`: the run plus its task's status."""

    n: int
    trigger: str
    scheduled_for: str
    fired_at: str
    skipped: bool
    reason: str
    task_id: str | None
    task_status: str | None
    workflow_run_id: str | None = None
    workflow_run_status: str | None = None


def _store(fleet_home: Path) -> ScheduleStore:
    """Schedule store rooted at *fleet_home*."""
    return ScheduleStore(fleet_home)


def _fetch(store: ScheduleStore, schedule_id: str) -> Schedule:
    """One schedule, exiting NOT_FOUND when the id is unknown."""
    schedule = store.get(schedule_id)
    if schedule is None:
        fail(f"Schedule {schedule_id} not found.", ExitCode.NOT_FOUND)
    return schedule


def _resolve_workflow_id(fleet_home: Path, ref: str) -> str:
    """One workflow id by id (wf- prefix) or name, exiting NOT_FOUND when unknown."""
    store = WorkflowStore(workflows_db_path(fleet_home))
    found = store.get(ref) if ref.startswith("wf-") else store.get_by_name(ref)
    if found is None and not ref.startswith("wf-"):
        found = store.get(ref)
    if found is None:
        fail(f"Workflow {ref} not found.", ExitCode.NOT_FOUND)
    return found.id


def _target_label(fleet_home: Path, schedule: Schedule) -> str:
    """Display target: `task`, or `workflow <name>` for workflow schedules."""
    if schedule.target is not TargetKind.workflow:
        return "task"
    try:
        found = WorkflowStore(workflows_db_path(fleet_home)).get(schedule.workflow_id or "")
    except Exception:
        found = None
    name = found.name if found is not None else (schedule.workflow_id or "-")
    return f"workflow {name}"


def _check_cron(cron_text: str) -> None:
    """Exit USAGE when *cron_text* is not a valid 5-field expression."""
    try:
        cron.parse(cron_text)
    except cron.CronError as exc:
        fail(f"cron: {exc}", ExitCode.USAGE)


def _check_zone(timezone: str) -> None:
    """Exit USAGE when *timezone* is not a known IANA zone name."""
    try:
        cron.zone(timezone)
    except cron.CronError as exc:
        fail(f"timezone: {exc}", ExitCode.USAGE)


def _check_coder(coder: str | None) -> None:
    """Exit USAGE when *coder* names no registered coder CLI."""
    if coder is None:
        return
    try:
        get_coder(coder)
    except ValueError as exc:
        fail(f"coder: {exc}", ExitCode.USAGE)


def _check_cwd(cwd: str | None) -> None:
    """Exit USAGE when *cwd* is set but is not an existing directory."""
    if cwd is not None and not Path(cwd).is_dir():
        fail(f"cwd: not an existing directory: {cwd!r}", ExitCode.USAGE)


def _check_priority(priority: int) -> None:
    """Exit USAGE when *priority* is outside the 0-4 bead range."""
    if not _MIN_PRIORITY <= priority <= _MAX_PRIORITY:
        fail(f"priority: must be 0-4, got {priority}", ExitCode.USAGE)


def _parse_input_pair(raw: str) -> tuple[str, str]:
    """Split one --input name=value pair, exiting USAGE when malformed."""
    name, sep, value = raw.partition("=")
    if not sep or not name:
        fail(f"invalid argument {raw!r} — expected name=value format.", ExitCode.USAGE)
    return name, value


def _check_workflow_inputs(fleet_home: Path, workflow_id: str, given: dict[str, str]) -> None:
    """Exit ERROR naming unknown or missing inputs for a workflow schedule."""
    workflow = WorkflowStore(workflows_db_path(fleet_home)).get(workflow_id)
    if workflow is None:
        fail(f"Workflow {workflow_id} not found.", ExitCode.NOT_FOUND)
    try:
        resolve_inputs(workflow, given)
    except WorkflowInvalid as exc:
        for problem in exc.problems:
            typer.echo(f"invalid: {problem}", err=True)
        raise typer.Exit(int(ExitCode.ERROR)) from None


def _build_schedule(  # noqa: PLR0913, PLR0917  # one schedule, one call shape
    *,
    schedule_id: str,
    name: str,
    cron_text: str,
    timezone: str,
    title: str,
    description: str,
    cwd: str | None,
    coder: str | None,
    model: str | None,
    priority: int,
    overlap: OverlapPolicy,
    enabled: bool,
    created_at: str,
    now: datetime,
    target: TargetKind = TargetKind.task,
    workflow_id: str | None = None,
    inputs: dict[str, str] | None = None,
) -> Schedule:
    """Validate fields like the serve API and return the schedule."""
    if not name.strip():
        fail("name: required and must not be empty", ExitCode.USAGE)
    if target is TargetKind.workflow and not workflow_id:
        fail("workflow: required when the target is a workflow", ExitCode.USAGE)
    if target is TargetKind.task and not title.strip():
        fail("title: required and must not be empty", ExitCode.USAGE)
    _check_cron(cron_text)
    _check_zone(timezone)
    _check_coder(coder)
    _check_cwd(cwd)
    _check_priority(priority)
    return Schedule(
        id=schedule_id,
        name=name,
        cron=cron_text,
        timezone=timezone,
        enabled=enabled,
        title=title,
        description=description,
        cwd=cwd,
        coder=coder,
        model=model,
        priority=priority,
        overlap=overlap,
        target=target,
        workflow_id=workflow_id,
        inputs=inputs or {},
        created_at=created_at,
        updated_at=now.isoformat(),
    )


def _row(store: ScheduleStore, fleet_home: Path, schedule: Schedule, now: datetime) -> ScheduleRow:
    """List row for one schedule: next firing, latest run, run count."""
    last_cron = store.last_run(schedule.id, Trigger.cron)
    due = firing.next_due(schedule, last_cron, now)
    last = store.last_run(schedule.id)
    return ScheduleRow(
        schedule=schedule,
        next_run=due.isoformat() if due is not None else None,
        last_run=last.fired_at if last is not None else None,
        run_count=store.run_count(schedule.id),
        target=_target_label(fleet_home, schedule),
    )


def _row_view(row: ScheduleRow) -> dict[str, Any]:
    """JSON view of one list row (mirrors the serve schedule view)."""
    return {
        **row.schedule.to_dict(),
        "next_fire_at": row.next_run,
        "run_count": row.run_count,
        "last_run_at": row.last_run,
    }


def _task_statuses(fleet_home: Path, schedule_id: str) -> dict[str, str | None]:
    """Task id to status for this schedule's tasks (one bd metadata query)."""
    try:
        tasks = bootstrap.queue(fleet_home).list_by_metadata("fleet_schedule_id", schedule_id)
    except BdError:
        return {}
    return {task.id: task.status for task in tasks}


def _workflow_run_statuses(fleet_home: Path, schedule_id: str) -> dict[str, str | None]:
    """Workflow run id to status for this schedule's workflow runs (no bd call)."""
    try:
        store = WorkflowStore(workflows_db_path(fleet_home))
    except Exception:
        return {}
    try:
        runs = ScheduleStore(fleet_home).runs(schedule_id)
    except Exception:
        return {}
    wanted = {run.workflow_run_id for run in runs if run.workflow_run_id}
    out: dict[str, str | None] = {}
    for run_id in wanted:
        found = store.get_run(run_id)
        out[run_id] = found.status.value if found is not None else None
    return out


def _run_lines(
    store: ScheduleStore,
    schedule_id: str,
    statuses: dict[str, str | None],
    workflow_statuses: dict[str, str | None] | None = None,
) -> list[RunLine]:
    """Newest-first run lines for show, capped at the display limit."""
    workflow_statuses = workflow_statuses if workflow_statuses is not None else {}
    return [
        RunLine(
            n=run.n,
            trigger=run.trigger.value,
            scheduled_for=run.scheduled_for,
            fired_at=run.fired_at,
            skipped=run.skipped,
            reason=run.reason,
            task_id=run.task_id,
            task_status=statuses.get(run.task_id or ""),
            workflow_run_id=run.workflow_run_id,
            workflow_run_status=workflow_statuses.get(run.workflow_run_id or ""),
        )
        for run in store.runs(schedule_id, limit=_SHOW_RUN_LIMIT)
    ]


def run_list(fleet_home: Path, now: datetime, json_output: bool) -> None:
    """Print every schedule as a table (or JSON with --json)."""
    store = _store(fleet_home)
    rows = [_row(store, fleet_home, item, now) for item in store.list()]
    if json_output:
        typer.echo(json.dumps([_row_view(row) for row in rows], indent=2))
        return
    render.print_schedule_list(rows)


def run_create(  # noqa: PLR0913, PLR0917  # one schedule, one call shape
    fleet_home: Path,
    now: datetime,
    *,
    name: str,
    cron_text: str,
    timezone: str,
    title: str,
    description: str,
    cwd: str | None,
    coder: str | None,
    model: str | None,
    priority: int,
    overlap: OverlapPolicy,
    disabled: bool,
    workflow: str | None = None,
    raw_inputs: list[str] | None = None,
) -> None:
    """Validate, save with a fresh id, and print the id."""
    store = _store(fleet_home)
    workflow_id = _resolve_workflow_id(fleet_home, workflow) if workflow else None
    given = dict(_parse_input_pair(raw) for raw in raw_inputs or [])
    if workflow_id is not None:
        _check_workflow_inputs(fleet_home, workflow_id, given)
    schedule = _build_schedule(
        schedule_id=new_id(),
        name=name,
        cron_text=cron_text,
        timezone=timezone,
        title=title,
        description=description,
        cwd=cwd,
        coder=coder,
        model=model,
        priority=priority,
        overlap=overlap,
        enabled=not disabled,
        created_at=now.isoformat(),
        now=now,
        target=TargetKind.workflow if workflow_id else TargetKind.task,
        workflow_id=workflow_id,
        inputs=given,
    )
    store.save(schedule)
    typer.echo(schedule.id)


def run_show(fleet_home: Path, now: datetime, schedule_id: str, json_output: bool) -> None:
    """Print one schedule: definition, next 5 firings, last 20 runs."""
    store = _store(fleet_home)
    schedule = _fetch(store, schedule_id)
    upcoming = [
        fire.isoformat() for fire in cron.upcoming(schedule.cron, now, 5, schedule.timezone)
    ]
    lines = _run_lines(
        store,
        schedule_id,
        _task_statuses(fleet_home, schedule_id),
        _workflow_run_statuses(fleet_home, schedule_id),
    )
    if json_output:
        typer.echo(
            json.dumps(
                {
                    **schedule.to_dict(),
                    "upcoming": upcoming,
                    "runs": [asdict(line) for line in lines],
                },
                indent=2,
            )
        )
        return
    render.print_schedule_show(schedule, upcoming, lines, _target_label(fleet_home, schedule))


def run_edit(  # noqa: PLR0913, PLR0917  # one schedule, one call shape
    fleet_home: Path,
    now: datetime,
    schedule_id: str,
    *,
    name: str | None,
    cron_text: str | None,
    timezone: str | None,
    title: str | None,
    description: str | None,
    cwd: str | None,
    coder: str | None,
    model: str | None,
    priority: int | None,
    overlap: OverlapPolicy | None,
    enabled: bool | None,
    workflow: str | None = None,
    raw_inputs: list[str] | None = None,
) -> None:
    """Rewrite only the given fields, bumping updated_at."""
    store = _store(fleet_home)
    existing = _fetch(store, schedule_id)
    workflow_id = existing.workflow_id
    target = existing.target
    if workflow is not None:
        workflow_id = _resolve_workflow_id(fleet_home, workflow)
        target = TargetKind.workflow
    merged_inputs = dict(existing.inputs)
    for raw in raw_inputs or []:
        name, value = _parse_input_pair(raw)
        merged_inputs[name] = value
    if target is TargetKind.workflow and workflow_id is not None:
        _check_workflow_inputs(fleet_home, workflow_id, merged_inputs)
    merged = _build_schedule(
        schedule_id=existing.id,
        name=existing.name if name is None else name,
        cron_text=existing.cron if cron_text is None else cron_text,
        timezone=existing.timezone if timezone is None else timezone,
        title=existing.title if title is None else title,
        description=existing.description if description is None else description,
        cwd=existing.cwd if cwd is None else cwd,
        coder=existing.coder if coder is None else coder,
        model=existing.model if model is None else model,
        priority=existing.priority if priority is None else priority,
        overlap=existing.overlap if overlap is None else overlap,
        enabled=existing.enabled if enabled is None else enabled,
        created_at=existing.created_at,
        now=now,
        target=target,
        workflow_id=workflow_id,
        inputs=merged_inputs,
    )
    store.save(dc_replace(merged, updated_at=now.isoformat()))
    typer.echo(schedule_id)


def run_set_enabled(fleet_home: Path, now: datetime, schedule_id: str, enabled: bool) -> None:
    """Flip a schedule's enabled flag, bumping updated_at."""
    store = _store(fleet_home)
    existing = _fetch(store, schedule_id)
    store.save(dc_replace(existing, enabled=enabled, updated_at=now.isoformat()))
    typer.echo(f"Schedule {schedule_id} {'enabled' if enabled else 'disabled'}.")


def run_rm(fleet_home: Path, schedule_id: str) -> None:
    """Remove a schedule and its run history."""
    if not _store(fleet_home).delete(schedule_id):
        fail(f"Schedule {schedule_id} not found.", ExitCode.NOT_FOUND)
    typer.echo(f"Removed schedule {schedule_id}.")


def run_fire(fleet_home: Path, now: datetime, schedule_id: str) -> None:
    """Fire one manual run now and print the new task id."""
    store = _store(fleet_home)
    schedule = _fetch(store, schedule_id)
    try:
        run = firing.fire(
            schedule,
            store=store,
            queue=bootstrap.queue(fleet_home),
            now=now,
            trigger=Trigger.manual,
            workflow_store=WorkflowStore(workflows_db_path(fleet_home)),
        )
    except BdError as exc:
        fail(str(exc) or "queue failed", ExitCode.BACKEND)
    except WorkflowInvalid as exc:
        for problem in exc.problems:
            typer.echo(f"invalid: {problem}", err=True)
        raise typer.Exit(int(ExitCode.ERROR)) from None
    typer.echo(run.workflow_run_id or run.task_id)


def run_preview(cron_text: str, timezone: str, count: int) -> None:
    """Print the next *count* firings, or the CronError when invalid."""
    if not 1 <= count <= _PREVIEW_MAX:
        fail(f"count: must be 1-{_PREVIEW_MAX}, got {count}", ExitCode.USAGE)
    try:
        cron.parse(cron_text)
        cron.zone(timezone)
        fires = cron.upcoming(cron_text, datetime.now(UTC), count, timezone)
    except cron.CronError as exc:
        fail(str(exc), ExitCode.USAGE)
    for fire in fires:
        typer.echo(fire.isoformat())


def register(app: typer.Typer) -> None:
    """Wire `fleet schedule` as a thin sub-app over the helpers above."""
    schedule_app = typer.Typer(
        no_args_is_help=True,
        help="Manage recurring-worker schedules (cron templates that open beads).",
        epilog=(
            "Examples:\n\n"
            '  fleet schedule create --name triage --cron "0 9 * * 1-5" --title "Triage"\n'
            "  fleet schedule list\n"
            "  fleet schedule run sch-abc123"
        ),
    )
    app.add_typer(schedule_app, name="schedule")

    @schedule_app.command("list")
    def list_cmd(
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit schedules as JSON.")
        ] = False,
    ) -> None:
        """List every schedule with next run, last run, and run count."""
        run_list(bootstrap.fleet_home(), datetime.now(UTC), json_output)

    @schedule_app.command("create")
    def create_cmd(  # noqa: PLR0913, PLR0917  # create takes one flag per field
        name: Annotated[str, typer.Option("--name", help="Short schedule name.")] = "",
        cron_text: Annotated[str, typer.Option("--cron", help="5-field cron expression.")] = "",
        timezone: Annotated[str, typer.Option("--tz", help="IANA time zone name.")] = "UTC",
        title: Annotated[str, typer.Option("--title", help="Bead title template.")] = "",
        description: Annotated[str, typer.Option("--description", help="Bead body template.")] = "",
        cwd: Annotated[
            str | None, typer.Option("--cwd", help="Working directory for opened tasks.")
        ] = ".",
        coder: Annotated[str | None, typer.Option("--coder", help="Coder CLI override.")] = None,
        model: Annotated[str | None, typer.Option("--model", help="Model override.")] = None,
        priority: Annotated[int, typer.Option("--priority", "-p", help="Bead priority 0-4.")] = 2,
        overlap: Annotated[
            OverlapPolicy, typer.Option("--overlap", help="skip or queue when busy.")
        ] = OverlapPolicy.skip,
        disabled: Annotated[
            bool, typer.Option("--disabled", help="Create the schedule disabled.")
        ] = False,
        workflow: Annotated[
            str | None,
            typer.Option("--workflow", help="Workflow id or name: run it, not one bead."),
        ] = None,
        raw_inputs: Annotated[
            list[str] | None,
            typer.Option("--input", help="Workflow input as name=value (repeatable)."),
        ] = None,
    ) -> None:
        """Create a schedule and print its id."""
        run_create(
            bootstrap.fleet_home(),
            datetime.now(UTC),
            name=name,
            cron_text=cron_text,
            timezone=timezone,
            title=title,
            description=description,
            cwd=cwd,
            coder=coder,
            model=model,
            priority=priority,
            overlap=overlap,
            disabled=disabled,
            workflow=workflow,
            raw_inputs=raw_inputs or [],
        )

    @schedule_app.command("show")
    def show_cmd(
        schedule_id: Annotated[str, typer.Argument(help="Schedule id.")],
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit the schedule as JSON.")
        ] = False,
    ) -> None:
        """Show one schedule: definition, next firings, recent runs."""
        run_show(bootstrap.fleet_home(), datetime.now(UTC), schedule_id, json_output)

    @schedule_app.command("edit")
    def edit_cmd(  # noqa: PLR0913, PLR0917  # edit mirrors create, all optional
        schedule_id: Annotated[str, typer.Argument(help="Schedule id.")],
        name: Annotated[str | None, typer.Option("--name")] = None,
        cron_text: Annotated[str | None, typer.Option("--cron")] = None,
        timezone: Annotated[str | None, typer.Option("--tz")] = None,
        title: Annotated[str | None, typer.Option("--title")] = None,
        description: Annotated[str | None, typer.Option("--description")] = None,
        cwd: Annotated[str | None, typer.Option("--cwd")] = None,
        coder: Annotated[str | None, typer.Option("--coder")] = None,
        model: Annotated[str | None, typer.Option("--model")] = None,
        priority: Annotated[int | None, typer.Option("--priority", "-p")] = None,
        overlap: Annotated[OverlapPolicy | None, typer.Option("--overlap")] = None,
        enabled: Annotated[
            bool | None, typer.Option("--enabled/--disabled", help="Flip the enabled flag.")
        ] = None,
        workflow: Annotated[
            str | None,
            typer.Option("--workflow", help="Point the schedule at a workflow id or name."),
        ] = None,
        raw_inputs: Annotated[
            list[str] | None,
            typer.Option("--input", help="Workflow input as name=value (repeatable)."),
        ] = None,
    ) -> None:
        """Change only the given fields of a schedule."""
        run_edit(
            bootstrap.fleet_home(),
            datetime.now(UTC),
            schedule_id,
            name=name,
            cron_text=cron_text,
            timezone=timezone,
            title=title,
            description=description,
            cwd=cwd,
            coder=coder,
            model=model,
            priority=priority,
            overlap=overlap,
            enabled=enabled,
            workflow=workflow,
            raw_inputs=raw_inputs or [],
        )

    @schedule_app.command("enable")
    def enable_cmd(
        schedule_id: Annotated[str, typer.Argument(help="Schedule id.")],
    ) -> None:
        """Enable a schedule."""
        run_set_enabled(bootstrap.fleet_home(), datetime.now(UTC), schedule_id, True)

    @schedule_app.command("disable")
    def disable_cmd(
        schedule_id: Annotated[str, typer.Argument(help="Schedule id.")],
    ) -> None:
        """Disable a schedule (it keeps its history and fires no more runs)."""
        run_set_enabled(bootstrap.fleet_home(), datetime.now(UTC), schedule_id, False)

    @schedule_app.command("rm")
    def rm_cmd(
        schedule_id: Annotated[str, typer.Argument(help="Schedule id.")],
    ) -> None:
        """Remove a schedule and its run history."""
        run_rm(bootstrap.fleet_home(), schedule_id)

    @schedule_app.command("run")
    def run_cmd(
        schedule_id: Annotated[str, typer.Argument(help="Schedule id.")],
    ) -> None:
        """Fire one manual run now and print the new task or workflow run id."""
        run_fire(bootstrap.fleet_home(), datetime.now(UTC), schedule_id)

    @schedule_app.command("preview")
    def preview_cmd(
        cron_text: Annotated[str, typer.Argument(help="Cron expression to check.")],
        timezone: Annotated[str, typer.Option("--tz", help="IANA time zone name.")] = "UTC",
        count: Annotated[int, typer.Option("--lines", "-n", help="How many firings to print.")] = 5,
    ) -> None:
        """Print the next firings of a cron expression."""
        run_preview(cron_text, timezone, count)
