"""Tests for orchestrator/checks.py: results, warn vs abort, default check."""

from __future__ import annotations

import pytest

from fleet.orchestrator.checks import (
    DEFAULT_CHECKS,
    CheckResult,
    StartupAborted,
    StartupCheck,
    run_startup_checks,
)
from fleet.orchestrator.state import SupervisorState
from tests.conftest import make_supervisor


class _StubLog:
    def __init__(self) -> None:
        self.infos: list = []
        self.warnings: list = []

    def info(self, event: str, **kwargs) -> None:  # noqa: ANN003
        self.infos.append((event, kwargs))

    def warning(self, event: str, **kwargs) -> None:  # noqa: ANN003
        self.warnings.append((event, kwargs))


def _state(tmp_path, log=None) -> SupervisorState:  # type: ignore[no-untyped-def]
    sup = make_supervisor(tmp_path, services=[], checks=[])
    if log is not None:
        sup.state.log = log
    return sup.state


class _Check:
    def __init__(self, name: str, severity: str, problem: str | None) -> None:
        self.name = name
        self.severity = severity  # type: ignore[assignment]
        self._problem = problem

    def run(self, st: SupervisorState) -> str | None:
        return self._problem


def test_run_startup_checks_returns_one_result_per_check(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """run_startup_checks returns one CheckResult per check, in order."""
    st = _state(tmp_path)
    checks: list[StartupCheck] = [_Check("a", "warn", None), _Check("b", "warn", "disk full")]
    results = run_startup_checks(st, checks)
    assert results == [CheckResult(name="a", problem=None), CheckResult(name="b", problem="disk full")]


def test_warn_failure_does_not_raise(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A failing warn-severity check is logged but does not raise."""
    log = _StubLog()
    st = _state(tmp_path, log=log)
    results = run_startup_checks(st, [_Check("w", "warn", "something off")])
    assert len(results) == 1
    assert any(event == "startup_check" for event, _ in log.warnings)


def test_abort_failure_raises_startup_aborted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A failing abort-severity check raises StartupAborted."""
    st = _state(tmp_path)
    with pytest.raises(StartupAborted):
        run_startup_checks(st, [_Check("must", "abort", "no database")])


def test_abort_check_passing_does_not_raise(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A passing abort-severity check returns normally."""
    st = _state(tmp_path)
    results = run_startup_checks(st, [_Check("must", "abort", None)])
    assert results[0].problem is None


def test_default_checks_not_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """DEFAULT_CHECKS ships at least the ask_human importable check."""
    assert len(DEFAULT_CHECKS) >= 1
    st = _state(tmp_path)
    results = run_startup_checks(st, DEFAULT_CHECKS)
    assert len(results) == len(DEFAULT_CHECKS)
