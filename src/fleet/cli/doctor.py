"""`fleet doctor` — environment preflight: the `bd` binary and its version.

Called directly by operators (`fleet doctor`) to diagnose a supervisor
that never claims beads. Prints the resolved `bd` path (the same
resolution `beads/client.py` uses at runtime) plus `bd --version`,
and exits BACKEND when the binary is missing or broken.
"""

from __future__ import annotations

import subprocess

import typer

from fleet.beads.client import BdError, resolve_bd_bin
from fleet.cli.errors import ExitCode, fail
from fleet.core.limits import BD_TIMEOUT_SEC


def bd_version_line(binary: str) -> str:
    """`bd --version` output for *binary*, or the failure reason."""
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=BD_TIMEOUT_SEC,
        )
    except FileNotFoundError as exc:
        return f"bd version: NOT RUNNABLE — {exc}"
    except subprocess.TimeoutExpired:
        return f"bd version: TIMED OUT after {BD_TIMEOUT_SEC}s"
    except OSError as exc:
        return f"bd version: FAILED — {exc}"
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        return f"bd version: FAILED — {detail}"
    return f"bd version: {result.stdout.strip() or result.stderr.strip() or '(no output)'}"


def register(app: typer.Typer) -> None:
    """Wire `fleet doctor` (environment preflight)."""

    @app.command("doctor")
    def doctor() -> None:
        """Print the resolved `bd` binary path and version."""
        try:
            binary = resolve_bd_bin()
        except BdError as exc:
            fail(f"bd binary missing: {exc}", ExitCode.BACKEND)
        typer.echo(f"bd: {binary}")
        typer.echo(bd_version_line(binary))
