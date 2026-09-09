"""All CLI printing: tables, status lines, and log tails.

Called by ``cli/tasks.py``, ``cli/daemons.py``, and ``cli/telegram.py``.
Commands compute (fetch queue rows, resolve paths, read files) and these
functions print — no command reads a file, runs a subprocess, or derives
display data. Absorbs the old ``cli/format.py`` (deleted): the tasks table
renders the same numbers ``state.task_summary.build_task_summary`` computes,
so ``fleet tasks`` and GET /api/tasks never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from fleet.beads.cache import get_beads_status_map
from fleet.coders import context_limit_for
from fleet.core.effective import effective_coder_model
from fleet.core.job_snapshot import JobSnapshot
from fleet.core.task import Task
from fleet.observability.daemon import StartResult
from fleet.observability.process import ServiceStatus
from fleet.state import runtime_stats
from fleet.state.paths import task_dir
from fleet.state.task_summary import build_task_summary, context_overrides_for_home

_SEC_PER_MINUTE = 60
_SEC_PER_HOUR = 3600
_THOUSAND = 1000
_MILLION = 1_000_000
_PCT_WARN = 50
_PCT_CRITICAL = 80

_console = Console()


def format_started(started_at_iso: str | None) -> str:
    """Local start time (today: HH:MM:SS, older: Mon DD HH:MM), "-" when unknown."""
    if not started_at_iso:
        return "-"
    ts = datetime.fromisoformat(started_at_iso)
    now = datetime.now(tz=UTC)
    local = ts.astimezone()
    if local.date() == now.astimezone().date():
        return local.strftime("%H:%M:%S")
    return local.strftime("%b %d %H:%M")


def format_elapsed(seconds: float | None) -> str:
    """Short duration (12s, 3m04s, 2h05m), "-" when unknown."""
    if seconds is None:
        return "-"
    total = max(0, int(seconds))
    if total < _SEC_PER_MINUTE:
        return f"{total}s"
    if total < _SEC_PER_HOUR:
        m, s = divmod(total, _SEC_PER_MINUTE)
        return f"{m}m{s:02d}s"
    h, rem = divmod(total, _SEC_PER_HOUR)
    m, _ = divmod(rem, _SEC_PER_MINUTE)
    return f"{h}h{m:02d}m"


def format_idle(seconds: float | None) -> str:
    """Coarse idle time (12s, 3m, 2h), "-" when unknown."""
    if seconds is None:
        return "-"
    total = max(0, int(seconds))
    if total < _SEC_PER_MINUTE:
        return f"{total}s"
    if total < _SEC_PER_HOUR:
        return f"{total // _SEC_PER_MINUTE}m"
    return f"{total // _SEC_PER_HOUR}h"


def format_events(count: int) -> str:
    """Compact event count (999, 1.2k, 3.40M)."""
    if count < _THOUSAND:
        return str(count)
    if count < _MILLION:
        return f"{count / _THOUSAND:.1f}k"
    return f"{count / _MILLION:.1f}M"


def format_tokens(count: int) -> str:
    """Compact token count (999, 1.2k, 3.40M)."""
    if count < _THOUSAND:
        return str(count)
    if count < _MILLION:
        return f"{count / _THOUSAND:.1f}k"
    return f"{count / _MILLION:.2f}M"


def format_context(tokens: int | None, pct: float | None) -> Text:
    """Context usage cell, colored by pressure (green/yellow/bold red)."""
    if tokens is None or tokens <= 0:
        return Text("-", style="dim")
    label = f"{format_tokens(tokens)} ({pct:.0f}%)" if pct is not None else format_tokens(tokens)
    if pct is not None and pct >= _PCT_CRITICAL:
        return Text(label, style="bold red")
    if pct is not None and pct >= _PCT_WARN:
        return Text(label, style="yellow")
    return Text(label, style="green")


def format_override(task_value: str | None, default: str) -> Text:
    """Per-task override: bold when explicitly set, dim default-name otherwise."""
    if task_value:
        return Text(task_value, style="bold")
    return Text(default, style="dim")


def render_tasks_table(
    tasks: list[Task], fleet_home: Path, default_coder: str, default_model: str
) -> Table:
    """Rich table of running tasks with start/elapsed/idle/context/coder/model."""
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

    overrides = context_overrides_for_home(fleet_home)
    beads_map = get_beads_status_map(fleet_home)
    for t in tasks:
        coder, model = effective_coder_model(t.coder, t.model, default_coder, default_model)
        data = {
            "id": t.id,
            "status": t.status,
            # Resolve to the effective coder/model so the context-limit lookup
            # matches what actually ran, even when the task used fleet's default.
            "coder": coder,
            "model": model,
            "title": t.title,
            "cwd": t.cwd,
        }
        summary = build_task_summary(
            task_dir(fleet_home, t.id),
            data,
            fleet_home,
            context_limit=context_limit_for(coder, model, overrides),
            blocked_notes=(beads_map or {}).get(t.id, {}).get("notes"),
        )
        table.add_row(
            t.id,
            format_started(summary["started_at"]),
            format_elapsed(summary["elapsed_sec"]),
            format_idle(summary["idle_sec"]),
            format_context(summary["context_tokens"], summary["context_pct"]),
            format_events(summary["events"]),
            format_override(t.coder, default_coder),
            format_override(t.model, default_model),
            t.title,
            t.cwd or "",
        )
    return table


def print_tasks_table(
    tasks: list[Task], fleet_home: Path, default_coder: str, default_model: str
) -> None:
    """Print the running-tasks table, or the empty message when there are none."""
    if not tasks:
        typer.echo("No running tasks.")
        return
    table = render_tasks_table(tasks, fleet_home, default_coder, default_model)
    Console(soft_wrap=False).print(table)


def print_ready_tasks(tasks: list[Task]) -> None:
    """Print one ready task per line, or the empty message."""
    if not tasks:
        typer.echo("No ready tasks.")
        return
    width = max(len(t.id) for t in tasks) + 2
    for t in tasks:
        cwd_suffix = f"  [{t.cwd}]" if t.cwd else ""
        typer.echo(f"{t.id:<{width}}{t.title}{cwd_suffix}")


def print_ignored_tasks(rows: list[tuple[Task, str]]) -> None:
    """Print triage-ignored tasks with their ignore-until stamps, or the empty message."""
    if not rows:
        typer.echo("No ignored tasks.")
        return
    width = max(len(t.id) for t, _ in rows) + 2
    for t, until in rows:
        typer.echo(f"{t.id:<{width}}{t.title}  [ignored until {until}]")


def print_task_show(
    task: Task, coder: str | None, model: str | None, coder_defaulted: bool, model_defaulted: bool
) -> None:
    """Print one task's detail lines for `fleet show`."""
    typer.echo(f"id:     {task.id}")
    typer.echo(f"title:  {task.title}")
    typer.echo(f"status: {task.status}")
    if task.cwd:
        typer.echo(f"cwd:    {task.cwd}")
    coder_suffix = " (default)" if coder_defaulted else ""
    model_suffix = " (default)" if model_defaulted else ""
    typer.echo(f"coder:  {coder}{coder_suffix}")
    typer.echo(f"model:  {model}{model_suffix}")
    if task.description:
        typer.echo(f"desc:   {task.description}")


@dataclass(frozen=True)
class ChildRow:
    """One job child line: id plus status (may be unknown)."""

    id: str
    status: str | None = None


@dataclass(frozen=True)
class JobView:
    """Everything `fleet job view` prints: snapshot, design flag, children, gate."""

    task_id: str
    title: str
    status: str
    phase: str
    snapshot: JobSnapshot
    has_design: bool = False
    children: tuple[ChildRow, ...] = ()
    gate: tuple[tuple[str, str], ...] = ()


def print_job_view(view: JobView) -> None:
    """Print a job's phase, children table, and pending gate questions."""
    typer.echo(f"id:     {view.task_id}")
    typer.echo(f"title:  {view.title}")
    typer.echo(f"status: {view.status}")
    typer.echo(f"phase:  {view.phase}")
    typer.echo(
        "artifacts: "
        f"research={'yes' if view.snapshot.has_research else 'no'} "
        f"design={'yes' if view.has_design else 'no'} "
        f"tasks={'yes' if view.snapshot.has_tasks else 'no'} "
        f"approved={'yes' if view.snapshot.approved else 'no'}"
    )
    if not view.children:
        typer.echo("children: (none)")
    else:
        typer.echo(f"children: {len(view.children)}")
        for child in view.children:
            typer.echo(f"  {child.id}  [{child.status}]")
    if view.gate:
        count = len(view.gate)
        noun = "question" if count == 1 else "questions"
        typer.echo(f"gate: {count} pending {noun}(s)")
        for qid, first_line in view.gate:
            typer.echo(f"  {qid}: {first_line}")
    else:
        typer.echo("gate: no pending questions")


def print_tail_header(task_id: str, stats: runtime_stats.TaskRuntimeStats) -> None:
    """Print the `fleet tail` summary line above the rendered events."""
    last_event_str = stats.last_event_at.strftime("%H:%M:%S") if stats.last_event_at else "-"
    ctx = stats.context_tokens if stats.context_tokens is not None else "-"
    typer.echo(
        f"{task_id}  events={stats.events}  last_event={last_event_str}  context_tokens={ctx}"
    )


def print_lines(lines: list[str]) -> None:
    """Echo pre-rendered lines (tail output, file content split into lines)."""
    for line in lines:
        typer.echo(line)


def print_text(text: str) -> None:
    """Write pre-read file text to stdout (log/state/result artifacts)."""

    typer.echo(text, nl=False)


def print_file_or_exit(path: Path, missing_msg: str) -> None:
    """Print an artifact file, exiting 1 with *missing_msg* when it is absent."""
    if not path.exists():
        typer.echo(missing_msg, err=True)
        raise typer.Exit(1)
    typer.echo(path.read_text(encoding="utf-8"), nl=False)


def print_init_done(fleet_home: Path) -> None:
    """Confirm `fleet init` created the fleet_home directory."""
    typer.echo(f"Fleet fleet_home initialized at {fleet_home}")


def print_kill_sent(task_id: str) -> None:
    """Confirm the kill sentinel was written for *task_id*."""
    typer.echo(f"Kill signal sent for task {task_id}.")


def print_gc_result(
    archived: int, mb: float, archive_dir: Path, skipped: int, dry_run: bool
) -> None:
    """Print how many task dirs archiving moved (or would move on dry-run)."""
    prefix = "dry-run: " if dry_run else ""
    typer.echo(
        f"{prefix}archived {archived} task dirs ({mb:.1f} MB) -> {archive_dir}; skipped {skipped}"
    )


def print_gc_purged(deleted: int, freed_mb: float, skipped: int, dry_run: bool) -> None:
    """Print how many archived task dirs purging deleted (or would delete)."""
    prefix = "dry-run: " if dry_run else ""
    typer.echo(
        f"{prefix}purged {deleted} archived task dirs ({freed_mb:.1f} MB freed); skipped {skipped}"
    )


def print_start_report(result: StartResult, label: str, logfile: Path) -> None:
    """Echo a daemon start/restart outcome; callers exit nonzero on immediate death."""
    if result.already_running:
        _console.print(f"[yellow]{label} already running[/] (pid {result.pid}).")
        return
    if not result.alive:
        _console.print(f"[red]{label} failed to start[/] — process exited immediately.")
        _print_log_tail(logfile)
        raise typer.Exit(1)
    _console.print(f"[green]{label} started[/] (pid {result.pid}). Logs: {logfile}")


def _print_log_tail(path: Path, n: int = 20) -> None:
    """Print the last *n* lines of a daemon logfile after a failed start."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if not lines:
        return
    _console.print(f"[dim]--- last {min(n, len(lines))} lines of {path} ---[/]")
    for line in lines[-n:]:
        _console.print(line)


def print_service_status(label: str, status: ServiceStatus, restart_hint: str) -> None:
    """Print one daemon's liveness line plus a stale-code warning when stale."""
    if not status.alive:
        _console.print(f"{label}: [red]stopped[/]")
        return
    parts = [f"pid {status.pid}"] if status.pid else []
    if status.since:
        parts.append(f"since {status.since}")
    if status.fingerprint:
        parts.append(f"fingerprint {status.fingerprint}")
    _console.print(f"{label}: [green]running[/] ({', '.join(parts)})")
    if status.stale:
        _console.print(
            f"[bold yellow]⚠  {label} is running stale code[/] — "
            f"run [bold]{restart_hint}[/] to pick up changes."
        )


@dataclass(frozen=True)
class TelegramStatus:
    """Outbound/inbound readiness facts `fleet telegram status` prints."""

    bot_username: str | None = None
    bot_error: str | None = None
    token_set: bool = False
    chat_id: str = ""
    allowed_ids: str = ""
    default_cwd: str = ""


def print_telegram_status(status: TelegramStatus, masked_token: str) -> None:
    """Print Telegram config/connectivity plus the outbound/inbound verdicts."""
    width = 26
    typer.echo(f"{'TELEGRAM_BOT_TOKEN':<{width}} {masked_token}")
    if status.bot_username is not None:
        typer.echo(f"{'bot':<{width}} @{status.bot_username}")
    elif status.bot_error is not None:
        typer.echo(f"{'bot':<{width}} token invalid/unreachable ({status.bot_error})")
    else:
        typer.echo(f"{'bot':<{width}} (token not set)")
    typer.echo("")
    typer.echo(f"{'telegram_chat_id':<{width}} {status.chat_id or '(not set)'}")
    typer.echo(f"{'telegram_allowed_ids':<{width}} {status.allowed_ids or '(not set)'}")
    typer.echo(f"{'telegram_default_cwd':<{width}} {status.default_cwd or '(not set)'}")
    outbound_ok = status.bot_username is not None and bool(status.chat_id)
    inbound_ok = status.bot_username is not None and bool(status.allowed_ids)
    typer.echo("")
    out_verdict = "ok" if outbound_ok else "NOT configured — need valid token + telegram_chat_id"
    in_verdict = "ok" if inbound_ok else "NOT configured — need valid token + telegram_allowed_ids"
    typer.echo(f"{'outbound notifications':<{width}} {out_verdict}")
    typer.echo(f"{'inbound /task creation':<{width}} {in_verdict}")


def telegram_verdict_ok(status: TelegramStatus) -> bool:
    """True when both outbound and inbound Telegram paths are configured."""
    return status.bot_username is not None and bool(status.chat_id) and bool(status.allowed_ids)


def mask_token(token: str, prefix_len: int = 6) -> str:
    """Mask a bot token as '12345...:***', never exposing the secret part."""
    if ":" not in token:
        return (token[:prefix_len] + "...") if len(token) > prefix_len else "***"
    bot_id, _ = token.split(":", 1)
    return f"{bot_id}...:***"


def print_test_sent(chat_id: str) -> None:
    """Confirm the Telegram test message reached *chat_id*."""
    typer.echo(f"Message sent to {chat_id}.")


def print_setup_summary(path: Path, written_keys: dict[str, str]) -> None:
    """Print which keys the telegram setup wizard wrote to runtime.toml."""
    typer.echo(f"\nSetup complete. Written to {path}:")
    if written_keys:
        for k, v in written_keys.items():
            typer.echo(f"  {k} = {v}")
    else:
        typer.echo("  (nothing written — all values were provided via flags)")
