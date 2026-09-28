"""`fleet flow` — Fleet 2 flows and their runs from the terminal.

Thin typer sub-app (ADR 0006 rule 3): each command parses flags, calls a
module-level `run_*` helper that computes through `flows.*` and `runs.*`,
and prints tables with rich (same style as `cli/render.py`) or JSON.
Definitions come from the folder catalog (`flows.folders.load_catalog`
over `bootstrap.config`); runs live in `runs.db` via `RunStore`. Time is
read here via `datetime.now(UTC)` only; everything stored is an ISO-8601
UTC string. Called by `cli/main.py`.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
import yaml
from rich.console import Console
from rich.table import Table

from fleet.cli import bootstrap
from fleet.cli.errors import ExitCode, fail
from fleet.core.errors import FlowInvalid, FlowNotFound
from fleet.flows import folders
from fleet.flows.folders import Catalog
from fleet.flows.model import Flow, flow_from_dict, flow_to_dict
from fleet.flows.tools import tool_from_dict
from fleet.runs import engine
from fleet.runs import run_dir as run_dir_mod
from fleet.runs.run_dir import NO_ITEM, read_outputs, step_dir
from fleet.runs.store import (
    FINISHED,
    Run,
    RunStatus,
    RunStore,
    StepRun,
    StepStatus,
    runs_db_path,
)

_RUNS_DEFAULT_LIMIT = 20


def _store(fleet_home: Path) -> RunStore:
    """Run store rooted at *fleet_home*."""
    return RunStore(runs_db_path(fleet_home))


def _catalog(fleet_home: Path) -> Catalog:
    """Folder catalog from the runtime config's `flows_folders`."""
    return folders.load_catalog(bootstrap.config(fleet_home))


def _warn_problems(catalog: Catalog) -> None:
    """Catalog problems as stderr warnings; they never crash the command."""
    for problem in catalog.problems:
        typer.echo(f"warning: {problem}", err=True)


def _resolve(catalog: Catalog, name: str) -> Flow:
    """One flow by name, exiting NOT_FOUND when unknown."""
    try:
        return catalog.flow(name)
    except FlowNotFound:
        fail(f"Flow {name} not found.", ExitCode.NOT_FOUND)


def _resolve_run(store: RunStore, run_id: str) -> Run:
    """One run by id, exiting NOT_FOUND when unknown."""
    run = store.get_run(run_id)
    if run is None:
        fail(f"Run {run_id} not found.", ExitCode.NOT_FOUND)
    return run


def _starts_of(flow: Flow) -> str:
    """Comma-joined start kinds (`cron`, `tool`, `manual`) of one flow."""
    kinds = []
    if flow.on.cron is not None:
        kinds.append("cron")
    if flow.on.tool is not None:
        kinds.append("tool")
    if flow.on.manual:
        kinds.append("manual")
    return ",".join(kinds) if kinds else "-"


def _parse_input_pair(raw: str) -> tuple[str, str]:
    """Split one --input name=value pair, exiting USAGE when malformed."""
    name, sep, value = raw.partition("=")
    if not sep or not name:
        fail(f"invalid argument {raw!r} — expected name=value format.", ExitCode.USAGE)
    return name, value


def _report_invalid(exc: FlowInvalid) -> NoReturn:
    """Print every validation problem and exit ERROR."""
    for problem in exc.problems:
        typer.echo(f"invalid: {problem}", err=True)
    raise typer.Exit(int(ExitCode.ERROR))


def _run_json(run: Run) -> dict[str, Any]:
    """JSON-safe mapping of one run row (enums as values)."""
    data = asdict(run)
    data["status"] = run.status.value
    return data


def _step_json(item: StepRun) -> dict[str, Any]:
    """JSON-safe mapping of one step run row (enums as values)."""
    data = asdict(item)
    data["status"] = item.status.value
    data["after"] = list(item.after)
    return data


def run_list(fleet_home: Path, json_output: bool) -> None:
    """Print every catalog flow as a table (or JSON with --json)."""
    catalog = _catalog(fleet_home)
    _warn_problems(catalog)
    flows = [catalog.flows[name] for name in sorted(catalog.flows)]
    if json_output:
        typer.echo(
            json.dumps(
                [
                    {
                        "name": flow.name,
                        "starts": _starts_of(flow),
                        "enabled": flow.enabled,
                        "source": flow.source,
                    }
                    for flow in flows
                ],
                indent=2,
            )
        )
        return
    if not flows:
        typer.echo("No flows.")
        return
    table = Table(
        title="Fleet — flows",
        title_style="bold",
        header_style="bold cyan",
        border_style="cyan",
        show_lines=False,
        pad_edge=False,
    )
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Starts", no_wrap=True)
    table.add_column("Enabled", no_wrap=True)
    table.add_column("Source", overflow="fold")
    for flow in flows:
        table.add_row(
            flow.name,
            _starts_of(flow),
            "yes" if flow.enabled else "no",
            flow.source,
        )
    Console(soft_wrap=False).print(table)


def run_show(fleet_home: Path, name: str, json_output: bool) -> None:
    """Print one parsed flow: inputs, defaults, steps (or JSON with --json)."""
    catalog = _catalog(fleet_home)
    _warn_problems(catalog)
    flow = _resolve(catalog, name)
    if json_output:
        typer.echo(json.dumps(flow_to_dict(flow), indent=2))
        return
    typer.echo(f"flow: {flow.name}")
    if flow.description:
        typer.echo(f"description: {flow.description}")
    typer.echo(f"enabled:  {'yes' if flow.enabled else 'no'}")
    typer.echo(f"starts:   {_starts_of(flow)}")
    typer.echo(f"source:   {flow.source}")
    if flow.inputs:
        typer.echo("inputs:")
        for item in flow.inputs:
            line = f"  - {item.name}"
            if item.required:
                line += " (required)"
            elif item.default is not None:
                line += f" (default: {item.default})"
            if item.description:
                line += f" — {item.description}"
            typer.echo(line)
    else:
        typer.echo("inputs: (none)")
    if flow.defaults:
        typer.echo("defaults:")
        for key in sorted(flow.defaults):
            typer.echo(f"  {key}: {flow.defaults[key]}")
    typer.echo(f"steps: {len(flow.steps)}")
    for step in flow.steps:
        line = f"  - {step.name} (kind: {step.kind}"
        if step.needs:
            line += f", needs: {', '.join(step.needs)}"
        if step.for_each is not None:
            line += f", for_each: {step.for_each}"
        if step.checks:
            line += f", checks: {', '.join(check.name for check in step.checks)}"
        typer.echo(line + ")")


def run_validate(path: Path) -> None:
    """Parse one flow or tool file; print "ok" or the problems (exit 1)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}", ExitCode.NOT_FOUND)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        typer.echo(f"invalid: {exc}", err=True)
        raise typer.Exit(int(ExitCode.ERROR)) from None
    if not isinstance(data, dict):
        typer.echo("invalid: top level must be a mapping", err=True)
        raise typer.Exit(int(ExitCode.ERROR))
    try:
        if "fleet_flow" in data:
            flow_from_dict(data, path.stem, str(path))
        elif "fleet_tool" in data:
            tool_from_dict(data, path.stem, str(path))
        else:
            raise FlowInvalid("file has neither fleet_flow nor fleet_tool marker")
    except FlowInvalid as exc:
        _report_invalid(exc)
    typer.echo("ok")


def run_run(fleet_home: Path, now: datetime, name: str, raw_inputs: list[str]) -> None:
    """Start a manual run and print the run id."""
    flow = _resolve(_catalog(fleet_home), name)
    if not flow.on.manual:
        _report_invalid(FlowInvalid(f"flow {flow.name}: manual start is disabled"))
    given = dict(_parse_input_pair(raw) for raw in raw_inputs)
    store = _store(fleet_home)
    try:
        run = engine.start_run(store, fleet_home, flow, given, now)
    except FlowInvalid as exc:
        _report_invalid(exc)
    typer.echo(run.id)


def run_runs(
    fleet_home: Path,
    flow_name: str | None,
    status: str | None,
    limit: int,
    json_output: bool,
) -> None:
    """Print runs newest first, optionally for one flow and one status."""
    wanted: RunStatus | None = None
    if status is not None:
        try:
            wanted = RunStatus(status)
        except ValueError:
            fail(f"status: unknown run status {status!r}", ExitCode.USAGE)
    if flow_name is not None:
        _resolve(_catalog(fleet_home), flow_name)
    store = _store(fleet_home)
    runs = store.list_runs(flow=flow_name, status=wanted, limit=limit if limit > 0 else 1)
    if json_output:
        typer.echo(json.dumps([_run_json(run) for run in runs], indent=2))
        return
    if not runs:
        typer.echo("No runs.")
        return
    table = Table(
        title="Fleet — flow runs",
        title_style="bold",
        header_style="bold cyan",
        border_style="cyan",
        show_lines=False,
        pad_edge=False,
    )
    table.add_column("ID", style="bold cyan", no_wrap=True)
    table.add_column("Flow", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Started", no_wrap=True)
    table.add_column("Finished", no_wrap=True)
    table.add_column("Reason", overflow="fold")
    for run in runs:
        table.add_row(
            run.id,
            run.flow,
            run.status.value,
            run.started_at,
            run.finished_at or "-",
            run.reason or "-",
        )
    Console(soft_wrap=False).print(table)


def run_status(fleet_home: Path, run_id: str, json_output: bool, show_outputs: bool) -> None:
    """Print one run plus one line per step run (--outputs adds outputs.json)."""
    store = _store(fleet_home)
    run = _resolve_run(store, run_id)
    rows = store.step_runs(run.id)
    directory = run_dir_mod.run_dir(fleet_home, run.id)
    outputs: dict[str, dict[str, Any]] = {}
    if show_outputs:
        for row in rows:
            if row.status in FINISHED:
                step_path = step_dir(directory, row.step, row.item_index)
                outputs[_output_key(row)] = read_outputs(step_path)
    if json_output:
        payload: dict[str, Any] = {**_run_json(run), "steps": [_step_json(row) for row in rows]}
        if show_outputs:
            payload["outputs"] = outputs
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(f"run: {run.id} flow {run.flow} {run.status.value}")
    typer.echo(f"started:  {run.started_at}")
    typer.echo(f"finished: {run.finished_at or '-'}")
    if run.reason:
        typer.echo(f"reason:   {run.reason}")
    if run.inputs:
        typer.echo("inputs:")
        for key in sorted(run.inputs):
            typer.echo(f"  {key}={run.inputs[key]}")
    else:
        typer.echo("inputs: (none)")
    if not rows:
        typer.echo("steps: (none)")
        return
    typer.echo(f"steps: {len(rows)}")
    for row in rows:
        line = f"  - {row.step} item={row.item_index} {row.status.value} attempt={row.attempt}"
        if row.reason:
            line += f" reason: {row.reason}"
        typer.echo(line)
        if show_outputs and _output_key(row) in outputs:
            typer.echo(f"    outputs: {json.dumps(outputs[_output_key(row)], sort_keys=True)}")


def _output_key(row: StepRun) -> str:
    """Stable key for one step run's outputs (`step` or `step[item]`)."""
    if row.item_index == NO_ITEM:
        return row.step
    return f"{row.step}[{row.item_index}]"


def run_cancel(fleet_home: Path, now: datetime, run_id: str, reason: str) -> None:
    """Cancel a run (every non-finished step run goes to cancelled)."""
    store = _store(fleet_home)
    run = _resolve_run(store, run_id)
    engine.cancel_run(store, run, now, reason)
    typer.echo(f"Run {run.id} cancelled.")


def run_retry(fleet_home: Path, now: datetime, run_id: str, step: str, item: int) -> None:
    """Send one failed or skipped step run back to ready (exit 1 otherwise)."""
    store = _store(fleet_home)
    _resolve_run(store, run_id)
    row = store.get_step_run(run_id, step, item)
    if row is None:
        fail(f"Step {step} item {item} not found in run {run_id}.", ExitCode.NOT_FOUND)
    if row.status not in (StepStatus.failed, StepStatus.skipped):
        fail(
            f"Step {step} item {item} is {row.status.value}, not failed or skipped.",
            ExitCode.ERROR,
        )
    engine.retry_step_run(store, row, now, "retried by operator")
    typer.echo(f"Run {run_id} step {step} item {item} queued for retry.")


def register(app: typer.Typer) -> None:
    """Wire `fleet flow` as a thin sub-app over the helpers above."""
    flow_app = typer.Typer(
        no_args_is_help=True,
        help="Manage Fleet 2 flows: list, validate, run, and inspect runs.",
        epilog=(
            "Examples:\n\n"
            "  fleet flow list\n"
            "  fleet flow run demo --input repo=/tmp/x\n"
            "  fleet flow status run-20260928-abc123"
        ),
    )
    app.add_typer(flow_app, name="flow")

    @flow_app.command("list")
    def list_cmd(
        json_output: Annotated[bool, typer.Option("--json", help="Emit flows as JSON.")] = False,
    ) -> None:
        """List every catalog flow with its starts, enabled flag, and source."""
        run_list(bootstrap.fleet_home(), json_output)

    @flow_app.command("show")
    def show_cmd(
        name: Annotated[str, typer.Argument(help="Flow name.")],
        json_output: Annotated[bool, typer.Option("--json", help="Emit the flow as JSON.")] = False,
    ) -> None:
        """Show one parsed flow: inputs, defaults, and steps."""
        run_show(bootstrap.fleet_home(), name, json_output)

    @flow_app.command("validate")
    def validate_cmd(
        file: Annotated[Path, typer.Argument(help="Flow or tool YAML file to check.")],
    ) -> None:
        """Parse one file and print "ok" or the problems (exit 1)."""
        run_validate(file)

    @flow_app.command("run")
    def run_cmd(
        name: Annotated[str, typer.Argument(help="Flow name.")],
        raw_inputs: Annotated[
            list[str] | None,
            typer.Option("--input", help="Run input as name=value (repeatable)."),
        ] = None,
    ) -> None:
        """Start a manual run and print the run id."""
        run_run(bootstrap.fleet_home(), datetime.now(UTC), name, raw_inputs or [])

    @flow_app.command("runs")
    def runs_cmd(
        flow_name: Annotated[
            str | None, typer.Option("--flow", help="Only runs of this flow.")
        ] = None,
        status: Annotated[
            str | None, typer.Option("--status", help="Only runs with this status.")
        ] = None,
        limit: Annotated[int, typer.Option("--limit", help="Maximum runs to list.")] = (
            _RUNS_DEFAULT_LIMIT
        ),
        json_output: Annotated[bool, typer.Option("--json", help="Emit runs as JSON.")] = False,
    ) -> None:
        """List runs newest first, optionally for one flow and one status."""
        run_runs(bootstrap.fleet_home(), flow_name, status, limit, json_output)

    @flow_app.command("status")
    def status_cmd(
        run_id: Annotated[str, typer.Argument(help="Run id.")],
        json_output: Annotated[bool, typer.Option("--json", help="Emit the run as JSON.")] = False,
        show_outputs: Annotated[
            bool, typer.Option("--outputs", help="Also print finished steps' outputs.json.")
        ] = False,
    ) -> None:
        """Show one run plus one line per step run."""
        run_status(bootstrap.fleet_home(), run_id, json_output, show_outputs)

    @flow_app.command("cancel")
    def cancel_cmd(
        run_id: Annotated[str, typer.Argument(help="Run id.")],
        reason: Annotated[str, typer.Option("--reason", help="Why it was cancelled.")] = (
            "cancelled by operator"
        ),
    ) -> None:
        """Cancel a run (every non-finished step run goes to cancelled)."""
        run_cancel(bootstrap.fleet_home(), datetime.now(UTC), run_id, reason)

    @flow_app.command("retry")
    def retry_cmd(
        run_id: Annotated[str, typer.Argument(help="Run id.")],
        step: Annotated[str, typer.Argument(help="Step name.")],
        item: Annotated[int, typer.Option("--item", help="For_each item index.")] = NO_ITEM,
    ) -> None:
        """Send one failed or skipped step run back to ready."""
        run_retry(bootstrap.fleet_home(), datetime.now(UTC), run_id, step, item)
