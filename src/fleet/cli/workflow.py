"""`fleet workflow` — saved workflows and their runs from the terminal.

Thin typer sub-app (ADR 0006 rule 3): each command parses flags, calls a
module-level `run_*` helper that computes through `workflows.*`, and prints
through `cli/render.py`. Time is read here via `datetime.now(UTC)` only;
everything stored is an ISO-8601 UTC string. Called by `cli/main.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from fleet.beads.client import BdError
from fleet.cli import bootstrap, render
from fleet.cli.errors import ExitCode, fail
from fleet.cli.render import WorkflowListRow, WorkflowRunRow, WorkflowStepLine
from fleet.core.errors import WorkflowInvalid, WorkflowNameTaken
from fleet.state.paths import workflows_db_path
from fleet.workflows.model import (
    RunStatus,
    Trigger,
    Workflow,
    WorkflowRun,
    new_id,
    step_state_of,
)
from fleet.workflows.runs import cancel_run, start_run
from fleet.workflows.store import WorkflowStore
from fleet.workflows.yaml_io import from_yaml, to_yaml

_RUNS_DEFAULT_LIMIT = 20


def _store(fleet_home: Path) -> WorkflowStore:
    """Workflow store rooted at *fleet_home*."""
    return WorkflowStore(workflows_db_path(fleet_home))


def _resolve(store: WorkflowStore, ref: str) -> Workflow:
    """One workflow by id (wf- prefix) or name, exiting NOT_FOUND when unknown."""
    found = store.get(ref) if ref.startswith("wf-") else store.get_by_name(ref)
    if found is None and not ref.startswith("wf-"):
        found = store.get(ref)
    if found is None:
        fail(f"Workflow {ref} not found.", ExitCode.NOT_FOUND)
    return found


def _resolve_run(store: WorkflowStore, run_id: str) -> WorkflowRun:
    """One run by id, exiting NOT_FOUND when unknown."""
    run = store.get_run(run_id)
    if run is None:
        fail(f"Run {run_id} not found.", ExitCode.NOT_FOUND)
    return run


def _read_doc(path: Path) -> str:
    """File text, exiting NOT_FOUND when the path is unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}", ExitCode.NOT_FOUND)


def _parse_doc(text: str) -> Workflow:
    """Validated workflow from YAML text, exiting ERROR with each problem."""
    try:
        return from_yaml(text)
    except WorkflowInvalid as exc:
        for problem in exc.problems:
            typer.echo(f"invalid: {problem}", err=True)
        raise typer.Exit(int(ExitCode.ERROR)) from None


def _last_status(store: WorkflowStore, workflow_id: str) -> str | None:
    """Latest run status for list display, or None when never run."""
    last = store.last_run(workflow_id)
    return last.status.value if last is not None else None


def _step_lines_of(run: WorkflowRun, store: WorkflowStore) -> list[WorkflowStepLine]:
    """Outline lines for one run with task id and status per step."""
    by_name = {item.step_name: item for item in store.step_runs(run.id)}
    lines: list[WorkflowStepLine] = []
    for stage_index, stage in enumerate(run.spec.stages):
        for step in stage.steps:
            item = by_name.get(step.name)
            lines.append(
                WorkflowStepLine(
                    stage_index=stage_index,
                    stage_name=stage.name,
                    step_name=step.name,
                    needs=tuple(step.needs),
                    task_id=item.task_id if item is not None else None,
                    task_status=item.task_status if item is not None else None,
                )
            )
    return lines


def _done_total(store: WorkflowStore, run: WorkflowRun) -> tuple[int, int]:
    """(done steps, total steps) for one run's done/total column."""
    steps = store.step_runs(run.id)
    done = sum(1 for item in steps if step_state_of(item.task_status).value == "done")
    return done, len(steps)


def _run_row(store: WorkflowStore, run: WorkflowRun) -> WorkflowRunRow:
    """List row for one run with its workflow name and done/total counts."""
    workflow = store.get(run.workflow_id)
    done, total = _done_total(store, run)
    return WorkflowRunRow(
        run=run,
        workflow_name=workflow.name if workflow is not None else run.spec.name,
        done=done,
        total=total,
    )


def _step_view(run: WorkflowRun, store: WorkflowStore) -> list[dict[str, Any]]:
    """JSON view of one run's steps with task facts and derived states."""
    return [
        {
            "stage_index": line.stage_index,
            "stage_name": line.stage_name,
            "step_name": line.step_name,
            "needs": list(line.needs),
            "task_id": line.task_id,
            "task_status": line.task_status,
            "state": step_state_of(line.task_status or "").value,
        }
        for line in _step_lines_of(run, store)
    ]


def run_list(fleet_home: Path, json_output: bool) -> None:
    """Print every workflow as a table (or JSON with --json)."""
    store = _store(fleet_home)
    rows = [
        WorkflowListRow(
            workflow=item,
            runs=store.run_count(item.id),
            last_status=_last_status(store, item.id),
        )
        for item in store.list()
    ]
    if json_output:
        typer.echo(
            json.dumps(
                [
                    {
                        **row.workflow.to_dict(),
                        "run_count": row.runs,
                        "last_run_status": row.last_status,
                    }
                    for row in rows
                ],
                indent=2,
            )
        )
        return
    render.print_workflow_list(rows)


def run_show(fleet_home: Path, ref: str, yaml_output: bool, json_output: bool) -> None:
    """Print one workflow as a stage outline (--yaml prints the export)."""
    workflow = _resolve(_store(fleet_home), ref)
    if yaml_output:
        typer.echo(to_yaml(workflow), nl=False)
        return
    if json_output:
        typer.echo(json.dumps(workflow.to_dict(), indent=2))
        return
    render.print_workflow_show(workflow)


def run_import(fleet_home: Path, now: datetime, path: Path, replace: str | None) -> None:
    """Validate a YAML file and save it as a new workflow (or replace one)."""
    parsed = _parse_doc(_read_doc(path))
    store = _store(fleet_home)
    stamp = now.isoformat()
    if replace is not None:
        existing = _resolve(store, replace)
        workflow = Workflow(
            id=existing.id,
            name=parsed.name,
            description=parsed.description,
            defaults=parsed.defaults,
            stages=parsed.stages,
            created_at=existing.created_at,
            updated_at=stamp,
        )
    else:
        workflow = Workflow(
            id=new_id(),
            name=parsed.name,
            description=parsed.description,
            defaults=parsed.defaults,
            stages=parsed.stages,
            created_at=stamp,
            updated_at=stamp,
        )
    try:
        store.save(workflow)
    except WorkflowNameTaken as exc:
        fail(f"workflow name already taken: {exc.name}", ExitCode.ERROR)
    typer.echo(workflow.id)


def run_export(fleet_home: Path, ref: str, output: Path | None) -> None:
    """Print one workflow as YAML (or write it to a file with -o)."""
    text = to_yaml(_resolve(_store(fleet_home), ref))
    if output is None:
        typer.echo(text, nl=False)
        return
    try:
        output.write_text(text, encoding="utf-8")
    except OSError as exc:
        fail(f"cannot write {output}: {exc}", ExitCode.ERROR)


def run_validate(path: Path) -> None:
    """Print each problem in a YAML file, or \"valid\" when it passes."""
    parsed = _parse_doc(_read_doc(path))
    _ = parsed
    typer.echo("valid")


def run_start(fleet_home: Path, now: datetime, ref: str) -> None:
    """Start a manual run and print the run id plus one line per step."""
    store = _store(fleet_home)
    workflow = _resolve(store, ref)
    queue = bootstrap.queue(fleet_home)
    try:
        run = start_run(workflow, store=store, queue=queue, now=now, trigger=Trigger.manual)
    except BdError as exc:
        fail(str(exc) or "queue failed", ExitCode.BACKEND)
    typer.echo(run.id)
    by_name = {item.step_name: item for item in store.step_runs(run.id)}
    for stage in run.spec.stages:
        for step in stage.steps:
            item = by_name.get(step.name)
            typer.echo(f"{stage.name}/{step.name} -> {item.task_id if item else '-'}")


def run_runs(
    fleet_home: Path,
    ref: str | None,
    status: str | None,
    limit: int,
    json_output: bool,
) -> None:
    """Print runs newest first, optionally for one workflow and one status."""
    store = _store(fleet_home)
    workflow_id = _resolve(store, ref).id if ref is not None else None
    wanted: RunStatus | None = None
    if status is not None:
        try:
            wanted = RunStatus(status)
        except ValueError:
            fail(f"status: unknown run status {status!r}", ExitCode.USAGE)
    runs = store.list_runs(workflow_id=workflow_id, limit=limit if limit > 0 else 1)
    rows = [_run_row(store, run) for run in runs]
    if wanted is not None:
        rows = [row for row in rows if row.run.status is wanted]
    if json_output:
        typer.echo(
            json.dumps(
                [{**row.run.to_dict(), "workflow_name": row.workflow_name} for row in rows],
                indent=2,
            )
        )
        return
    render.print_workflow_runs(rows)


def run_run_show(fleet_home: Path, run_id: str, json_output: bool) -> None:
    """Print one run as a stage outline with task id and status per step."""
    store = _store(fleet_home)
    run = _resolve_run(store, run_id)
    if json_output:
        typer.echo(json.dumps({**run.to_dict(), "steps": _step_view(run, store)}, indent=2))
        return
    render.print_workflow_run_show(run, _step_lines_of(run, store))


def run_cancel(fleet_home: Path, now: datetime, run_id: str, reason: str) -> None:
    """Cancel a run (close waiting beads, kill running ones)."""
    store = _store(fleet_home)
    run = _resolve_run(store, run_id)
    try:
        finished = cancel_run(
            run, store=store, queue=bootstrap.queue(fleet_home), now=now, reason=reason
        )
    except BdError as exc:
        fail(str(exc) or "queue failed", ExitCode.BACKEND)
    typer.echo(f"Run {finished.id} {finished.status.value}.")


def run_rm(fleet_home: Path, now: datetime, ref: str, force: bool) -> None:
    """Remove a workflow; refuses while a run is active unless --force."""
    store = _store(fleet_home)
    workflow = _resolve(store, ref)
    active = [
        run
        for run in store.list_runs(workflow_id=workflow.id, limit=10_000)
        if run.status in (RunStatus.running, RunStatus.attention)
    ]
    if active and not force:
        fail(
            f"Workflow {workflow.id} has {len(active)} active run(s); cancel them or pass --force.",
            ExitCode.ERROR,
        )
    if active:
        queue = bootstrap.queue(fleet_home)
        for run in active:
            try:
                cancel_run(run, store=store, queue=queue, now=now, reason="workflow removed")
            except BdError as exc:
                fail(str(exc) or "queue failed", ExitCode.BACKEND)
    if not store.delete(workflow.id):
        fail(f"Workflow {workflow.id} not found.", ExitCode.NOT_FOUND)
    typer.echo(f"Removed workflow {workflow.id}.")


def register(app: typer.Typer) -> None:
    """Wire `fleet workflow` as a thin sub-app over the helpers above."""
    workflow_app = typer.Typer(
        no_args_is_help=True,
        help="Manage saved workflows: import, validate, run, and inspect runs.",
        epilog=(
            "Examples:\n\n"
            "  fleet workflow import nightly.yaml\n"
            "  fleet workflow run nightly-quality\n"
            "  fleet workflow runs nightly-quality"
        ),
    )
    app.add_typer(workflow_app, name="workflow")

    @workflow_app.command("list")
    def list_cmd(
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit workflows as JSON.")
        ] = False,
    ) -> None:
        """List every workflow with stage/step/run counts."""
        run_list(bootstrap.fleet_home(), json_output)

    @workflow_app.command("show")
    def show_cmd(
        ref: Annotated[str, typer.Argument(help="Workflow id or name.")],
        yaml_output: Annotated[bool, typer.Option("--yaml", help="Print the YAML export.")] = False,
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit the workflow as JSON.")
        ] = False,
    ) -> None:
        """Show one workflow as a stage outline."""
        run_show(bootstrap.fleet_home(), ref, yaml_output, json_output)

    @workflow_app.command("import")
    def import_cmd(
        file: Annotated[Path, typer.Argument(help="YAML file to import.")],
        replace: Annotated[
            str | None, typer.Option("--replace", help="Replace this workflow id or name.")
        ] = None,
    ) -> None:
        """Validate a YAML file and save it as a workflow, printing its id."""
        run_import(bootstrap.fleet_home(), datetime.now(UTC), file, replace)

    @workflow_app.command("export")
    def export_cmd(
        ref: Annotated[str, typer.Argument(help="Workflow id or name.")],
        output: Annotated[
            Path | None, typer.Option("-o", help="Write to this file, not stdout.")
        ] = None,
    ) -> None:
        """Print one workflow as YAML (the import file shape)."""
        run_export(bootstrap.fleet_home(), ref, output)

    @workflow_app.command("validate")
    def validate_cmd(
        file: Annotated[Path, typer.Argument(help="YAML file to check.")],
    ) -> None:
        """Print each problem in a YAML file, or \"valid\" when it passes."""
        run_validate(file)

    @workflow_app.command("run")
    def run_cmd(
        ref: Annotated[str, typer.Argument(help="Workflow id or name.")],
    ) -> None:
        """Start a manual run and print the run id plus one line per step."""
        run_start(bootstrap.fleet_home(), datetime.now(UTC), ref)

    @workflow_app.command("runs")
    def runs_cmd(
        ref: Annotated[
            str | None, typer.Argument(help="Workflow id or name (all when omitted).")
        ] = None,
        status: Annotated[
            str | None, typer.Option("--status", help="Only runs with this status.")
        ] = None,
        limit: Annotated[
            int, typer.Option("--lines", "-n", help="Maximum runs to list.")
        ] = _RUNS_DEFAULT_LIMIT,
        json_output: Annotated[bool, typer.Option("--json", help="Emit runs as JSON.")] = False,
    ) -> None:
        """List runs newest first, optionally for one workflow."""
        run_runs(bootstrap.fleet_home(), ref, status, limit, json_output)

    @workflow_app.command("run-show")
    def run_show_cmd(
        run_id: Annotated[str, typer.Argument(help="Run id.")],
        json_output: Annotated[bool, typer.Option("--json", help="Emit the run as JSON.")] = False,
    ) -> None:
        """Show one run as a stage outline with task id and status per step."""
        run_run_show(bootstrap.fleet_home(), run_id, json_output)

    @workflow_app.command("cancel")
    def cancel_cmd(
        run_id: Annotated[str, typer.Argument(help="Run id.")],
        reason: Annotated[str, typer.Option("--reason", help="Why it was cancelled.")] = (
            "cancelled by operator"
        ),
    ) -> None:
        """Cancel a run (close waiting beads, kill running ones)."""
        run_cancel(bootstrap.fleet_home(), datetime.now(UTC), run_id, reason)

    @workflow_app.command("rm")
    def rm_cmd(
        ref: Annotated[str, typer.Argument(help="Workflow id or name.")],
        force: Annotated[bool, typer.Option("--force", help="Cancel active runs first.")] = False,
    ) -> None:
        """Remove a workflow; refuses while a run is active unless --force."""
        run_rm(bootstrap.fleet_home(), datetime.now(UTC), ref, force)
