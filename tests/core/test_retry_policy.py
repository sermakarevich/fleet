"""Tests for core/retry_policy.py. Mirrors the source path."""

from __future__ import annotations

import time

import pytest

from fleet.core.config import RuntimeConfig
from fleet.core.retry_policy import (
    CONTEXT_MAX_ROUNDS,
    FAILURE_MAX_ROUNDS,
    NOCLOSE_MAX_ROUNDS,
    PARTIAL_MAX_ROUNDS,
    STALL_MAX_ROUNDS,
    Action,
    decide,
    rounds_for_history,
)
from fleet.core.task import TaskOutcome, TaskOutcomeRecord


def _record(outcome: TaskOutcome, **kwargs) -> TaskOutcomeRecord:
    return TaskOutcomeRecord(outcome=outcome, **kwargs)


def _hist(*outcomes: tuple[str, str | None]) -> list[dict]:
    """Build history rows from (outcome, reason) pairs."""
    return [
        {"n": i + 1, "outcome": o, "reason": r, "action": "release"}
        for i, (o, r) in enumerate(outcomes)
    ]


def test_every_outcome_has_a_row() -> None:
    """Property-style: decide() never raises ValueError for any TaskOutcome."""
    config = RuntimeConfig()
    records = {
        TaskOutcome.SUCCESS: _record(TaskOutcome.SUCCESS),
        TaskOutcome.FAILURE: _record(TaskOutcome.FAILURE, exit_code=1, reason="x"),
        TaskOutcome.RATE_LIMIT: _record(TaskOutcome.RATE_LIMIT),
        TaskOutcome.CONTEXT_PRESSURE: _record(TaskOutcome.CONTEXT_PRESSURE),
        TaskOutcome.BLOCKED_BY_CODER: _record(TaskOutcome.BLOCKED_BY_CODER, reason="x"),
        TaskOutcome.KILLED: _record(TaskOutcome.KILLED, reason="manual_kill"),
        TaskOutcome.PARTIAL: _record(TaskOutcome.PARTIAL, reason="next"),
        TaskOutcome.TERMINAL: _record(TaskOutcome.TERMINAL, reason="terminal: bad coder"),
    }
    for outcome, record in records.items():
        decision = decide(record, [], "in_progress", config)
        assert isinstance(decision.action, Action), outcome


def test_failure_retries_then_blocks() -> None:
    config = RuntimeConfig()
    rec = _record(TaskOutcome.FAILURE, exit_code=1, reason="boom")
    d1 = decide(rec, [], "in_progress", config)
    assert d1.action == Action.RELEASE
    assert 60 <= (d1.wait_sec or 0) <= 90
    d2 = decide(rec, _hist(("failure", "boom")), "in_progress", config)
    assert d2.action == Action.RELEASE
    assert 300 <= (d2.wait_sec or 0) <= 330
    d3 = decide(rec, _hist(("failure", "boom"), ("failure", "boom")), "in_progress", config)
    assert d3.action == Action.BLOCK


def test_failure_streak_resets_on_different_ending() -> None:
    config = RuntimeConfig()
    rec = _record(TaskOutcome.FAILURE, exit_code=1)
    history = _hist(("failure", "x"), ("failure", "x"), ("success", None))
    # Trailing SUCCESS-close? action release + outcome success counts as noclose,
    # which breaks the failure streak → rounds back to 1 → RELEASE.
    d = decide(rec, history, "in_progress", config)
    assert d.action == Action.RELEASE


def test_stall_timeout_share_one_ladder() -> None:
    config = RuntimeConfig()
    stalled = _record(TaskOutcome.KILLED, reason="stalled")
    timeout = _record(TaskOutcome.KILLED, reason="timeout")
    assert decide(stalled, [], "in_progress", config).action == Action.RELEASE
    # One prior stall + current timeout = round 2 → BLOCK.
    got = decide(timeout, _hist(("killed", "stalled")), "in_progress", config)
    assert got.action == Action.BLOCK
    assert STALL_MAX_ROUNDS == 2


def test_killed_manual_blocks() -> None:
    d = decide(
        _record(TaskOutcome.KILLED, reason="manual_kill"), [], "in_progress", RuntimeConfig()
    )
    assert d.action == Action.BLOCK
    assert "manually interrupted" in d.reason


def test_rate_limit_waits_not_counted() -> None:
    config = RuntimeConfig()
    rec = _record(TaskOutcome.RATE_LIMIT)
    d = decide(rec, [], "in_progress", config)
    assert d.action == Action.RELEASE
    assert (d.wait_sec or 0) >= 300
    # Even a long rate-limit streak never blocks.
    history = _hist(*[("rate_limit", None)] * 10)
    assert decide(rec, history, "in_progress", config).action == Action.RELEASE


def test_rate_limit_respects_resets_at() -> None:
    resets_at = int(time.time()) + 99999
    d = decide(
        _record(TaskOutcome.RATE_LIMIT, resets_at=resets_at), [], "in_progress", RuntimeConfig()
    )
    assert (d.wait_sec or 0) >= 90000


def test_context_pressure_blocks_with_split_reason() -> None:
    config = RuntimeConfig()
    rec = _record(TaskOutcome.CONTEXT_PRESSURE)
    assert decide(rec, [], "in_progress", config).action == Action.RELEASE
    history = _hist(*[("context_pressure", None)] * (CONTEXT_MAX_ROUNDS - 1))
    d = decide(rec, history, "in_progress", config)
    assert d.action == Action.BLOCK
    assert "split it" in d.reason


def test_partial_ladder_is_five() -> None:
    config = RuntimeConfig()
    rec = _record(TaskOutcome.PARTIAL, reason="next step")
    assert decide(rec, [], "in_progress", config).action == Action.RELEASE
    history = _hist(*[("partial", "s")] * (PARTIAL_MAX_ROUNDS - 1))
    assert decide(rec, history, "in_progress", config).action == Action.BLOCK


def test_success_close_vs_noclose() -> None:
    config = RuntimeConfig()
    done = _record(TaskOutcome.SUCCESS, close_reason="shipped")
    d = decide(done, [], "in_progress", config)
    assert d.action == Action.CLOSE
    plain = _record(TaskOutcome.SUCCESS)
    assert decide(plain, [], "in_progress", config).action == Action.RELEASE
    history = _hist(*[("success", None)] * (NOCLOSE_MAX_ROUNDS - 1))
    # History SUCCESS rows with action=release count as noclose rounds.
    assert decide(plain, history, "in_progress", config).action == Action.BLOCK
    assert NOCLOSE_MAX_ROUNDS == 3


def test_blocked_by_coder_and_terminal_always_block() -> None:
    config = RuntimeConfig()
    assert (
        decide(_record(TaskOutcome.BLOCKED_BY_CODER, reason="creds"), [], "open", config).action
        == Action.BLOCK
    )
    assert (
        decide(
            _record(TaskOutcome.TERMINAL, reason="terminal: bad coder"), [], "open", config
        ).action
        == Action.BLOCK
    )


def test_noop_when_bead_not_in_progress() -> None:
    config = RuntimeConfig()
    assert decide(_record(TaskOutcome.SUCCESS), [], "closed", config).action == Action.NOOP
    assert (
        decide(_record(TaskOutcome.FAILURE, exit_code=1), [], "closed", config).action
        == Action.NOOP
    )


def test_rounds_for_history_counts_trailing_streaks() -> None:
    history = _hist(("failure", "x"), ("failure", "x"), ("success", None))
    rounds = rounds_for_history(history)
    assert rounds["noclose"] == 1
    assert rounds["failure"] == 0
    assert (
        decide(
            _record(TaskOutcome.FAILURE, exit_code=1), history, "in_progress", RuntimeConfig()
        ).action
        == Action.RELEASE
    )


def test_unhandled_outcome_raises() -> None:
    # Force an unknown outcome via a fake record type.
    rec = _record(TaskOutcome.FAILURE, exit_code=1)
    object.__setattr__(rec, "outcome", "bogus")
    with pytest.raises(ValueError):
        decide(rec, [], "in_progress", RuntimeConfig())


def test_failure_constants_match_table() -> None:
    assert FAILURE_MAX_ROUNDS == 3


def test_supervisor_shutdown_requeues_and_never_counts() -> None:
    """A shutdown-killed attempt is released immediately, and shutdown rows in
    history neither count toward nor break the failure streak."""
    config = RuntimeConfig()
    rec = _record(TaskOutcome.FAILURE, exit_code=-15, reason="supervisor_shutdown")
    d = decide(rec, _hist(("failure", "boom"), ("failure", "boom")), "in_progress", config)
    assert d.action == Action.RELEASE
    assert (d.wait_sec or 0) == 0

    # Two real failures, then a shutdown: the next real failure is round 3 -> BLOCK.
    real = _record(TaskOutcome.FAILURE, exit_code=1, reason="boom")
    history = _hist(("failure", "boom"), ("failure", "boom"), ("failure", "supervisor_shutdown"))
    assert decide(real, history, "in_progress", config).action == Action.BLOCK
    # A shutdown alone in history is not a round either.
    history = _hist(("failure", "supervisor_shutdown"))
    d = decide(real, history, "in_progress", config)
    assert d.action == Action.RELEASE
    assert 60 <= (d.wait_sec or 0) <= 90


def test_unblock_row_resets_failure_streak() -> None:
    """The "unblocked" row appended by an operator unblock ends the streak."""
    config = RuntimeConfig()
    real = _record(TaskOutcome.FAILURE, exit_code=1, reason="boom")
    history = _hist(("failure", "boom"), ("failure", "boom"), ("unblocked", "operator"))
    d = decide(real, history, "in_progress", config)
    assert d.action == Action.RELEASE
    assert 60 <= (d.wait_sec or 0) <= 90
