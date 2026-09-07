from __future__ import annotations

from fleet.core.config import RuntimeConfig
from fleet.core.limits import NOCLOSE_LIMIT, RETRY_LIMIT
from fleet.core.outcome_policy import Action, Counters, decide
from fleet.core.task import TaskOutcome, TaskOutcomeRecord


def _counters(failures: int = 0, noclose: int = 0, stalls: int = 0) -> Counters:
    return Counters(failures=failures, noclose=noclose, stalls=stalls)


def _record(outcome: TaskOutcome, **kwargs) -> TaskOutcomeRecord:
    return TaskOutcomeRecord(outcome=outcome, **kwargs)


# ---------------------------------------------------------------------------
# SUCCESS
# ---------------------------------------------------------------------------


def test_success_bead_already_closed_is_noop() -> None:
    decision = decide(
        _record(TaskOutcome.SUCCESS), _counters(), "closed", RuntimeConfig()
    )
    assert decision.action == Action.NOOP


def test_success_still_in_progress_below_limit_releases_and_increments_noclose() -> None:
    decision = decide(
        _record(TaskOutcome.SUCCESS),
        _counters(noclose=NOCLOSE_LIMIT - 2),
        "in_progress",
        RuntimeConfig(),
    )
    assert decision.action == Action.RELEASE
    assert decision.increment == "noclose"


def test_success_at_noclose_limit_blocks() -> None:
    decision = decide(
        _record(TaskOutcome.SUCCESS),
        _counters(noclose=NOCLOSE_LIMIT - 1),
        "in_progress",
        RuntimeConfig(),
    )
    assert decision.action == Action.BLOCK
    assert decision.increment == "noclose"


# ---------------------------------------------------------------------------
# FAILURE
# ---------------------------------------------------------------------------


def test_failure_bead_already_closed_is_noop() -> None:
    decision = decide(
        _record(TaskOutcome.FAILURE, exit_code=1),
        _counters(),
        "closed",
        RuntimeConfig(),
    )
    assert decision.action == Action.NOOP


def test_failure_below_retry_limit_releases() -> None:
    decision = decide(
        _record(TaskOutcome.FAILURE, exit_code=1),
        _counters(failures=RETRY_LIMIT - 2),
        "in_progress",
        RuntimeConfig(),
    )
    assert decision.action == Action.RELEASE
    assert decision.increment == "failure"


def test_failure_at_retry_limit_blocks() -> None:
    decision = decide(
        _record(TaskOutcome.FAILURE, exit_code=1, reason="crash"),
        _counters(failures=RETRY_LIMIT - 1),
        "in_progress",
        RuntimeConfig(),
    )
    assert decision.action == Action.BLOCK
    assert decision.increment == "failure"
    assert "retry limit" in decision.reason


# ---------------------------------------------------------------------------
# RATE_LIMIT
# ---------------------------------------------------------------------------


def test_rate_limit_releases_with_sleep_sec_set() -> None:
    decision = decide(
        _record(TaskOutcome.RATE_LIMIT), _counters(), "in_progress", RuntimeConfig()
    )
    assert decision.action == Action.RELEASE_AFTER_RATE_LIMIT
    assert decision.sleep_sec is not None
    assert decision.sleep_sec > 0


def test_rate_limit_with_resets_at_uses_later_of_the_two() -> None:
    import time

    resets_at = int(time.time()) + 99999
    decision = decide(
        _record(TaskOutcome.RATE_LIMIT, resets_at=resets_at),
        _counters(),
        "in_progress",
        RuntimeConfig(),
    )
    assert decision.action == Action.RELEASE_AFTER_RATE_LIMIT
    assert decision.sleep_sec is not None
    assert decision.sleep_sec > 90000


# ---------------------------------------------------------------------------
# CONTEXT_PRESSURE
# ---------------------------------------------------------------------------


def test_context_pressure_releases_for_context() -> None:
    decision = decide(
        _record(TaskOutcome.CONTEXT_PRESSURE),
        _counters(),
        "in_progress",
        RuntimeConfig(),
    )
    assert decision.action == Action.RELEASE_FOR_CONTEXT


def test_context_pressure_bead_already_closed_is_noop() -> None:
    decision = decide(
        _record(TaskOutcome.CONTEXT_PRESSURE), _counters(), "closed", RuntimeConfig()
    )
    assert decision.action == Action.NOOP


# ---------------------------------------------------------------------------
# BLOCKED_BY_AGENT
# ---------------------------------------------------------------------------


def test_blocked_by_agent_blocks() -> None:
    decision = decide(
        _record(TaskOutcome.BLOCKED_BY_AGENT),
        _counters(),
        "blocked",
        RuntimeConfig(),
    )
    assert decision.action == Action.BLOCK


# ---------------------------------------------------------------------------
# KILLED
# ---------------------------------------------------------------------------


def test_killed_manual_bead_in_progress_blocks() -> None:
    decision = decide(
        _record(TaskOutcome.KILLED, reason="manual_kill"),
        _counters(),
        "in_progress",
        RuntimeConfig(),
    )
    assert decision.action == Action.BLOCK


def test_killed_manual_bead_already_closed_is_noop() -> None:
    decision = decide(
        _record(TaskOutcome.KILLED, reason="manual_kill"),
        _counters(),
        "closed",
        RuntimeConfig(),
    )
    assert decision.action == Action.NOOP


def test_killed_stall_below_block_after_releases() -> None:
    cfg = RuntimeConfig(stall_block_after=2)
    decision = decide(
        _record(TaskOutcome.KILLED, reason="stalled"),
        _counters(stalls=0),
        "in_progress",
        cfg,
    )
    assert decision.action == Action.RELEASE
    assert decision.increment == "stall"


def test_killed_stall_at_block_after_blocks() -> None:
    cfg = RuntimeConfig(stall_block_after=2)
    decision = decide(
        _record(TaskOutcome.KILLED, reason="stalled"),
        _counters(stalls=1),
        "in_progress",
        cfg,
    )
    assert decision.action == Action.BLOCK
    assert decision.increment == "stall"
