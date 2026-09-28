"""`fleet blocked` and `fleet ignore` — blocked-bead triage from the terminal.

`fleet blocked --json` lists blocked beads the way
``orchestrator/helper.py`` selects them (blocked in the queue snapshot,
non-empty ``blocked_reason`` in task.json, no active ``ignore_until``), one
object per bead with the task-folder context the helper flow polls through
the ``fleet_blocked`` tool. `fleet ignore <id> --hours N` suppresses triage
for one bead through ``Queue.set_ignore``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from fleet.cli import bootstrap
from fleet.cli.errors import ExitCode, fail
from fleet.cli.options import TaskIdArgument
from fleet.core.ignore_policy import ignore_active
from fleet.core.retry_policy import rounds_for_history
from fleet.orchestrator.helper import STDERR_TAIL_CHARS, read_meta, stderr_tail_text
from fleet.state import paths as state_paths
from fleet.state.attempts import load_attempts
from fleet.state.task_summary import read_declared_result

if TYPE_CHECKING:
    from fleet.beads.queue import Queue
    from fleet.core.task import Task

#: Queue snapshot cap, mirroring ``collect_targets`` in orchestrator/helper.py.
_BLOCKED_LIMIT = 100

#: Reason characters shown per row of the human-readable table.
_REASON_PREVIEW_CHARS = 60


@dataclass(frozen=True)
class BlockedItem:
    """One blocked bead with the fleet task-folder context a helper needs."""

    id: str
    title: str
    blocked_reason: str
    blocked_at: str
    cwd: str
    coder: str
    model: str
    rounds: str
    result_status: str
    task_dir: str
    stderr_tail: str

    def to_dict(self) -> dict[str, str]:
        """Render as a flat string mapping for ``--json`` output."""
        return {
            "id": self.id,
            "title": self.title,
            "blocked_reason": self.blocked_reason,
            "blocked_at": self.blocked_at,
            "cwd": self.cwd,
            "coder": self.coder,
            "model": self.model,
            "rounds": self.rounds,
            "result_status": self.result_status,
            "task_dir": self.task_dir,
            "stderr_tail": self.stderr_tail,
        }


def _opt_str(value: Any) -> str:
    """Render an unknown task.json value as a string ("" when missing)."""
    return str(value) if isinstance(value, str) else str(value or "")


def blocked_item(fleet_home: Path, bead: Task, now: datetime) -> BlockedItem | None:
    """Build the triage item for one blocked bead, or None when skipped.

    Skipped: human-blocked beads (no task.json ``blocked_reason``) and beads
    with an active ``ignore_until`` — the same filters ``collect_targets``
    applies. Values mirror the helper template and the blocked-task event
    payload (strings only, "" when unknown, ``stderr_tail`` capped).
    """
    task_dir = state_paths.task_dir(fleet_home, bead.id)
    meta = read_meta(fleet_home, bead.id)
    blocked_reason = str(meta.get("blocked_reason") or "")
    if not blocked_reason:
        return None
    raw_ignore = meta.get("ignore_until")
    if ignore_active(raw_ignore if isinstance(raw_ignore, str) else None, now):
        return None
    declared = read_declared_result(task_dir)
    status = declared.get("status") if isinstance(declared, dict) else None
    tail = stderr_tail_text(task_dir) or ""
    return BlockedItem(
        id=bead.id,
        title=str(meta.get("title") or bead.title or ""),
        blocked_reason=blocked_reason,
        blocked_at=_opt_str(meta.get("blocked_at")),
        cwd=str(meta.get("cwd") or bead.cwd or ""),
        coder=_opt_str(meta.get("coder")),
        model=_opt_str(meta.get("model")),
        rounds=str(rounds_for_history(load_attempts(task_dir))),
        result_status=str(status or ""),
        task_dir=str(task_dir.absolute()),
        stderr_tail=tail.strip()[-STDERR_TAIL_CHARS:] or "",
    )


def collect_blocked(queue: Queue, fleet_home: Path, now: datetime) -> list[BlockedItem]:
    """Every triage item for the current queue snapshot, skipping unreadable beads."""
    try:
        beads = queue.list_blocked(limit=_BLOCKED_LIMIT)
    except Exception as exc:
        fail(f"cannot list blocked beads: {exc}", ExitCode.BACKEND)
    items: list[BlockedItem] = []
    for bead in beads:
        try:
            item = blocked_item(fleet_home, bead, now)
        except Exception:
            continue
        if item is not None:
            items.append(item)
    return items


def run_blocked(fleet_home: Path, json_output: bool) -> None:
    """Print blocked beads with task-folder context (JSON with --json, else a table)."""
    items = collect_blocked(bootstrap.queue(fleet_home), fleet_home, datetime.now(tz=UTC))
    if json_output:
        typer.echo(json.dumps([item.to_dict() for item in items], indent=2))
        return
    if not items:
        typer.echo("No blocked beads.")
        return
    table = Table(
        title="Fleet — blocked beads",
        title_style="bold",
        header_style="bold cyan",
        border_style="cyan",
        show_lines=False,
        pad_edge=False,
    )
    table.add_column("ID", style="bold cyan", no_wrap=True)
    table.add_column("Blocked at", no_wrap=True)
    table.add_column("Reason", overflow="fold")
    for item in items:
        table.add_row(item.id, item.blocked_at or "-", item.blocked_reason[:_REASON_PREVIEW_CHARS])
    Console(soft_wrap=False).print(table)


def run_ignore(fleet_home: Path, task_id: str, hours: float) -> None:
    """Suppress helper triage for *task_id* for *hours* hours."""
    if hours <= 0:
        fail("--hours must be a positive number of hours.", ExitCode.USAGE)
    queue = bootstrap.queue(fleet_home)
    try:
        queue.get(task_id)
    except Exception:
        fail(f"Task {task_id} not found.", ExitCode.NOT_FOUND)
    ignore_until = (datetime.now(tz=UTC) + timedelta(hours=hours)).isoformat()
    queue.set_ignore(task_id, ignore_until)
    typer.echo(f"Ignored {task_id} until {ignore_until}.")


def register(app: typer.Typer) -> None:
    """Wire `fleet blocked` and `fleet ignore` as thin closures over the helpers above."""

    @app.command("blocked")
    def blocked_cmd(
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit blocked beads as JSON.")
        ] = False,
    ) -> None:
        """List blocked beads with fleet's task-folder context (reason, cwd, stderr tail)."""
        run_blocked(bootstrap.fleet_home(), json_output)

    @app.command("ignore")
    def ignore_cmd(
        task_id: TaskIdArgument,
        hours: Annotated[float, typer.Option("--hours", help="Ignore triage for N hours.")] = 24.0,
    ) -> None:
        """Suppress helper triage for a blocked bead for N hours."""
        run_ignore(bootstrap.fleet_home(), task_id, hours)
