"""The one error path for CLI commands: distinct exit codes.

Called by every ``cli/*`` command module instead of scattering
``typer.echo("Error: ...", err=True)`` + ``raise typer.Exit(1)`` pairs.
``fail`` prints to stderr through ``cli/render.py`` and raises
``typer.Exit`` with the given code, so scripts can tell "not found"
from "bad argument" from "backend down":

- ``ERROR`` (1): generic failure (daemon stopped, misconfigured env).
- ``USAGE`` (2): bad invocation — invalid flag value, malformed
  ``key=value``, non-positive ``--lines``.
- ``NOT_FOUND`` (3): a task, artifact, log, or binary is missing.
- ``BACKEND`` (4): ``bd``, a subprocess, or the network failed.
"""

from __future__ import annotations

from enum import IntEnum
from typing import NoReturn

import typer

from fleet.cli import render


class ExitCode(IntEnum):
    """Process exit code for a CLI failure; OK is 0, failures are 1-4."""

    OK = 0
    ERROR = 1
    USAGE = 2
    NOT_FOUND = 3
    BACKEND = 4


def fail(message: str, code: ExitCode = ExitCode.ERROR) -> NoReturn:
    """Print *message* to stderr and exit with *code*."""
    render.print_error(message.removeprefix("Error: ").removeprefix("error: "))
    raise typer.Exit(int(code))
