from datetime import UTC, datetime

from fleet.coders.opencode import classify_opencode_log_lines
from fleet.core.task import TaskOutcome

_SINCE = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
_MODEL = "opencode/muse-spark-1.3-contributor-free"


def _line(ts: str, model: str = "muse-spark-1.3-contributor-free", msg: str = "") -> str:
    return (
        f'timestamp={ts} level=ERROR run=5c9887cc message="stream error" '
        f"providerID=opencode modelID={model} session.id=ses_abc small=true "
        f'agent=title mode=primary error.error="{msg}"'
    )


def test_rate_limit_line_returns_rate_limit_with_future_resets_at() -> None:
    line = _line(
        "2026-09-07T12:05:00.000Z",
        msg="AI_APICallError: Rate limit exceeded. [rate_limit_exceeded]",
    )
    now = datetime.now(tz=UTC).timestamp()

    result = classify_opencode_log_lines([line], since=_SINCE, model=_MODEL)

    assert result is not None
    assert result.outcome == TaskOutcome.RATE_LIMIT
    assert result.resets_at is not None
    assert result.resets_at > now


def test_connect_error_line_returns_failure_with_reason() -> None:
    line = _line(
        "2026-09-07T12:05:00.000Z",
        msg="AI_APICallError: Cannot connect to API",
    )

    result = classify_opencode_log_lines([line], since=_SINCE, model=_MODEL)

    assert result is not None
    assert result.outcome == TaskOutcome.FAILURE
    assert result.exit_code is None
    assert "opencode provider unreachable" in result.reason


def test_line_before_since_is_ignored() -> None:
    line = _line(
        "2026-09-07T11:59:00.000Z",
        msg="AI_APICallError: Rate limit exceeded. [rate_limit_exceeded]",
    )

    result = classify_opencode_log_lines([line], since=_SINCE, model=_MODEL)

    assert result is None


def test_line_for_another_model_is_ignored() -> None:
    line = _line(
        "2026-09-07T12:05:00.000Z",
        model="some-other-model",
        msg="AI_APICallError: Rate limit exceeded. [rate_limit_exceeded]",
    )

    result = classify_opencode_log_lines([line], since=_SINCE, model=_MODEL)

    assert result is None


def test_empty_lines_returns_none() -> None:
    assert classify_opencode_log_lines([], since=_SINCE, model=_MODEL) is None


def test_error_from_another_session_is_ignored_when_session_known() -> None:
    """Regression: fleet-exfhr was released as rate_limit because a sibling
    task's session logged [rate_limit_exceeded] into the shared opencode.log."""
    line = _line(
        "2026-09-07T12:05:00.000Z",
        msg="AI_APICallError: Rate limit exceeded. [rate_limit_exceeded]",
    )  # session.id=ses_abc

    assert (
        classify_opencode_log_lines([line], since=_SINCE, model=_MODEL, session_id="ses_other")
        is None
    )
    own = classify_opencode_log_lines([line], since=_SINCE, model=_MODEL, session_id="ses_abc")
    assert own is not None and own.outcome == TaskOutcome.RATE_LIMIT


def test_line_without_session_id_still_counts() -> None:
    line = (
        'timestamp=2026-09-07T12:05:00.000Z level=ERROR message="stream error" '
        "providerID=opencode modelID=muse-spark-1.3-contributor-free "
        'error.error="Rate limit exceeded. [rate_limit_exceeded]"'
    )
    result = classify_opencode_log_lines([line], since=_SINCE, model=_MODEL, session_id="ses_x")
    assert result is not None and result.outcome == TaskOutcome.RATE_LIMIT
