"""Task-management commands: init, ready, show, tasks, task, kill, gc, tail, log, job.

Every command is a thin closure (at most a few lines): it parses input via
typer, calls a module-level helper that computes, and prints through
``cli/render.py``. Artifact paths come from ``state/artifact_locator``;
fleet-fleet_home/queue/config dependencies come from ``cli/bootstrap``.
"""

from __future__ import annotations

import sys
import time
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from typer.core import TyperCommand

from fleet.beads import client as beads_client
from fleet.beads.client import BdError
from fleet.cli import bootstrap, render
from fleet.cli.render import ChildRow, JobView
from fleet.core.effective import effective_coder_model
from fleet.core.job_phase import phase_of
from fleet.core.job_snapshot import JobSnapshot
from fleet.integrations.ask_human.store import Question, QuestionStore
from fleet.observability import tailview
from fleet.state import paths as state_paths
from fleet.state import runtime_stats
from fleet.state.archive import apply_gc, apply_purge, plan_gc, plan_purge
from fleet.state.artifact_locator import locate
from fleet.state.incremental_read import read_new_bytes
from fleet.state.legacy_task_dir import legacy_state_text

if TYPE_CHECKING:
    from fleet.beads.queue import BeadsQueue
    from fleet.core.task import Task


class TaskAction(StrEnum):
    """Which artifact `fleet task <id>` prints."""

    log = "log"
    state = "state"
    result = "result"


def _fetch_ready(queue: BeadsQueue, limit: int) -> list[Task]:
    """Ready tasks, exiting 1 when the queue is unreadable."""
    try:
        return queue.list_ready(limit=limit)
    except BdError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _fetch_in_progress(queue: BeadsQueue, limit: int) -> list[Task]:
    """Running tasks, exiting 1 when the queue is unreadable."""
    try:
        return queue.list_in_progress(limit=limit)
    except BdError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _fetch_ignored(queue: BeadsQueue, limit: int) -> list[tuple[Task, str]]:
    """Triage-ignored tasks with their ignore-until stamps."""
    try:
        return queue.list_ignored(limit=limit)
    except BdError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _fetch_job(queue: BeadsQueue, job_id: str) -> Task:
    """One bead, exiting 1 when bd cannot show it."""
    try:
        return queue.get(job_id)
    except BdError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def _fetch_children(queue: BeadsQueue, job_id: str) -> list[Any]:
    """Child beads, best-effort (empty when bd cannot list them)."""
    try:
        return queue.list_children(job_id)
    except BdError:
        return []


def _pending_gate(job_id: str) -> list[Question]:
    """Pending job-gate questions, best-effort (empty when the store is unreadable)."""
    try:
        return QuestionStore().fetch_pending_for_task(job_id, "job_gate")
    except Exception:
        return []


def _child_row(child: Any) -> ChildRow:
    """Normalize a Task-like or raw-dict child into an id/status row."""
    if isinstance(child, dict):
        return ChildRow(id=str(child.get("id")), status=child.get("status"))
    return ChildRow(id=str(getattr(child, "id", "")), status=getattr(child, "status", None))


def _gate_row(question: Question) -> tuple[str, str]:
    """(id, first prompt line) for one pending gate question."""
    prompt = question.get("prompt") or ""
    first_line = prompt.splitlines()[0] if prompt else ""
    return (str(question.get("id")), first_line)


def _build_job_view(
    fleet_home: Path, task: Task, children: list[Any], pending: list[Question]
) -> JobView:
    """Assemble the JobSnapshot-backed view one `fleet job view` prints."""
    artifacts = state_paths.task_dir(fleet_home, task.id) / "artifacts"
    snapshot = JobSnapshot(
        has_research=(artifacts / "RESEARCH.md").exists(),
        has_tasks=(artifacts / "tasks.json").exists(),
        gate_enabled=(task.job_gate or "") != "off",
        approved=(artifacts / "APPROVED").exists(),
        has_children=len(children) > 0,
    )
    return JobView(
        task_id=task.id,
        title=task.title,
        status=task.status,
        phase=str(phase_of(snapshot)),
        snapshot=snapshot,
        has_design=(artifacts / "DESIGN.md").exists(),
        children=tuple(_child_row(c) for c in children),
        gate=tuple(_gate_row(q) for q in pending),
    )


def _help_row(task: Task, width: int, default_coder: str, default_model: str) -> str:
    """One `fleet task --help` epilog line with the task's effective coder/model."""
    coder, model = effective_coder_model(task.coder, task.model, default_coder, default_model)
    return f"  {task.id:<{width}}[{coder}/{model}]  {task.title}"


def _running_tasks_help_text() -> str:
    """Dynamic `--help` epilog for `fleet task`: running tasks and their coders."""
    header = "Currently running tasks (run `fleet tasks` for full details):"
    fleet_home = bootstrap.fleet_home()
    try:
        tasks = bootstrap.queue(fleet_home).list_in_progress(limit=50)
    except BdError:
        return f"{header}\n\n  (unable to query bd queue)"
    if not tasks:
        return f"{header}\n\n  (none)"
    try:
        config = bootstrap.config(fleet_home)
        default_coder, default_model = config.coder, config.model
    except OSError:
        default_coder, default_model = "claude", "sonnet"
    width = max(len(t.id) for t in tasks) + 2
    rows = [_help_row(t, width, default_coder, default_model) for t in tasks]
    # Double newlines preserve line breaks through typer's rich epilog renderer,
    # which collapses single newlines within a paragraph to spaces.
    return header + "\n\n" + "\n\n".join(rows)


class _TaskHelpCommand(TyperCommand):
    """`fleet task` command whose --help appends a list of running tasks."""

    def format_help(self, ctx, formatter):
        self.epilog = _running_tasks_help_text()
        return super().format_help(ctx, formatter)


def _tail_follow(events_path: Path, buffer_n: int) -> None:
    """Follow events.jsonl incrementally, rendering new lines as they arrive."""
    try:
        offset = events_path.stat().st_size
    except OSError:
        return
    remainder = ""
    try:
        while True:
            time.sleep(1)
            new_bytes, offset = read_new_bytes(events_path, offset)
            if not new_bytes:
                continue
            chunk = remainder + new_bytes.decode("utf-8", errors="replace")
            if "\n" in chunk:
                lines_part, remainder = chunk.rsplit("\n", 1)
            else:
                lines_part, remainder = chunk, ""
            if not lines_part.strip():
                continue
            rendered = tailview.render_lines(lines_part.splitlines())
            if rendered:
                render.print_lines(rendered[-buffer_n:] if buffer_n > 0 else rendered)
    except KeyboardInterrupt:
        sys.exit(0)


def run_init(fleet_home: Path, force: bool) -> None:
    """Create the fleet home (beads + defaults + tasks dir)."""
    fleet_home.mkdir(parents=True, exist_ok=True)
    if force or not (fleet_home / ".beads").exists():
        try:
            beads_client.run_bd(["init"], cwd=fleet_home)
        except BdError as exc:
            if "already" not in str(exc).lower():
                typer.echo(f"bd init failed: {exc}", err=True)
                raise typer.Exit(1) from exc
    bootstrap.config(fleet_home)  # writes defaults if missing
    (fleet_home / "tasks").mkdir(exist_ok=True)
    render.print_init_done(fleet_home)


def run_show(fleet_home: Path, task_id: str, json_output: bool) -> None:
    """Print one task as raw bd JSON (--json) or as detail lines."""
    if json_output:
        result = beads_client.try_run_bd(["show", task_id, "--json"], cwd=fleet_home)
        if result.returncode != 0:
            typer.echo(result.stderr.strip(), err=True)
            raise typer.Exit(result.returncode)
        typer.echo(result.stdout, nl=False)
        return
    task = _fetch_job(bootstrap.queue(fleet_home), task_id)
    config = bootstrap.config(fleet_home)
    coder, model = effective_coder_model(task.coder, task.model, config.coder, config.model)
    render.print_task_show(task, coder, model, task.coder is None, task.model is None)


def run_kill(fleet_home: Path, task_id: str) -> None:
    """Interrupt a running task via its .kill sentinel."""
    task_dir = state_paths.task_dir(fleet_home, task_id)
    if not (task_dir / "task.json").exists():
        typer.echo(f"Task {task_id} not found.", err=True)
        raise typer.Exit(1)
    (task_dir / ".kill").touch()
    render.print_kill_sent(task_id)


def run_tasks(fleet_home: Path, limit: int, ignored: bool) -> None:
    """Print running tasks (table) or triage-ignored tasks (list)."""
    q = bootstrap.queue(fleet_home)
    if ignored:
        render.print_ignored_tasks(_fetch_ignored(q, limit))
        return
    tasks = _fetch_in_progress(q, limit)
    config = bootstrap.config(fleet_home)
    render.print_tasks_table(tasks, fleet_home, config.coder, config.model)


def preview_gc(fleet_home: Path, days: int) -> None:
    """Print what archiving closed task dirs would move (no moves)."""
    result = plan_gc(fleet_home, days)
    render.print_gc_preview(
        len(result.archived),
        result.bytes_moved / (1024 * 1024),
        fleet_home / "archive" / "tasks",
        result.skipped,
    )


def run_gc(fleet_home: Path, days: int) -> None:
    """Archive closed task dirs older than *days* and print the result."""
    result = apply_gc(fleet_home, plan_gc(fleet_home, days))
    render.print_gc_result(
        len(result.archived),
        result.bytes_moved / (1024 * 1024),
        fleet_home / "archive" / "tasks",
        result.skipped,
    )


def preview_purge(fleet_home: Path) -> None:
    """Print what purging old archives would delete (no deletes)."""
    config = bootstrap.config(fleet_home)
    purged = plan_purge(fleet_home, config.gc_archive_days)
    render.print_purge_preview(
        len(purged.deleted), purged.bytes_freed / (1024 * 1024), purged.skipped
    )


def run_purge(fleet_home: Path) -> None:
    """Permanently delete archived task dirs past retention and print the result."""
    config = bootstrap.config(fleet_home)
    purged = apply_purge(fleet_home, plan_purge(fleet_home, config.gc_archive_days))
    render.print_purge_result(
        len(purged.deleted), purged.bytes_freed / (1024 * 1024), purged.skipped
    )


def _print_state(fleet_home: Path, task_id: str, task_dir: Path) -> None:
    """Print STATE.md, or the legacy view for old task dirs without one."""
    state_path = locate(fleet_home, task_id, "state")
    if state_path.exists():
        render.print_file_or_exit(state_path, f"No STATE.md for task {task_id}")
        return
    legacy = legacy_state_text(task_dir)
    if legacy is None:
        typer.echo(f"No STATE.md for task {task_id}", err=True)
        raise typer.Exit(1)
    render.print_text(legacy)


def run_task_artifact(fleet_home: Path, task_id: str, action: TaskAction) -> None:
    """Print a task's log, STATE.md, or RESULT.json artifact."""
    task_dir = state_paths.task_dir(fleet_home, task_id)
    if not task_dir.exists():
        typer.echo(f"No task directory at {task_dir}", err=True)
        raise typer.Exit(1)
    if action is TaskAction.state:
        _print_state(fleet_home, task_id, task_dir)
    elif action is TaskAction.result:
        render.print_file_or_exit(
            locate(fleet_home, task_id, "result"), f"No RESULT.json for task {task_id}"
        )
    else:
        render.print_file_or_exit(locate(fleet_home, task_id, "log"), f"No log for task {task_id}")


def run_job_view(fleet_home: Path, job_id: str) -> None:
    """Render one job's phase, children table, and pending gate questions."""
    q = bootstrap.queue(fleet_home)
    task = _fetch_job(q, job_id)
    children = _fetch_children(q, job_id)
    render.print_job_view(_build_job_view(fleet_home, task, children, _pending_gate(job_id)))


def _print_tail_events(events_path: Path, line_count: int, follow: bool) -> None:
    """Print the last *line_count* rendered events, then follow when asked."""
    try:
        raw_lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        typer.echo(f"Error: cannot read {events_path}", err=True)
        raise typer.Exit(1) from exc
    rendered = tailview.render_lines(raw_lines)
    if not rendered:
        typer.echo("(no renderable events)")
        return
    render.print_lines(rendered[-line_count:] if line_count > 0 else rendered)
    if follow:
        _tail_follow(events_path, line_count)


def run_tail(fleet_home: Path, task_id: str, line_count: int, follow: bool) -> None:
    """Print a human-readable, one-line-per-event view of a task's events.jsonl."""
    task_dir = state_paths.task_dir(fleet_home, task_id)
    if not task_dir.exists():
        typer.echo(f"No task directory for {task_id} at {task_dir}", err=True)
        raise typer.Exit(1)
    events_path = locate(fleet_home, task_id, "events")
    # If events.jsonl does not exist yet, still print header; --follow will wait.
    if not events_path.exists():
        typer.echo(f"{task_id}  events=0  last_event=-  context_tokens=-")
        typer.echo("(events.jsonl does not exist yet)")
        if not follow:
            return
        while not events_path.exists():
            time.sleep(1)
    render.print_tail_header(task_id, runtime_stats.task_runtime_stats_for(task_id))
    _print_tail_events(events_path, line_count, follow)


def _latest_supervisor_log(log_dir: Path) -> Path:
    """Newest fleet-*.jsonl file, exiting 1 when the dir is missing or empty."""
    if not log_dir.exists():
        typer.echo(f"No log directory at {log_dir}", err=True)
        raise typer.Exit(1)
    candidates = sorted(log_dir.glob("fleet-*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        typer.echo(f"No log files in {log_dir}", err=True)
        raise typer.Exit(1)
    return candidates[-1]


def run_log(fleet_home: Path, lines: int | None) -> None:
    """Print the newest supervisor log in full, or only its last N lines."""
    latest = _latest_supervisor_log(bootstrap.log_dir(fleet_home))
    if lines is None:
        render.print_text(latest.read_text(encoding="utf-8"))
        return
    if lines <= 0:
        typer.echo("Error: lines must be a positive integer.", err=True)
        raise typer.Exit(1)
    with latest.open("r", encoding="utf-8") as fh:
        render.print_text("".join(fh.readlines()[-lines:]))


def register(app: typer.Typer) -> None:
    """Wire every task command as a thin closure over the helpers above."""
    job_app = typer.Typer(no_args_is_help=True, help="Inspect job (epic) beads.")
    app.add_typer(job_app, name="job")

    @app.command()
    def init(
        force: Annotated[
            bool, typer.Option("--force", help="Re-init even if .beads already exists.")
        ] = False,
    ) -> None:
        """Initialize the fleet home directory (beads + defaults)."""
        run_init(bootstrap.fleet_home(), force)

    @app.command()
    def ready(
        limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum tasks to list.")] = 50,
    ) -> None:
        """List ready tasks."""
        render.print_ready_tasks(_fetch_ready(bootstrap.queue(bootstrap.fleet_home()), limit))

    @app.command()
    def show(
        task_id: Annotated[str, typer.Argument(help="Task ID.")],
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit raw bd show JSON envelope.")
        ] = False,
    ) -> None:
        """Show one task."""
        run_show(bootstrap.fleet_home(), task_id, json_output)

    @app.command("kill")
    def kill_cmd(
        task_id: Annotated[str, typer.Argument(help="Task ID to kill.")],
    ) -> None:
        """Interrupt a running task (supervisor terminates it and marks it manually interrupted)."""
        run_kill(bootstrap.fleet_home(), task_id)

    @app.command("tasks")
    def tasks_cmd(
        limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum tasks to list.")] = 50,
        ignored: Annotated[
            bool,
            typer.Option("--ignored", help="List triage-ignored blocked tasks."),
        ] = False,
    ) -> None:
        """List currently running tasks with start time, elapsed, idle, context usage, events."""
        run_tasks(bootstrap.fleet_home(), limit, ignored)

    @app.command("gc")
    def gc_cmd(
        days: Annotated[
            int, typer.Option("--days", help="Archive closed tasks older than N days.")
        ] = 30,
        dry_run: Annotated[
            bool, typer.Option("--dry-run", help="List what would be archived without moving.")
        ] = False,
        purge: Annotated[
            bool,
            typer.Option(
                "--purge",
                help="Also permanently delete archived tasks older than gc_archive_days.",
            ),
        ] = False,
    ) -> None:
        """Archive closed task directories older than N days to archive/tasks."""
        fleet_home = bootstrap.fleet_home()
        if dry_run:
            preview_gc(fleet_home, days)
            if purge:
                preview_purge(fleet_home)
        else:
            run_gc(fleet_home, days)
            if purge:
                run_purge(fleet_home)

    @app.command("task", cls=_TaskHelpCommand)
    def task_cmd(
        task_id: Annotated[str, typer.Argument(help="Task ID.")],
        action: Annotated[
            TaskAction,
            typer.Argument(help="What to print: log | state | result."),
        ],
    ) -> None:
        """Print a task's log, STATE.md, or RESULT.json artifact."""
        run_task_artifact(bootstrap.fleet_home(), task_id, action)

    @job_app.command("view")
    def job_view_cmd(
        job_id: Annotated[str, typer.Argument(help="Job (epic) bead ID.")],
    ) -> None:
        """Show a job's phase, children table, and pending gate question."""
        run_job_view(bootstrap.fleet_home(), job_id)

    @app.command("tail")
    def tail_cmd(
        task_id: Annotated[str, typer.Argument(help="Task ID.")],
        line_count: Annotated[
            int,
            typer.Option("--lines", "-n", help="Number of last rendered lines to show."),
        ] = 30,
        follow: Annotated[
            bool,
            typer.Option("--follow", "-f", help="Follow new events as they arrive."),
        ] = False,
    ) -> None:
        """Print a human-readable, one-line-per-event view of a task's events.jsonl."""
        run_tail(bootstrap.fleet_home(), task_id, line_count, follow)

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
        run_log(bootstrap.fleet_home(), lines)
