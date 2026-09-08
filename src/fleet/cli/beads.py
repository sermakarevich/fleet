"""`fleet bd` — passthrough to the `bd` CLI, with create-argv rewriting."""

from __future__ import annotations

import json
import os
import subprocess

import typer

from fleet.beads import client as beads_client
from fleet.beads.create_args import rewrite_create_argv
from fleet.beads.queue import BeadsQueue
from fleet.state.paths import fleet_home


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


def register(app: typer.Typer) -> None:
    @app.command(
        "bd",
        context_settings={
            "allow_extra_args": True,
            "ignore_unknown_options": True,
            "help_option_names": [],
        },
        help=(
            "Run a `bd` command against the centralized fleet database in $FLEET_HOME. "
            "For `bd create`/`bd new`, `--coder`, `--model`, `--worker`, `--cwd`, and "
            "`--isolation` are "
            "intercepted and stored as per-task overrides instead of being forwarded to bd. "
            "`--worker` names the worker family that should run this bead (see "
            "workers/__init__.py::FAMILIES), overriding the type-based default. "
            "`--isolation none` opts out of git worktree isolation for this task. "
            "Use `--cwd <path>` to set the task working directory explicitly instead of "
            "using the shell's current directory — useful when creating tasks from a "
            "centralized location for multiple projects."
        ),
    )
    def bd_passthrough(ctx: typer.Context) -> None:
        """Forward all trailing args verbatim to `bd`, with cwd=$FLEET_HOME.

        For `bd create` / `bd new`, also captures the task working directory and persists
        it into the task's `task.json` so downstream agents see where to run.
        `--coder`, `--model`, `--worker`, `--cwd`, and `--isolation` flags are
        intercepted (not forwarded to bd) and persisted as per-task overrides on task.json.

        `--cwd <path>` overrides the shell's working directory for the task cwd.
        When omitted, the shell cwd at invocation time is used (existing behaviour).
        """
        home = fleet_home()
        bd_args = list(ctx.args)

        sub = _first_positional(bd_args)
        is_create = sub in ("create", "new")

        if not is_create:
            # Simple passthrough: stream stdout/stderr straight to the terminal
            # (no capture) so colors/interactivity behave like a direct `bd` call.
            result = subprocess.run(["bd", *bd_args], cwd=home)
            raise typer.Exit(result.returncode)

        try:
            bd_args, overrides = rewrite_create_argv(bd_args, os.getcwd())
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        coder_override = overrides["coder"]
        model_override = overrides["model"]
        worker_override = overrides["worker"]
        isolation_override = overrides.get("isolation")
        invocation_cwd = overrides["cwd"]

        user_wants_json = "--json" in bd_args
        user_wants_dry_run = "--dry-run" in bd_args

        if not user_wants_json:
            bd_args.append("--json")

        result = beads_client.run(bd_args, cwd=home, check=False)
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
            queue.set_overrides(
                task_id,
                coder=coder_override,
                model=model_override,
                worker=worker_override,
                isolation=isolation_override,
            )
            # Also snapshot title/description so the UI can show them before the
            # supervisor claims the task (claim is when the full snapshot lands).
            queue.set_bd_fields(task_id, body)

        if user_wants_json:
            typer.echo(result.stdout, nl=False)
        elif task_id:
            extras = [f"cwd: {invocation_cwd}"]
            if coder_override:
                extras.append(f"coder: {coder_override}")
            if model_override:
                extras.append(f"model: {model_override}")
            if worker_override:
                extras.append(f"worker: {worker_override}")
            typer.echo(f"Created {task_id}: {task_title or ''}  [{', '.join(extras)}]")
        else:
            typer.echo(result.stdout, nl=False)

        raise typer.Exit(result.returncode)
