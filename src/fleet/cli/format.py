"""Table formatters shared by the CLI's task-listing commands.

Renders the same numbers `state.task_summary.build_task_summary` computes,
so `fleet tasks` and GET /api/tasks never disagree.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rich.table import Table
from rich.text import Text

from fleet.core.task import Task
from fleet.state.paths import task_dir as _task_dir
from fleet.state.task_summary import build_task_summary


def format_started(started_at_iso: str | None) -> str:
    if not started_at_iso:
        return "-"
    ts = datetime.fromisoformat(started_at_iso)
    now = datetime.now(tz=UTC)
    local = ts.astimezone()
    if local.date() == now.astimezone().date():
        return local.strftime("%H:%M:%S")
    return local.strftime("%b %d %H:%M")


def format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        m, s = divmod(total, 60)
        return f"{m}m{s:02d}s"
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h{m:02d}m"


def format_idle(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    return f"{total // 3600}h"


def format_events(count: int) -> str:
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1000:.1f}k"
    return f"{count / 1_000_000:.1f}M"


def format_tokens(count: int) -> str:
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1000:.1f}k"
    return f"{count / 1_000_000:.2f}M"


def format_context(tokens: int | None, pct: float | None) -> Text:
    if tokens is None or tokens <= 0:
        return Text("-", style="dim")
    label = f"{format_tokens(tokens)} ({pct:.0f}%)" if pct is not None else format_tokens(tokens)
    if pct is not None and pct >= 80:
        return Text(label, style="bold red")
    if pct is not None and pct >= 50:
        return Text(label, style="yellow")
    return Text(label, style="green")


def format_override(task_value: str | None, default: str) -> Text:
    """Render a per-task override: bold when explicitly set, dim default-name otherwise."""
    if task_value:
        return Text(task_value, style="bold")
    return Text(default, style="dim")


def render_tasks_table(
    tasks: list[Task], home: Path, default_coder: str, default_model: str
) -> Table:
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
        task_dir = _task_dir(home, t.id)
        data = {
            "id": t.id,
            "status": t.status,
            # Resolve to the effective coder/model so the context-limit lookup
            # matches what actually ran, even when the task used fleet's default.
            "coder": t.coder or default_coder,
            "model": t.model or default_model,
            "title": t.title,
            "cwd": t.cwd,
        }
        summary = build_task_summary(task_dir, data, home)
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
