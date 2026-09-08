"""Tests for workers/session/classify.py: the pure exit-outcome table."""

from __future__ import annotations

from fleet.core.task import TaskOutcome, TaskOutcomeRecord
from fleet.workers.session.classify import classify_exit


def test_verdict_wins() -> None:
    verdict = TaskOutcomeRecord(outcome=TaskOutcome.RATE_LIMIT, exit_code=-15, reason="r")
    record = classify_exit(0, verdict=verdict, killed=True, cancelled=True)
    assert record == verdict


def test_killed_beats_cancelled_and_exit_code() -> None:
    record = classify_exit(0, killed=True, kill_reason="stalled", cancelled=True)
    assert record.outcome == TaskOutcome.KILLED
    assert record.reason == "stalled"
    assert record.exit_code == 0


def test_cancelled_means_shutdown_failure() -> None:
    record = classify_exit(-15, cancelled=True)
    assert record.outcome == TaskOutcome.FAILURE
    assert record.reason == "supervisor_shutdown"


def test_clean_exit_is_success() -> None:
    record = classify_exit(0)
    assert record.outcome == TaskOutcome.SUCCESS
    assert record.reason == ""


def test_stderr_overflow_is_context_pressure() -> None:
    record = classify_exit(1, stderr_tail="Error: prompt is too long\n")
    assert record.outcome == TaskOutcome.CONTEXT_PRESSURE
    assert record.reason == "cli reported context overflow"
    assert record.stderr_tail is not None


def test_plain_failure_keeps_tail() -> None:
    record = classify_exit(1, stderr_tail="something went wrong\n")
    assert record.outcome == TaskOutcome.FAILURE
    assert record.reason == "subprocess exited with rc=1"
    assert record.stderr_tail == "something went wrong\n"


def test_failure_without_tail() -> None:
    record = classify_exit(2)
    assert record.outcome == TaskOutcome.FAILURE
    assert record.stderr_tail is None
