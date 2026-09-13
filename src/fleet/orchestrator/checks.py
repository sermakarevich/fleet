"""Startup checks for the supervisor runner: warn or abort before serving.

Called by ``orchestrator/supervisor.py`` before ``on_start``. Each check is
data: a ``StartupCheckSpec`` with a severity and a ``run`` function, so
adding a check means appending one spec to ``DEFAULT_CHECKS``.
"""

from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from fleet.beads.client import BdError, resolve_bd_bin
from fleet.core.limits import BD_TIMEOUT_SEC

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one startup check: None problem means ok."""

    name: str
    problem: str | None


@dataclass(frozen=True)
class StartupCheckSpec:
    """One pre-serve check: warn or abort the supervisor startup."""

    name: str
    severity: Literal["warn", "abort"]
    run: Callable[[SupervisorState], str | None]


def ask_human_server_importable(st: SupervisorState) -> str | None:
    """Return a problem string when the ask_human server module is missing."""
    _ = st
    if importlib.util.find_spec("fleet.integrations.ask_human.server") is None:
        return (
            "fleet.integrations.ask_human.server cannot be imported; "
            "workers told to call the ask_human MCP tool will fail"
        )
    return None


class StartupAborted(RuntimeError):
    """Raised when an abort-severity startup check fails."""


def check_bd_binary() -> str | None:
    """Problem string when the `bd` binary is missing or `bd --version` fails."""
    try:
        binary = resolve_bd_bin()
    except BdError as exc:
        return str(exc)
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=BD_TIMEOUT_SEC,
        )
    except FileNotFoundError as exc:
        return f"bd executable not found at {binary}: {exc}"
    except subprocess.TimeoutExpired:
        return f"bd --version timed out after {BD_TIMEOUT_SEC}s ({binary})"
    except OSError as exc:
        return f"bd --version failed ({binary}): {exc}"
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        return f"bd --version failed ({binary}): {detail}"
    return None


def bd_binary_found(st: SupervisorState) -> str | None:
    """Abort-severity wrapper: the supervisor cannot claim beads without `bd`."""
    _ = st
    return check_bd_binary()


ASK_HUMAN_SERVER_IMPORTABLE = StartupCheckSpec(
    name="ask_human_server_importable",
    severity="warn",
    run=ask_human_server_importable,
)

BD_BINARY_FOUND = StartupCheckSpec(
    name="bd_binary_found",
    severity="abort",
    run=bd_binary_found,
)

DEFAULT_CHECKS: tuple[StartupCheckSpec, ...] = (BD_BINARY_FOUND, ASK_HUMAN_SERVER_IMPORTABLE)


def run_startup_checks(
    st: SupervisorState, checks: Sequence[StartupCheckSpec]
) -> list[CheckResult]:
    """Run every check, log each result, abort when an abort check fails."""
    results: list[CheckResult] = []
    for check in checks:
        problem = check.run(st)
        results.append(CheckResult(name=check.name, problem=problem))
        if problem is None:
            st.log.info("startup_check", name=check.name, ok=True)
        else:
            st.log.warning("startup_check", name=check.name, ok=False, problem=problem)
            if check.severity == "abort":
                raise StartupAborted(f"startup check {check.name} failed: {problem}")
    return results
