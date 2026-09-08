"""Startup checks for the supervisor runner: warn or abort before serving."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from fleet.orchestrator.state import SupervisorState


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one startup check: None problem means ok."""

    name: str
    problem: str | None


class StartupCheck(Protocol):
    """A pre-serve check that warns or aborts the supervisor startup."""

    name: str
    severity: Literal["warn", "abort"]

    def run(self, st: SupervisorState) -> str | None:
        """Return None when ok, else a human-readable problem description."""
        ...


class AskHumanServerImportable:
    """Warn when the bundled ask_human MCP server cannot be imported."""

    name = "ask_human_server_importable"
    severity: Literal["warn"] = "warn"

    def run(self, st: SupervisorState) -> str | None:
        """Return a problem string when the ask_human server module is missing."""
        import importlib.util

        if importlib.util.find_spec("fleet.integrations.ask_human.server") is None:
            return (
                "fleet.integrations.ask_human.server cannot be imported; "
                "workers told to call the ask_human MCP tool will fail"
            )
        return None


class StartupAborted(RuntimeError):
    """Raised when an abort-severity startup check fails."""


DEFAULT_CHECKS: list[StartupCheck] = [AskHumanServerImportable()]


def run_startup_checks(st: SupervisorState, checks: Sequence[StartupCheck]) -> list[CheckResult]:
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
