"""Tests for orchestrator/checks.py: results, warn vs abort, default check."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from fleet.beads.client import BdError
from fleet.orchestrator.checks import (
    DEFAULT_CHECKS,
    CheckResult,
    StartupAborted,
    StartupCheckSpec,
    check_bd_binary,
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


def _check(name: str, severity: str, problem: str | None) -> StartupCheckSpec:
    return StartupCheckSpec(name=name, severity=severity, run=lambda st: problem)  # type: ignore[arg-type]


def test_run_startup_checks_returns_one_result_per_check(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """run_startup_checks returns one CheckResult per check, in order."""
    st = _state(tmp_path)
    checks = [_check("a", "warn", None), _check("b", "warn", "disk full")]
    results = run_startup_checks(st, checks)
    assert results == [
        CheckResult(name="a", problem=None),
        CheckResult(name="b", problem="disk full"),
    ]


def test_warn_failure_does_not_raise(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A failing warn-severity check is logged but does not raise."""
    log = _StubLog()
    st = _state(tmp_path, log=log)
    results = run_startup_checks(st, [_check("w", "warn", "something off")])
    assert len(results) == 1
    assert any(event == "startup_check" for event, _ in log.warnings)


def test_abort_failure_raises_startup_aborted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A failing abort-severity check raises StartupAborted."""
    st = _state(tmp_path)
    with pytest.raises(StartupAborted):
        run_startup_checks(st, [_check("must", "abort", "no database")])


def test_abort_check_passing_does_not_raise(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A passing abort-severity check returns normally."""
    st = _state(tmp_path)
    results = run_startup_checks(st, [_check("must", "abort", None)])
    assert results[0].problem is None


def test_default_checks_not_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """DEFAULT_CHECKS ships at least the ask_human importable check."""
    assert len(DEFAULT_CHECKS) >= 1
    st = _state(tmp_path)
    results = run_startup_checks(st, DEFAULT_CHECKS)
    assert len(results) == len(DEFAULT_CHECKS)


def test_bd_binary_found_check_present_and_abort(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """DEFAULT_CHECKS carries an abort-severity `bd_binary_found` check."""
    names = {check.name: check.severity for check in DEFAULT_CHECKS}
    assert names.get("bd_binary_found") == "abort"


def test_missing_bd_aborts_startup(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """No `bd` anywhere -> the abort check fails and startup raises."""
    st = _state(tmp_path)
    only_bd = [check for check in DEFAULT_CHECKS if check.name == "bd_binary_found"]
    assert len(only_bd) == 1
    with (
        patch(
            "fleet.orchestrator.checks.resolve_bd_bin",
            side_effect=BdError("bd executable not found (checked FLEET_BD_BIN env, PATH)"),
        ),
        pytest.raises(StartupAborted, match="bd_binary_found"),
    ):
        run_startup_checks(st, only_bd)


def test_bd_check_reports_problem_on_launchd_path(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """launchd's minimal PATH with no fallback `bd` -> a clear problem string."""
    monkeypatch.delenv("FLEET_BD_BIN", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    monkeypatch.setenv("HOME", "/nonexistent-home-for-bd-test")
    problem = check_bd_binary()
    assert problem is not None
    assert "bd" in problem


def test_bd_check_passes_when_version_succeeds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A working `bd --version` -> the abort check passes."""
    st = _state(tmp_path)
    only_bd = [check for check in DEFAULT_CHECKS if check.name == "bd_binary_found"]
    completed = subprocess.CompletedProcess(
        args=["bd", "--version"], returncode=0, stdout="bd 0.1.0", stderr=""
    )
    with (
        patch("fleet.orchestrator.checks.resolve_bd_bin", return_value="/fake/bd"),
        patch("fleet.orchestrator.checks.subprocess.run", return_value=completed),
        patch("fleet.orchestrator.checks.BD_TIMEOUT_SEC", 5),
    ):
        results = run_startup_checks(st, only_bd)
    assert results[0].problem is None
