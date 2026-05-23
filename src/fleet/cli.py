"""fleet CLI — typer-based surface for the fleet supervisor (FR-32)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, fields as dc_fields
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
from fleet.logging_setup import setup_supervisor_logger
from fleet.queue import BeadsError, BeadsQueue
from fleet.schemas import Task
from fleet.supervisor import Supervisor

app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config", help="Manage runtime configuration.")


def _fleet_home() -> Path:
    """Return the centralized fleet home directory.

    Resolution order:
      1. $FLEET_HOME env var (absolute path).
      2. ~/.fleet
    """
    env = os.environ.get("FLEET_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".fleet"


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


@app.command("task-set")
def task_set(
    task_id: Annotated[str, typer.Argument(help="Task ID.")],
    coder: Annotated[
        str | None,
        typer.Option(
            "--coder",
            help="Per-task coder override; pass empty string to clear.",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help="Per-task model override; pass empty string to clear.",
        ),
    ] = None,
) -> None:
    """Set per-task coder/model override in the task's task.json."""
    if coder is None and model is None:
        typer.echo("Error: provide at least one of --coder/--model.", err=True)
        raise typer.Exit(1)

    q = _queue()
    try:
        task = q.get(task_id)
    except BeadsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    if coder is not None:
        normalized = coder.strip() or None
        if normalized is not None:
            try:
                get_coder(normalized)
            except ValueError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(1)
        q.set_coder(task.id, normalized)
    if model is not None:
        normalized_model = model.strip() or None
        q.set_model(task.id, normalized_model)

    typer.echo(f"Updated task.json for {task.id}.")


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


@app.command(
    "bd",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "help_option_names": [],
    },
    help="Run a `bd` command against the centralized fleet database in $FLEET_HOME.",
)
def bd_passthrough(ctx: typer.Context) -> None:
    """Forward all trailing args verbatim to `bd`, with cwd=$FLEET_HOME.

    For `bd create` / `bd new`, also captures the user's invocation directory
    (the shell cwd from which `fleet bd create` was run) and persists it into
    the task's `task.json` so downstream agents see where the human filed it.
    """
    home = _fleet_home()
    bd_args = list(ctx.args)

    sub = _first_positional(bd_args)
    is_create = sub in ("create", "new")
    user_wants_json = "--json" in bd_args
    user_wants_dry_run = "--dry-run" in bd_args

    if not is_create:
        result = subprocess.run(["bd", *bd_args], cwd=home)
        raise typer.Exit(result.returncode)

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
        BeadsQueue(home).set_cwd(task_id, invocation_cwd)

    if user_wants_json:
        typer.echo(result.stdout, nl=False)
    elif task_id:
        typer.echo(f"Created {task_id}: {task_title or ''}  [cwd: {invocation_cwd}]")
    else:
        typer.echo(result.stdout, nl=False)

    raise typer.Exit(result.returncode)


# ---------------------------------------------------------------------------
# Supervisor command
# ---------------------------------------------------------------------------


@app.command()
def run(
    coder: Annotated[
        str | None,
        typer.Option(
            "--coder",
            help="Override the default coder for this run (else use config 'coder').",
        ),
    ] = None,
    once: Annotated[bool, typer.Option("--once", help="Exit after in-flight count reaches 0.")] = False,
) -> None:
    """Start the fleet supervisor."""
    home = _fleet_home()
    runtime_toml = _runtime_toml_path()
    cfg = load_config(runtime_toml)

    # Validate the resolved coder name up-front so a typo fails fast.
    resolved_coder_name = coder or cfg.coder
    try:
        get_coder(resolved_coder_name)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    q = BeadsQueue(home)
    log_root = Path(cfg.log_root)
    if not log_root.is_absolute():
        log_root = home / log_root
    log = setup_supervisor_logger(log_root)
    supervisor = Supervisor(
        queue=q,
        runtime_toml_path=runtime_toml,
        project_root=home,
        log=log,
        once=once,
        coder_override=coder,
    )
    try:
        rc = asyncio.run(supervisor.run())
    except NotImplementedError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    raise typer.Exit(rc)


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------


def _resolve_log_dir() -> Path:
    cfg = load_config(_runtime_toml_path())
    log_root = Path(cfg.log_root)
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
    return _fleet_home() / "tasks" / task_id


def _print_file_or_exit(path: Path, missing_msg: str) -> None:
    if not path.exists():
        typer.echo(missing_msg, err=True)
        raise typer.Exit(1)
    sys.stdout.write(path.read_text(encoding="utf-8"))


_CONTEXT_WINDOW_TOKENS = 200_000


@dataclass
class _TaskRuntimeStats:
    started_at: datetime | None
    last_event_at: datetime | None
    events: int
    context_tokens: int | None  # peak (input + cache_creation + cache_read)


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _safe_int(v: object) -> int:
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return 0
    return 0


def _task_runtime_stats(task_id: str) -> _TaskRuntimeStats:
    """Best-effort scan of a task's directory for runtime signals."""
    task_dir = _task_dir(task_id)
    if not task_dir.exists():
        return _TaskRuntimeStats(
            started_at=None, last_event_at=None, events=0, context_tokens=None
        )

    started_at: datetime | None = None
    log = task_dir / "log.jsonl"
    if log.exists():
        try:
            with log.open("r", encoding="utf-8") as fh:
                first_line = fh.readline().strip()
            if first_line:
                row = json.loads(first_line)
                ts = row.get("timestamp")
                if isinstance(ts, str):
                    started_at = _parse_iso(ts)
        except (OSError, json.JSONDecodeError):
            pass
        if started_at is None:
            started_at = datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc)

    events_file = task_dir / "events.jsonl"
    events = 0
    last_event_at: datetime | None = None
    context_tokens: int | None = None
    if events_file.exists():
        try:
            with events_file.open("r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    events += 1
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts_str = row.get("ts")
                    if isinstance(ts_str, str):
                        parsed = _parse_iso(ts_str)
                        if parsed is not None:
                            last_event_at = parsed
                    usage = row.get("usage")
                    if isinstance(usage, dict):
                        prompt = (
                            _safe_int(usage.get("input_tokens"))
                            + _safe_int(usage.get("cache_creation_input_tokens"))
                            + _safe_int(usage.get("cache_read_input_tokens"))
                        )
                        if prompt > 0:
                            context_tokens = max(context_tokens or 0, prompt)
        except OSError:
            pass

    return _TaskRuntimeStats(
        started_at=started_at,
        last_event_at=last_event_at,
        events=events,
        context_tokens=context_tokens,
    )


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


def _format_context(tokens: int | None) -> Text:
    if tokens is None or tokens <= 0:
        return Text("-", style="dim")
    pct = tokens / _CONTEXT_WINDOW_TOKENS * 100
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
        table.add_row(
            t.id,
            _format_started(stats.started_at, now),
            _format_elapsed(stats.started_at, now),
            _format_idle(stats.last_event_at, now),
            _format_context(stats.context_tokens),
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


