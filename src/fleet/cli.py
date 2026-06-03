"""fleet CLI — typer-based surface for the fleet supervisor (FR-32)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import fields as dc_fields
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text
from typer.core import TyperCommand

from fleet.coders import get_coder
from fleet.config import load as load_config
from fleet.config import write_atomic
from fleet.logging import setup_supervisor_logger
from fleet.queue import BeadsError, BeadsQueue
from fleet.schemas import LOG_ROOT, Task
from fleet.serve.stats import (
    TaskRuntimeStats as _TaskRuntimeStats,
    fleet_home as _fleet_home_impl,
    task_dir as _task_dir_impl,
    task_runtime_stats,
)
from fleet.supervisor import Supervisor

app = typer.Typer(
    no_args_is_help=True,
    help=(
        "fleet — parallel coding-agent supervisor.\n\n"
        "Pulls tasks from a centralized beads queue and runs them in parallel "
        "through a coder CLI (claude, agy, or codex) in a headless loop. "
        "Each task carries its own project directory and optional coder/model "
        "override, so a single supervisor can drive work across many projects "
        "and agent backends from one machine.\n\n"
        "Typical flow:  fleet init  →  fleet bd create  →  fleet run"
    ),
)
config_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config", help="Manage runtime configuration.")


def _fleet_home() -> Path:
    """Return the centralized fleet home directory (delegates to serve.stats.fleet_home)."""
    return _fleet_home_impl()


def _runtime_toml_path() -> Path:
    return _fleet_home() / "runtime.toml"


def _queue() -> BeadsQueue:
    return BeadsQueue(_fleet_home())


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    force: Annotated[bool, typer.Option("--force", help="Re-init even if .beads already exists.")] = False,
) -> None:
    """Initialize the fleet home directory (beads + defaults)."""
    home = _fleet_home()
    home.mkdir(parents=True, exist_ok=True)

    beads_dir = home / ".beads"
    if force or not beads_dir.exists():
        result = subprocess.run(
            ["bd", "init"],
            cwd=home,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 and "already" not in result.stderr.lower():
            typer.echo(f"bd init failed: {result.stderr.strip()}", err=True)
            raise typer.Exit(1)

    load_config(_runtime_toml_path())  # writes defaults if missing
    (home / "tasks").mkdir(exist_ok=True)
    typer.echo(f"Fleet home initialized at {home}")


# ---------------------------------------------------------------------------
# Task management commands
# ---------------------------------------------------------------------------


@app.command()
def ready(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum tasks to list.")] = 50,
) -> None:
    """List ready tasks."""
    q = _queue()
    try:
        tasks = q.list_ready(limit=limit)
    except BeadsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    if not tasks:
        typer.echo("No ready tasks.")
        return
    width = max(len(t.id) for t in tasks) + 2
    for t in tasks:
        cwd_suffix = f"  [{t.cwd}]" if t.cwd else ""
        typer.echo(f"{t.id:<{width}}{t.title}{cwd_suffix}")


@app.command()
def show(
    task_id: Annotated[str, typer.Argument(help="Task ID.")],
    json_output: Annotated[bool, typer.Option("--json", help="Emit raw bd show JSON envelope.")] = False,
) -> None:
    """Show one task."""
    root = _fleet_home()
    if json_output:
        result = subprocess.run(
            ["bd", "show", task_id, "--json"],
            capture_output=True,
            text=True,
            cwd=root,
        )
        if result.returncode != 0:
            typer.echo(result.stderr.strip(), err=True)
            raise typer.Exit(result.returncode)
        typer.echo(result.stdout, nl=False)
        return
    q = BeadsQueue(root)
    try:
        task = q.get(task_id)
    except BeadsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    cfg = load_config(_runtime_toml_path())
    effective_coder = task.coder or cfg.coder
    effective_model = task.model or cfg.model
    typer.echo(f"id:     {task.id}")
    typer.echo(f"title:  {task.title}")
    typer.echo(f"status: {task.status}")
    if task.cwd:
        typer.echo(f"cwd:    {task.cwd}")
    coder_suffix = " (default)" if task.coder is None else ""
    model_suffix = " (default)" if task.model is None else ""
    typer.echo(f"coder:  {effective_coder}{coder_suffix}")
    typer.echo(f"model:  {effective_model}{model_suffix}")
    if task.description:
        typer.echo(f"desc:   {task.description}")


# ---------------------------------------------------------------------------
# bd passthrough
# ---------------------------------------------------------------------------


def _first_positional(args: list[str]) -> str | None:
    """Return the first non-flag positional in a bd argv tail, or None.

    bd subcommands (`create`, `ready`, `show`, …) are never dashed, so any
    leading dashed token is a flag and we skip past it. We don't try to model
    "flag with value" pairs — for finding the subcommand, treating every
    dashed token as a flag is sufficient.
    """
    for a in args:
        if a.startswith("-"):
            continue
        return a
    return None


def _extract_flag(args: list[str], flag: str) -> tuple[list[str], str | None]:
    """Strip `--flag <value>` and `--flag=value` from args.

    Returns (new_args, value). If the flag appears multiple times the last
    occurrence wins. A bare `--flag` with no value is dropped silently.
    """
    out: list[str] = []
    value: str | None = None
    eq_prefix = flag + "="
    i = 0
    while i < len(args):
        token = args[i]
        if token == flag:
            if i + 1 < len(args):
                value = args[i + 1]
                i += 2
            else:
                i += 1
            continue
        if token.startswith(eq_prefix):
            value = token[len(eq_prefix):]
            i += 1
            continue
        out.append(token)
        i += 1
    return out, value


@app.command(
    "bd",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "help_option_names": [],
    },
    help=(
        "Run a `bd` command against the centralized fleet database in $FLEET_HOME. "
        "For `bd create`/`bd new`, `--coder` and `--model` are intercepted and "
        "stored as per-task overrides instead of being forwarded to bd."
    ),
)
def bd_passthrough(ctx: typer.Context) -> None:
    """Forward all trailing args verbatim to `bd`, with cwd=$FLEET_HOME.

    For `bd create` / `bd new`, also captures the user's invocation directory
    (the shell cwd from which `fleet bd create` was run) and persists it into
    the task's `task.json` so downstream agents see where the human filed it.
    `--coder` / `--model` flags are intercepted (not forwarded to bd) and
    persisted as per-task overrides on task.json.
    """
    home = _fleet_home()
    bd_args = list(ctx.args)

    sub = _first_positional(bd_args)
    is_create = sub in ("create", "new")

    if not is_create:
        result = subprocess.run(["bd", *bd_args], cwd=home)
        raise typer.Exit(result.returncode)

    bd_args, coder_override = _extract_flag(bd_args, "--coder")
    bd_args, model_override = _extract_flag(bd_args, "--model")
    if coder_override is not None:
        try:
            get_coder(coder_override)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1)

    user_wants_json = "--json" in bd_args
    user_wants_dry_run = "--dry-run" in bd_args

    # typer/click do not chdir, so os.getcwd() here is the shell cwd from
    # which the user invoked us — capture before any subprocess work.
    invocation_cwd = os.getcwd()

    if not user_wants_json:
        bd_args.append("--json")

    result = subprocess.run(
        ["bd", *bd_args],
        cwd=home,
        capture_output=True,
        text=True,
    )
    if result.stderr:
        typer.echo(result.stderr, err=True, nl=False)

    if result.returncode != 0:
        if result.stdout:
            typer.echo(result.stdout, nl=False)
        raise typer.Exit(result.returncode)

    task_id: str | None = None
    task_title: str | None = None
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else None
    except (json.JSONDecodeError, ValueError):
        data = None
    if isinstance(data, dict):
        body = data.get("data", data)
        if isinstance(body, list):
            body = body[0] if body else {}
        if isinstance(body, dict):
            task_id = body.get("id")
            task_title = body.get("title")

    if task_id and not user_wants_dry_run:
        queue = BeadsQueue(home)
        queue.set_cwd(task_id, invocation_cwd)
        queue.set_overrides(task_id, coder=coder_override, model=model_override)

    if user_wants_json:
        typer.echo(result.stdout, nl=False)
    elif task_id:
        extras = [f"cwd: {invocation_cwd}"]
        if coder_override:
            extras.append(f"coder: {coder_override}")
        if model_override:
            extras.append(f"model: {model_override}")
        typer.echo(f"Created {task_id}: {task_title or ''}  [{', '.join(extras)}]")
    else:
        typer.echo(result.stdout, nl=False)

    raise typer.Exit(result.returncode)


# ---------------------------------------------------------------------------
# Supervisor command
# ---------------------------------------------------------------------------


@app.command()
def run() -> None:
    """Start the fleet supervisor."""
    home = _fleet_home()
    runtime_toml = _runtime_toml_path()
    cfg = load_config(runtime_toml)

    # Validate the configured default coder up-front so a typo fails fast.
    try:
        get_coder(cfg.coder)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    q = BeadsQueue(home)
    log_root = Path(LOG_ROOT)
    if not log_root.is_absolute():
        log_root = home / log_root
    log = setup_supervisor_logger(log_root)
    supervisor = Supervisor(
        queue=q,
        runtime_toml_path=runtime_toml,
        project_root=home,
        log=log,
    )
    try:
        rc = asyncio.run(supervisor.run())
    except NotImplementedError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    raise typer.Exit(rc)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@app.command()
def serve(
    port: Annotated[int, typer.Option("--port", help="Port to listen on.")] = 7890,
) -> None:
    """Start the fleet UI server on 127.0.0.1 (FR-48, FR-49)."""
    import uvicorn

    uvicorn.run(
        "fleet.serve.app:create_app",
        host="127.0.0.1",
        port=port,
        factory=True,
    )


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------


def _resolve_log_dir() -> Path:
    log_root = Path(LOG_ROOT)
    if not log_root.is_absolute():
        log_root = _fleet_home() / log_root
    return log_root


@app.command("log")
def log_cmd(
    lines: Annotated[
        int | None,
        typer.Argument(
            help="If given, print only the last N lines (tail).",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Print the supervisor log from FLEET_HOME/logging.

    With no argument, prints the most recently modified `fleet-*.jsonl` file
    in full. With a positive integer N, prints only the last N lines.
    """
    log_dir = _resolve_log_dir()
    if not log_dir.exists():
        typer.echo(f"No log directory at {log_dir}", err=True)
        raise typer.Exit(1)

    candidates = sorted(
        log_dir.glob("fleet-*.jsonl"),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        typer.echo(f"No log files in {log_dir}", err=True)
        raise typer.Exit(1)

    latest = candidates[-1]
    if lines is None:
        sys.stdout.write(latest.read_text(encoding="utf-8"))
        return

    if lines <= 0:
        typer.echo("Error: lines must be a positive integer.", err=True)
        raise typer.Exit(1)

    with latest.open("r", encoding="utf-8") as fh:
        tail = fh.readlines()[-lines:]
    sys.stdout.write("".join(tail))


# ---------------------------------------------------------------------------
# tasks / task
# ---------------------------------------------------------------------------


class TaskAction(str, Enum):
    log = "log"
    plan = "plan"
    knowledge = "knowledge"


def _task_dir(task_id: str) -> Path:
    return _task_dir_impl(task_id)


def _print_file_or_exit(path: Path, missing_msg: str) -> None:
    if not path.exists():
        typer.echo(missing_msg, err=True)
        raise typer.Exit(1)
    sys.stdout.write(path.read_text(encoding="utf-8"))


def _task_runtime_stats(task_id: str) -> _TaskRuntimeStats:
    return task_runtime_stats(task_id)


def _format_started(ts: datetime | None, now: datetime) -> str:
    if ts is None:
        return "-"
    local = ts.astimezone()
    if local.date() == now.astimezone().date():
        return local.strftime("%H:%M:%S")
    return local.strftime("%b %d %H:%M")


def _format_elapsed(ts: datetime | None, now: datetime) -> str:
    if ts is None:
        return "-"
    total = max(0, int((now - ts).total_seconds()))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        m, s = divmod(total, 60)
        return f"{m}m{s:02d}s"
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h{m:02d}m"


def _format_idle(last_event_at: datetime | None, now: datetime) -> str:
    if last_event_at is None:
        return "-"
    total = max(0, int((now - last_event_at).total_seconds()))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    return f"{total // 3600}h"


def _format_events(count: int) -> str:
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1000:.1f}k"
    return f"{count / 1_000_000:.1f}M"


def _format_tokens(count: int) -> str:
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1000:.1f}k"
    return f"{count / 1_000_000:.2f}M"


def _format_context(tokens: int | None, context_limit: int = 200_000) -> Text:
    if tokens is None or tokens <= 0:
        return Text("-", style="dim")
    pct = tokens / context_limit * 100
    label = f"{_format_tokens(tokens)} ({pct:.0f}%)"
    if pct >= 80:
        return Text(label, style="bold red")
    if pct >= 50:
        return Text(label, style="yellow")
    return Text(label, style="green")


def _format_override(task_value: str | None, default: str) -> Text:
    """Render a per-task override: bold when explicitly set, dim default-name otherwise."""
    if task_value:
        return Text(task_value, style="bold")
    return Text(default, style="dim")


def _render_tasks_table(tasks: list[Task], now: datetime) -> Table:
    cfg = load_config(_runtime_toml_path())
    default_coder = cfg.coder
    default_model = cfg.model
    table = Table(
        title="Fleet — running tasks",
        title_style="bold",
        header_style="bold cyan",
        border_style="cyan",
        show_lines=False,
        pad_edge=False,
    )
    table.add_column("ID", style="bold cyan", no_wrap=True)
    table.add_column("Started", no_wrap=True)
    table.add_column("Elapsed", justify="right", no_wrap=True)
    table.add_column("Idle", justify="right", no_wrap=True)
    table.add_column("Context", justify="right", no_wrap=True)
    table.add_column("Events", justify="right", no_wrap=True)
    table.add_column("Coder", no_wrap=True)
    table.add_column("Model", no_wrap=True)
    table.add_column("Title", overflow="fold")
    table.add_column("cwd", style="dim", overflow="fold")

    for t in tasks:
        stats = _task_runtime_stats(t.id)
        try:
            context_limit = get_coder(t.coder or default_coder).context_limit
        except ValueError:
            context_limit = 200_000
        table.add_row(
            t.id,
            _format_started(stats.started_at, now),
            _format_elapsed(stats.started_at, now),
            _format_idle(stats.last_event_at, now),
            _format_context(stats.context_tokens, context_limit),
            _format_events(stats.events),
            _format_override(t.coder, default_coder),
            _format_override(t.model, default_model),
            t.title,
            t.cwd or "",
        )
    return table


@app.command("tasks")
def tasks_cmd(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum tasks to list.")] = 50,
) -> None:
    """List currently running tasks with start time, elapsed, idle, context usage, events."""
    q = _queue()
    try:
        tasks = q.list_in_progress(limit=limit)
    except BeadsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    if not tasks:
        typer.echo("No running tasks.")
        return

    now = datetime.now(tz=timezone.utc)
    table = _render_tasks_table(tasks, now)
    Console(soft_wrap=False).print(table)


def _running_tasks_help_text() -> str:
    """Build the dynamic `--help` epilog for `fleet task`.

    Lists currently running tasks so users running `fleet task --help` can
    immediately see which task IDs are valid arguments, plus the effective
    coder/model for each (per-task override or current config default).
    """
    header = "Currently running tasks (run `fleet tasks` for full details):"
    try:
        tasks = _queue().list_in_progress(limit=50)
    except BeadsError:
        return f"{header}\n\n  (unable to query bd queue)"
    if not tasks:
        return f"{header}\n\n  (none)"
    try:
        cfg = load_config(_runtime_toml_path())
        default_coder = cfg.coder
        default_model = cfg.model
    except OSError:
        default_coder = "claude"
        default_model = "sonnet"
    width = max(len(t.id) for t in tasks) + 2
    rows = []
    for t in tasks:
        coder = t.coder or default_coder
        model = t.model or default_model
        rows.append(
            f"  {t.id:<{width}}[{coder}/{model}]  {t.title}"
        )
    # Double newlines preserve line breaks through typer's rich epilog renderer,
    # which collapses single newlines within a paragraph to spaces.
    return header + "\n\n" + "\n\n".join(rows)


class _TaskHelpCommand(TyperCommand):
    """`fleet task` command whose --help appends a list of running tasks."""

    def format_help(self, ctx, formatter):  # type: ignore[override]
        self.epilog = _running_tasks_help_text()
        return super().format_help(ctx, formatter)


@app.command("task", cls=_TaskHelpCommand)
def task_cmd(
    task_id: Annotated[str, typer.Argument(help="Task ID.")],
    action: Annotated[
        TaskAction,
        typer.Argument(help="What to print: log | plan | knowledge."),
    ],
) -> None:
    """Print a task's log, PLAN_AND_STATUS, or KNOWLEDGE artifact."""
    task_dir = _task_dir(task_id)
    if not task_dir.exists():
        typer.echo(f"No task directory at {task_dir}", err=True)
        raise typer.Exit(1)

    if action is TaskAction.plan:
        _print_file_or_exit(
            task_dir / "artifacts" / "PLAN_AND_STATUS.md",
            f"No PLAN_AND_STATUS.md for task {task_id}",
        )
        return

    if action is TaskAction.knowledge:
        _print_file_or_exit(
            task_dir / "artifacts" / "KNOWLEDGE.md",
            f"No KNOWLEDGE.md for task {task_id}",
        )
        return

    # action == TaskAction.log
    log_path = task_dir / "log.jsonl"
    if not log_path.exists():
        typer.echo(f"No log for task {task_id}", err=True)
        raise typer.Exit(1)
    sys.stdout.write(log_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Config sub-commands
# ---------------------------------------------------------------------------


@config_app.command("show")
def config_show(
    raw: Annotated[bool, typer.Option("--raw", help="Print raw TOML bytes.")] = False,
) -> None:
    """Show the current runtime configuration."""
    path = _runtime_toml_path()
    if raw:
        if path.exists():
            typer.echo(path.read_text(encoding="utf-8"), nl=False)
        else:
            typer.echo("# No config file found (using defaults)")
        return
    cfg = load_config(path)
    typer.echo(f"{'key':<38} value")
    typer.echo("-" * 55)
    for f in dc_fields(cfg):
        typer.echo(f"{f.name:<38} {getattr(cfg, f.name)!s}")


@config_app.command("set")
def config_set(
    pairs: Annotated[list[str], typer.Argument(metavar="key=value", help="One or more key=value pairs.")],
) -> None:
    """Update one or more runtime config keys atomically."""
    updates: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            typer.echo(f"Error: invalid argument {pair!r} — expected key=value format.", err=True)
            raise typer.Exit(1)
        k, _, v = pair.partition("=")
        updates[k.strip()] = v.strip()

    path = _runtime_toml_path()
    try:
        new_cfg = write_atomic(path, updates)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    typer.echo(f"{'key':<38} value")
    typer.echo("-" * 55)
    for f in dc_fields(new_cfg):
        typer.echo(f"{f.name:<38} {getattr(new_cfg, f.name)!s}")


