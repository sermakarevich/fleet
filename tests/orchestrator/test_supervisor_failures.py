"""Tests for failure/rate-limit outcome policy (unit under test: orchestrator reap policy)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fleet.core.retry_policy import FAILURE_MAX_ROUNDS
from fleet.core.task import TaskOutcome
from tests.orchestrator.conftest import (
    StubQueue,
    _handle,
    _history_outcomes,
    _make_supervisor,
    _outcome,
    _task,
)


def test_failure_under_limit_calls_release(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1, reason="rc=1"))
    assert len(queue.released) == 1
    assert "rc=1" in queue.released[0][1]


def test_failure_under_limit_calls_comment(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.comments) == 1


def test_failure_under_limit_no_set_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.blocked) == 0


def test_failure_blocks_on_third_consecutive_round(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(FAILURE_MAX_ROUNDS - 1):
        _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.blocked) == 0
    _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.blocked) == 1


def test_failure_third_round_no_release(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(FAILURE_MAX_ROUNDS):
        _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert len(queue.released) == FAILURE_MAX_ROUNDS - 1


def test_failure_exhausted_reason_in_blocked(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    for _ in range(FAILURE_MAX_ROUNDS):
        _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1, reason="crash"))
    assert "retry limit" in queue.blocked[0][1]


def test_failure_history_journaled(tmp_path: Path) -> None:
    queue = StubQueue(status="in_progress")
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.FAILURE, exit_code=1))
    assert _history_outcomes(tmp_path) == ["failure"]


def test_rate_limit_sets_paused_until(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("fleet.core.retry_policy.RATE_LIMIT_DEFAULT_SLEEP_SEC", 300)
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue)
    before = datetime.now(tz=UTC)
    _handle(s, _task(), _outcome(TaskOutcome.RATE_LIMIT, resets_at=None))
    assert s.state.paused_until is not None
    assert s.state.paused_until > before


def test_rate_limit_paused_until_uses_resets_at_when_later(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("fleet.core.retry_policy.RATE_LIMIT_DEFAULT_SLEEP_SEC", 5)
    queue = StubQueue()
    far_future = int(datetime.now(tz=UTC).timestamp()) + 9999
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.RATE_LIMIT, resets_at=far_future))
    assert s.state.paused_until is not None
    # paused_until should be >= far_future (resets_at wins)
    assert s.state.paused_until.timestamp() >= far_future


def test_rate_limit_releases_with_delay(tmp_path: Path) -> None:
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.RATE_LIMIT))
    assert len(queue.released) == 1
    assert len(queue.blocked) == 0


def test_rate_limit_claim_loop_skips_while_paused(tmp_path: Path, monkeypatch) -> None:
    """After a RATE_LIMIT outcome, _paused_until is set and claim loop skips spawning."""
    monkeypatch.setattr("fleet.core.retry_policy.RATE_LIMIT_DEFAULT_SLEEP_SEC", 300)
    queue = StubQueue()
    s = _make_supervisor(tmp_path, queue)
    _handle(s, _task(), _outcome(TaskOutcome.RATE_LIMIT))
    # Confirm paused_until is in the future
    assert s.state.paused_until > datetime.now(tz=UTC)
