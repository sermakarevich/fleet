"""Tests for the pure triage proposal rules (core/triage_policy.py)."""

from datetime import UTC, datetime, timedelta

from fleet.core.triage_policy import (
    CLOSE,
    COMMON_OPTIONS,
    EDIT_RETRY,
    IGNORE_24H,
    IGNORE_FOREVER,
    RETRY_OPUS,
    RETRY_SAME,
    digest_text,
    ignore_active,
    propose,
)


def _attempts(**overrides):
    base = {"rounds": {}, "rate_limited": False, "stderr_tail": None}
    base.update(overrides)
    return base


def test_default_proposal_offers_common_options():
    p = propose({"id": "t1", "title": "T"}, _attempts(), None, "failed 1 time")
    assert p.options == COMMON_OPTIONS
    assert "t1" in p.text


def test_rate_limit_suggests_switch():
    p = propose(
        {"id": "t1", "title": "T"},
        _attempts(rate_limited=True),
        None,
        "rate limited",
    )
    assert "rate limit" in p.text.lower()
    assert RETRY_OPUS in p.options


def test_stall_rounds_suggest_stronger_model():
    p = propose(
        {"id": "t1", "title": "T"},
        _attempts(rounds={"stall": 2}),
        None,
        "stalled 2 times",
    )
    assert "stronger model" in p.text
    assert p.options == COMMON_OPTIONS


def test_context_exhausted_suggests_split():
    p = propose(
        {"id": "t1", "title": "T"},
        _attempts(rounds={"context": 3}),
        None,
        "too large for one worker",
    )
    assert "split" in p.text
    assert p.options == COMMON_OPTIONS


def test_result_blocked_quotes_report_verbatim():
    result = {
        "status": "blocked",
        "blocked_reason": "need API key",
        "open_questions": ["which env?"],
    }
    p = propose({"id": "t1", "title": "T"}, _attempts(), result, "agent blocked")
    assert "need API key" in p.text
    assert "which env?" in p.text
    assert p.options == COMMON_OPTIONS


def test_failure_exhausted_shows_stderr_tail():
    p = propose(
        {"id": "t1", "title": "T"},
        _attempts(rounds={"failure": 3}, stderr_tail="boom\ntraceback"),
        None,
        "retry limit exhausted",
    )
    assert "boom" in p.text
    assert RETRY_SAME in p.options and RETRY_OPUS in p.options
    assert EDIT_RETRY in p.options and CLOSE in p.options
    assert IGNORE_24H in p.options and IGNORE_FOREVER in p.options


def test_rule_priority_rate_limit_first():
    p = propose(
        {"id": "t1", "title": "T"},
        _attempts(rounds={"stall": 2, "failure": 3}, rate_limited=True),
        None,
        "blocked",
    )
    assert "rate limit" in p.text.lower()


def test_ignore_active():
    assert ignore_active("forever")
    assert ignore_active("FOREVER")
    future = (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat()
    assert ignore_active(future)
    past = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
    assert not ignore_active(past)
    assert not ignore_active(None)
    assert not ignore_active("")
    assert not ignore_active("not-a-date")


def test_digest_text_lists_tasks():
    text = digest_text(
        [
            {"id": "a", "title": "A", "blocked_reason": "r1"},
            {"id": "b", "title": "B", "blocked_reason": "r2"},
        ]
    )
    assert "a" in text and "b" in text and "r1" in text
