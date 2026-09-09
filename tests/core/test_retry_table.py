"""Tests for the retry table shape in core/retry_policy.py.

The behaviour spec lives in test_retry_policy.py (unchanged); these tests
pin the table itself: no two rows share a key, every TaskOutcome is
covered, and decide() really is first-match-wins over RETRY_TABLE.
"""

from __future__ import annotations

from fleet.core.config import RuntimeConfig
from fleet.core.retry_policy import (
    RETRY_TABLE,
    _apply_rule,
    _rule_matches,
    decide,
)
from fleet.core.task import TaskOutcome, TaskOutcomeRecord


def _record(outcome: TaskOutcome, **kwargs) -> TaskOutcomeRecord:
    return TaskOutcomeRecord(outcome=outcome, **kwargs)


def _rule_key(rule) -> tuple:
    match = rule.reason_match
    if match is None:
        reason_key = "*"
    elif isinstance(match, str):
        reason_key = f"={match}"
    elif isinstance(match, tuple):
        reason_key = ("in", *sorted(match))
    else:
        reason_key = f"fn:{match.__name__}"
    outcome_key = rule.outcome.value if rule.outcome is not None else "*"
    return (outcome_key, reason_key, rule.bead_open, rule.action.value)


def test_retry_table_keys_unique() -> None:
    """No two rows match the same key (catches copy-paste duplicate rows)."""
    keys = [_rule_key(rule) for rule in RETRY_TABLE]
    assert len(keys) == len(set(keys)), [key for key in keys if keys.count(key) > 1]


def test_retry_table_covers_every_outcome() -> None:
    """Every TaskOutcome is matched by at least one row on an open bead."""
    grid: dict[TaskOutcome, TaskOutcomeRecord] = {
        TaskOutcome.TERMINAL: _record(TaskOutcome.TERMINAL, reason="t"),
        TaskOutcome.BLOCKED_BY_CODER: _record(TaskOutcome.BLOCKED_BY_CODER, reason="b"),
        TaskOutcome.SUCCESS: _record(TaskOutcome.SUCCESS, close_reason="shipped"),
        TaskOutcome.PARTIAL: _record(TaskOutcome.PARTIAL, reason="p"),
        TaskOutcome.CONTEXT_PRESSURE: _record(TaskOutcome.CONTEXT_PRESSURE),
        TaskOutcome.RATE_LIMIT: _record(TaskOutcome.RATE_LIMIT),
        TaskOutcome.WAITING: _record(TaskOutcome.WAITING, reason="w"),
        TaskOutcome.KILLED: _record(TaskOutcome.KILLED, reason="stalled"),
        TaskOutcome.FAILURE: _record(TaskOutcome.FAILURE, exit_code=1, reason="x"),
    }
    assert set(grid) == set(TaskOutcome)
    for outcome, record in grid.items():
        winners = [r for r in RETRY_TABLE if _rule_matches(r, record, "in_progress")]
        assert winners, outcome


def test_retry_table_first_match_wins() -> None:
    """decide() returns what the first matching row resolves to (action+reason)."""
    config = RuntimeConfig()
    cases = [
        (_record(TaskOutcome.TERMINAL, reason="t"), "in_progress"),
        (_record(TaskOutcome.BLOCKED_BY_CODER, reason="b"), "closed"),
        (_record(TaskOutcome.SUCCESS, close_reason="shipped"), "in_progress"),
        (_record(TaskOutcome.SUCCESS, close_reason="shipped"), "closed"),
        (_record(TaskOutcome.SUCCESS), "in_progress"),
        (_record(TaskOutcome.SUCCESS), "closed"),
        (_record(TaskOutcome.PARTIAL, reason="next"), "in_progress"),
        (_record(TaskOutcome.PARTIAL), "in_progress"),
        (_record(TaskOutcome.PARTIAL, reason="next"), "closed"),
        (_record(TaskOutcome.CONTEXT_PRESSURE), "in_progress"),
        (_record(TaskOutcome.CONTEXT_PRESSURE), "closed"),
        (_record(TaskOutcome.RATE_LIMIT, resets_at=9_999_999_999), "in_progress"),
        (_record(TaskOutcome.RATE_LIMIT), "closed"),
        (_record(TaskOutcome.WAITING, reason="w"), "closed"),
        (_record(TaskOutcome.KILLED, reason="stalled"), "in_progress"),
        (_record(TaskOutcome.KILLED, reason="timeout"), "closed"),
        (_record(TaskOutcome.KILLED, reason="manual"), "in_progress"),
        (_record(TaskOutcome.KILLED, reason="manual"), "closed"),
        (_record(TaskOutcome.FAILURE, exit_code=1, reason="boom"), "in_progress"),
        (_record(TaskOutcome.FAILURE, exit_code=1, reason="boom"), "closed"),
        (_record(TaskOutcome.FAILURE, exit_code=-15, reason="supervisor_shutdown"), "in_progress"),
        (_record(TaskOutcome.FAILURE, exit_code=-15, reason="supervisor_shutdown"), "closed"),
    ]
    for record, bead_status in cases:
        winners = [r for r in RETRY_TABLE if _rule_matches(r, record, bead_status)]
        assert winners, (record, bead_status)
        expected = _apply_rule(winners[0], record, [])
        got = decide(record, [], bead_status, config)
        assert (got.action, got.reason) == (expected.action, expected.reason), (
            record,
            bead_status,
        )
