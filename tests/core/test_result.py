from __future__ import annotations

from fleet.core.result import ResultStatus, parse_result


def test_parse_result_done() -> None:
    result = parse_result('{"schema": 1, "status": "done", "summary": "shipped it"}')
    assert result is not None
    assert result.status == ResultStatus.DONE
    assert result.summary == "shipped it"
    assert result.commits == []
    assert result.tests is None


def test_parse_result_partial_with_next_step() -> None:
    text = '{"schema": 1, "status": "partial", "summary": "half done", "next_step": "run tests"}'
    result = parse_result(text)
    assert result is not None
    assert result.status == ResultStatus.PARTIAL
    assert result.next_step == "run tests"


def test_parse_result_blocked_with_reason() -> None:
    text = '{"schema": 1, "status": "blocked", "blocked_reason": "need creds"}'
    result = parse_result(text)
    assert result is not None
    assert result.status == ResultStatus.BLOCKED
    assert result.blocked_reason == "need creds"


def test_parse_result_full_schema() -> None:
    text = """
    {
      "schema": 1,
      "status": "done",
      "summary": "did the thing",
      "commits": ["abc123", "def456"],
      "tests": {"command": "pytest", "passed": true},
      "open_questions": ["is this right?"],
      "next_step": "",
      "blocked_reason": ""
    }
    """
    result = parse_result(text)
    assert result is not None
    assert result.commits == ["abc123", "def456"]
    assert result.tests == {"command": "pytest", "passed": True}
    assert result.open_questions == ["is this right?"]


def test_parse_result_invalid_json_returns_none() -> None:
    assert parse_result("not json") is None


def test_parse_result_not_an_object_returns_none() -> None:
    assert parse_result("[1, 2, 3]") is None


def test_parse_result_missing_status_returns_none() -> None:
    assert parse_result('{"summary": "no status"}') is None


def test_parse_result_unknown_status_returns_none() -> None:
    assert parse_result('{"status": "finished"}') is None


def test_parse_result_missing_optional_fields_default() -> None:
    result = parse_result('{"status": "done"}')
    assert result is not None
    assert result.summary == ""
    assert result.commits == []
    assert result.open_questions == []
    assert result.next_step == ""
    assert result.blocked_reason == ""
