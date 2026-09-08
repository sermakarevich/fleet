"""Task-management commands: init, ready, show, tasks, task, kill, gc, tail, log."""

from __future__ import annotations

import sys
import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from typer.core import TyperCommand

from fleet.beads.client import BeadsError
from fleet.beads.queue import BeadsQueue
from fleet.cli.format import render_tasks_table
from fleet.core.config import load as load_config
from fleet.core.limits import LOG_ROOT
from fleet.observability import tailview
from fleet.state.archive import gc_tasks
from fleet.state.attempts import latest_attempt_dir
from fleet.state.paths import fleet_home
from fleet.state.paths import task_dir as _task_dir
from fleet.state.tail import read_new_bytes


class TaskAction(StrEnum):
    log = "log"
    plan = "plan"
    handoff = "handoff"
    knowledge = "knowledge"
    result = "result"


def _resolve_log_dir() -> Path:
    log_root = Path(LOG_ROOT)
    if not log_root.is_absolute():
        log_root = fleet_home() / log_root
    return log_root


def _print_file_or_exit(path: Path, missing_msg: str) -> None:
    if not path.exists():
        typer.echo(missing_msg, err=True)
        raise typer.Exit(1)
    sys.stdout.write(path.read_text(encoding="utf-8"))


def _running_tasks_help_text() -> str:
    """Build the dynamic `--help` epilog for `fleet task`.

    Lists currently running tasks so users running `fleet task --help` can
    immediately see which task IDs are valid arguments, plus the effective
    coder/model for each (per-task override or current config default).
    """
    header = "Currently running tasks (run `fleet tasks` for full details):"
    try:
        tasks = BeadsQueue(fleet_home()).list_in_progress(limit=50)
    except BeadsError:
        return f"{header}\n\n  (unable to query bd queue)"
    if not tasks:
        return f"{header}\n\n  (none)"
    try:
        cfg = load_config(fleet_home() / "runtime.toml")
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
        rows.append(f"  {t.id:<{width}}[{coder}/{model}]  {t.title}")
    # Double newlines preserve line breaks through typer's rich epilog renderer,
    # which collapses single newlines within a paragraph to spaces.
    return header + "\n\n" + "\n\n".join(rows)


class _TaskHelpCommand(TyperCommand):
    """`fleet task` command whose --help appends a list of running tasks."""

    def format_help(self, ctx, formatter):  # type: ignore[override]
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
                display = rendered[-buffer_n:] if buffer_n > 0 else rendered
                for line in display:
                    typer.echo(line)
    except KeyboardInterrupt:
        sys.exit(0)


def register(app: typer.Typer) -> None:
    @app.command()
    def init(
        force: Annotated[
            bool, typer.Option("--force", help="Re-init even if .beads already exists.")
        ] = False,
    ) -> None:
        """Initialize the fleet home directory (beads + defaults)."""
        from fleet.beads import client as beads_client

        home = fleet_home()
        home.mkdir(parents=True, exist_ok=True)

        beads_dir = home / ".beads"
        if force or not beads_dir.exists():
            try:
                beads_client.run(["init"], cwd=home)
            except BeadsError as exc:
                if "already" not in str(exc).lower():
                    typer.echo(f"bd init failed: {exc}", err=True)
                    raise typer.Exit(1) from exc

        load_config(home / "runtime.toml")  # writes defaults if missing
        (home / "tasks").mkdir(exist_ok=True)
        typer.echo(f"Fleet home initialized at {home}")

    @app.command()
    def ready(
        limit: Annotated[
            int, typer.Option("--limit", "-n", help="Maximum tasks to list.")
        ] = 50,
    ) -> None:
        """List ready tasks."""
        q = BeadsQueue(fleet_home())
        try:
            tasks = q.list_ready(limit=limit)
        except BeadsError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
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
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit raw bd show JSON envelope.")
        ] = False,
    ) -> None:
        """Show one task."""
        from fleet.beads import client as beads_client

        root = fleet_home()
        if json_output:
            result = beads_client.run(["show", task_id, "--json"], cwd=root, check=False)
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
            raise typer.Exit(1) from exc
        cfg = load_config(root / "runtime.toml")
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

    @app.command("kill")
    def kill_cmd(
        task_id: Annotated[str, typer.Argument(help="Task ID to kill.")],
    ) -> None:
        """Interrupt a running task (supervisor terminates it and marks it manually interrupted)."""
        home = fleet_home()
        task_dir = _task_dir(home, task_id)
        if not (task_dir / "task.json").exists():
            typer.echo(f"Task {task_id} not found.", err=True)
            raise typer.Exit(1)
        (task_dir / ".kill").touch()
        typer.echo(f"Kill signal sent for task {task_id}.")

    @app.command("tasks")
    def tasks_cmd(
        limit: Annotated[
            int, typer.Option("--limit", "-n", help="Maximum tasks to list.")
        ] = 50,
        ignored: Annotated[
            bool,
            typer.Option("--ignored", help="List triage-ignored blocked tasks."),
        ] = False,
    ) -> None:
        """List currently running tasks with start time, elapsed, idle, context usage, events."""
        home = fleet_home()
        q = BeadsQueue(home)
        if ignored:
            try:
                rows = q.list_ignored(limit=limit)
            except BeadsError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(1) from exc
            if not rows:
                typer.echo("No ignored tasks.")
                return
            width = max(len(t.id) for t, _ in rows) + 2
            for t, until in rows:
                typer.echo(f"{t.id:<{width}}{t.title}  [ignored until {until}]")
            return
        try:
            tasks = q.list_in_progress(limit=limit)
        except BeadsError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        if not tasks:
            typer.echo("No running tasks.")
            return

        cfg = load_config(home / "runtime.toml")
        table = render_tasks_table(tasks, home, cfg.coder, cfg.model)
        Console(soft_wrap=False).print(table)

    @app.command("gc")
    def gc_cmd(
        days: Annotated[
            int, typer.Option("--days", help="Archive closed tasks older than N days.")
        ] = 30,
        dry_run: Annotated[
            bool, typer.Option("--dry-run", help="List what would be archived without moving.")
        ] = False,
    ) -> None:
        """Archive closed task directories older than N days to archive/tasks."""
        home = fleet_home()
        result = gc_tasks(home, days, dry_run)
        mb = result.bytes_moved / (1024 * 1024)
        archive_dir = home / "archive" / "tasks"
        prefix = "dry-run: " if dry_run else ""
        typer.echo(
            f"{prefix}archived {len(result.archived)} task dirs "
            f"({mb:.1f} MB) -> {archive_dir}; skipped {result.skipped}"
        )

    @app.command("task", cls=_TaskHelpCommand)
    def task_cmd(
        task_id: Annotated[str, typer.Argument(help="Task ID.")],
        action: Annotated[
            TaskAction,
            typer.Argument(help="What to print: log | plan | handoff | knowledge | result."),
        ],
    ) -> None:
        """Print a task's log, PLAN, HANDOFF, KNOWLEDGE, or RESULT artifact."""
        task_dir = _task_dir(fleet_home(), task_id)
        if not task_dir.exists():
            typer.echo(f"No task directory at {task_dir}", err=True)
            raise typer.Exit(1)

        if action is TaskAction.plan:
            plan_path = task_dir / "artifacts" / "PLAN.md"
            if not plan_path.exists():
                # Fall back to the pre-worker-1 combined file for old tasks.
                plan_path = task_dir / "artifacts" / "PLAN_AND_STATUS.md"
            _print_file_or_exit(plan_path, f"No PLAN.md for task {task_id}")
            return

        if action is TaskAction.handoff:
            _print_file_or_exit(
                task_dir / "artifacts" / "HANDOFF.md",
                f"No HANDOFF.md for task {task_id}",
            )
            return

        if action is TaskAction.knowledge:
            _print_file_or_exit(
                task_dir / "artifacts" / "KNOWLEDGE.md",
                f"No KNOWLEDGE.md for task {task_id}",
            )
            return

        if action is TaskAction.result:
            _print_file_or_exit(
                task_dir / "artifacts" / "RESULT.json",
                f"No RESULT.json for task {task_id}",
            )
            return

        # action == TaskAction.log
        attempt_dir = latest_attempt_dir(task_dir)
        log_path = attempt_dir / "log.jsonl" if attempt_dir is not None else None
        if log_path is None or not log_path.exists():
            typer.echo(f"No log for task {task_id}", err=True)
            raise typer.Exit(1)
        sys.stdout.write(log_path.read_text(encoding="utf-8"))

    @app.command("tail")
    def tail_cmd(
        task_id: Annotated[str, typer.Argument(help="Task ID.")],
        n: Annotated[
            int,
            typer.Option("--lines", "-n", help="Number of last rendered lines to show."),
        ] = 30,
        follow: Annotated[
            bool,
            typer.Option("--follow", "-f", help="Follow new events as they arrive."),
        ] = False,
    ) -> None:
        """Print a human-readable, one-line-per-event view of a task's events.jsonl."""
        from fleet.serve.stats import task_runtime_stats

        home = fleet_home()
        task_dir_path = _task_dir(home, task_id)

        if not task_dir_path.exists():
            typer.echo(f"No task directory for {task_id} at {task_dir_path}", err=True)
            raise typer.Exit(1)

        attempt_dir = latest_attempt_dir(task_dir_path)
        events_path = (
            attempt_dir / "events.jsonl"
            if attempt_dir is not None
            else task_dir_path / "attempts" / "1" / "events.jsonl"
        )

        # If events.jsonl does not exist yet, still print header; --follow will wait.
        if not events_path.exists():
            typer.echo(f"{task_id}  events=0  last_event=-  context_tokens=-")
            typer.echo("(events.jsonl does not exist yet)")
            if not follow:
                return
            while not events_path.exists():
                time.sleep(1)

        stats = task_runtime_stats(task_id)
        last_event_str = (
            stats.last_event_at.strftime("%H:%M:%S")
            if stats.last_event_at is not None
            else "-"
        )
        ctx = stats.context_tokens if stats.context_tokens is not None else "-"
        typer.echo(
            f"{task_id}  events={stats.events}  last_event={last_event_str}  context_tokens={ctx}"
        )

        try:
            raw_lines = events_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            typer.echo(f"Error: cannot read {events_path}", err=True)
            raise typer.Exit(1) from exc

        rendered = tailview.render_lines(raw_lines)

        if not rendered:
            typer.echo("(no renderable events)")
            return

        display = rendered[-n:] if n > 0 else rendered
        for line in display:
            typer.echo(line)

        if follow:
            _tail_follow(events_path, n)

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
