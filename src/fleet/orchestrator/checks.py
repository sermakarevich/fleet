"""Startup checks for the supervisor runner: warn or abort before serving.

Called by ``orchestrator/supervisor.py`` before ``on_start``. Each check is
data: a ``StartupCheckSpec`` with a severity and a ``run`` function, so
adding a check means appending one spec to ``DEFAULT_CHECKS``.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

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


ASK_HUMAN_SERVER_IMPORTABLE = StartupCheckSpec(
    name="ask_human_server_importable",
    severity="warn",
    run=ask_human_server_importable,
)

DEFAULT_CHECKS: tuple[StartupCheckSpec, ...] = (ASK_HUMAN_SERVER_IMPORTABLE,)


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
