"""`fleet bd` — passthrough to the `bd` CLI, with create-argv rewriting."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, NoReturn

import typer

from fleet.beads.client import BdClient, BdError
from fleet.beads.create_args import (
    CreateOverrides,
    describe_flags,
    rewrite_create_argv,
    value_flag_names,
)
from fleet.beads.queue import BeadsQueue
from fleet.cli.errors import ExitCode, fail
from fleet.coders import get_coder
from fleet.state import paths as state_paths

#: bd flags (without dashes) that consume the next argv token, so
#: `_first_positional` can skip their values when hunting for the subcommand.
#: Global flags first, then per-command value flags seen in `bd ... --help`.
_BD_VALUE_FLAGS = frozenset(
    {
        "db",
        "directory",
        "actor",
        "dolt-auto-commit",
        "format",
        "assignee",
        "status",
        "priority",
        "type",
        "label",
        "labels",
        "label-any",
        "label-pattern",
        "label-regex",
        "exclude-label",
        "exclude-type",
        "limit",
        "sort",
        "title",
        "description",
        "body",
        "body-file",
        "deps",
        "metadata",
        "metadata-field",
        "has-metadata-key",
        "parent",
        "estimate",
        "due",
        "defer",
        "closed-after",
        "closed-before",
        "created-after",
        "created-before",
        "defer-after",
        "defer-before",
        "due-after",
        "due-before",
        "desc-contains",
        "id",
        "mol-type",
        "repo",
        "context",
        "notes",
        "design",
        "design-file",
        "acceptance",
        "append-notes",
        "external-ref",
        "skills",
        "spec-id",
        "file",
        "graph",
        "event-actor",
        "event-category",
        "event-payload",
        "event-target",
        "waits-for",
        "waits-for-gate",
        "wisp-type",
    }
    | {name.removeprefix("--") for name in value_flag_names()}
)

#: Short flags that consume the next argv token (`-n 5`, `-a someone`).
_SHORT_VALUE_FLAGS = frozenset({"a", "d", "e", "f", "l", "n", "p", "t", "C"})

#: Length of a bare short flag token (`-n`); longer dashed tokens carry values inline.
_SHORT_FLAG_LEN = 2


def _first_positional(args: list[str]) -> str | None:
    """First non-flag positional in a bd argv tail, or None.

    Flags that take values (``--db <path>``, ``-n 5``, ``--flag=value``)
    are skipped together with their values, so a value such as a path is
    never mistaken for the subcommand.
    """
    skip_next = False
    for i, token in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if token == "--":
            return args[i + 1] if i + 1 < len(args) else None
        if token.startswith("--"):
            name, eq, _ = token[2:].partition("=")
            if not eq and name in _BD_VALUE_FLAGS:
                skip_next = True
            continue
        if token.startswith("-") and len(token) > 1:
            if len(token) == _SHORT_FLAG_LEN and token[1] in _SHORT_VALUE_FLAGS:
                skip_next = True
            continue
        return token
    return None


def _has_flag(args: list[str], flag: str) -> bool:
    """True when *flag* appears as `--flag` or `--flag=value`."""
    return any(token == flag or token.startswith(flag + "=") for token in args)


def _wants_help(args: list[str]) -> bool:
    """True when `-h`/`--help` was passed through to bd."""
    return "-h" in args or _has_flag(args, "--help")


def _create_coder_name(args: list[str]) -> str | None:
    """Return the --coder value in a bd create argv tail, if present."""
    for i, token in enumerate(args):
        if token == "--coder" and i + 1 < len(args):
            return args[i + 1]
        if token.startswith("--coder="):
            return token[len("--coder=") :]
    return None


def _validate_create_coder(args: list[str]) -> None:
    """Fail with USAGE when --coder names an unknown coder."""
    coder = _create_coder_name(args)
    if coder is not None:
        try:
            get_coder(coder)  # raises ValueError on an unknown coder name
        except ValueError as exc:
            fail(str(exc), ExitCode.USAGE)


def _passthrough(client: BdClient, argv: list[str]) -> NoReturn:
    """Forward *argv* to bd, echo captured output, and preserve bd's exit code."""
    try:
        result = client.try_run(argv)
    except BdError as exc:
        fail(str(exc), ExitCode.BACKEND)
    if result.stderr:
        typer.echo(result.stderr, err=True, nl=False)
    if result.stdout:
        typer.echo(result.stdout, nl=False)
    raise typer.Exit(result.returncode)


BD_HELP = (
    "Run a `bd` command against the centralized fleet database in $FLEET_HOME.\n\n"
    "For `bd create`/`bd new`, these flags are intercepted and stored as "
    "per-task overrides instead of being forwarded to bd:\n"
    + "\n".join(describe_flags())
    + "\n\n`--cwd <path>` sets the task working directory explicitly instead of "
    "using the shell's current directory.\n\n"
    "Examples:\n\n"
    '  fleet bd create "Fix login redirect" --coder opencode\n'
    "  fleet bd list --status open\n"
    "  fleet bd show fleet-abc"
)


def _run_create(client: BdClient, fleet_home: Path, bd_args: list[str]) -> NoReturn:
    """Run `bd create`/`bd new` through the client, persisting fleet overrides."""
    _validate_create_coder(bd_args)
    try:
        bd_args, overrides = rewrite_create_argv(bd_args, os.getcwd())
    except ValueError as exc:
        fail(str(exc), ExitCode.USAGE)
    user_wants_json = _has_flag(bd_args, "--json")
    user_wants_dry_run = _has_flag(bd_args, "--dry-run")
    if not user_wants_json:
        bd_args.append("--json")
    try:
        result = client.run(bd_args)
    except BdError as exc:
        if exc.stderr:
            typer.echo(exc.stderr, err=True, nl=False)
        raise typer.Exit(
            exc.returncode if exc.returncode is not None else int(ExitCode.BACKEND)
        ) from exc
    task_id, task_title, body = _created_identity(result.stdout)
    if task_id and not user_wants_dry_run:
        _persist_create_overrides(fleet_home, task_id, body, overrides)
    _report_created(result.stdout, task_id, task_title, overrides, user_wants_json)
    raise typer.Exit(result.returncode)


def _created_identity(stdout: str) -> tuple[str | None, str | None, dict[str, Any]]:
    """(id, title, body) of the bead bd just created, or (None, None, {}) when unparseable."""
    try:
        data = json.loads(stdout) if stdout.strip() else None
    except (json.JSONDecodeError, ValueError):
        return None, None, {}
    if not isinstance(data, dict):
        return None, None, {}
    body = data.get("data", data)
    if isinstance(body, list):
        body = body[0] if body else {}
    if not isinstance(body, dict):
        return None, None, {}
    return body.get("id"), body.get("title"), body


def _persist_create_overrides(
    fleet_home: Path, task_id: str, body: dict[str, Any], overrides: CreateOverrides
) -> None:
    """Store invocation cwd plus coder/model/worker overrides on the new task."""
    queue = BeadsQueue(fleet_home)
    queue.set_cwd(task_id, overrides["cwd"])
    queue.set_overrides(
        task_id,
        coder=overrides["coder"],
        model=overrides["model"],
        worker=overrides["worker"],
        isolation=overrides.get("isolation"),
        job_gate=overrides.get("job_gate"),
    )
    # Also snapshot title/description so the UI can show them before the
    # supervisor claims the task (claim is when the full snapshot lands).
    queue.set_bd_fields(task_id, body)


def _report_created(
    stdout: str,
    task_id: str | None,
    task_title: str | None,
    overrides: CreateOverrides,
    user_wants_json: bool,
) -> None:
    """Echo the create result: raw JSON when asked, else a human summary line."""
    if user_wants_json:
        typer.echo(stdout, nl=False)
        return
    if not task_id:
        typer.echo(stdout, nl=False)
        return
    extras = [f"cwd: {overrides['cwd']}"]
    for key in ("coder", "model", "worker"):
        if overrides[key]:
            extras.append(f"{key}: {overrides[key]}")
    typer.echo(f"Created {task_id}: {task_title or ''}  [{', '.join(extras)}]")


def register(app: typer.Typer) -> None:
    @app.command(
        "bd",
        context_settings={
            "allow_extra_args": True,
            "ignore_unknown_options": True,
            # Fleet handles --help itself (forwarded to bd); typer must not swallow it.
            "help_option_names": [],
        },
        help=BD_HELP,
    )
    def bd_passthrough(ctx: typer.Context) -> None:
        """Forward all trailing args to `bd` with cwd=$FLEET_HOME.

        For `bd create` / `bd new`, also captures the task working directory and persists
        it into the task's `task.json` so downstream agents see where to run.
        `--coder`, `--model`, `--worker`, `--cwd`, `--isolation` and `--job-gate`
        are intercepted (not forwarded to bd) and persisted as per-task overrides.

        `--help`/`-h` is forwarded to bd so `fleet bd create --help` shows bd's help.
        """
        fleet_home = state_paths.fleet_home()
        client = BdClient(fleet_home)
        bd_args = list(ctx.args)

        if _wants_help(bd_args):
            _passthrough(client, bd_args)

        sub = _first_positional(bd_args)
        if sub not in ("create", "new"):
            _passthrough(client, bd_args)

        _run_create(client, fleet_home, bd_args)
