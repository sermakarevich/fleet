"""Tests for core/result.py followups parsing. Mirrors the source path."""

import json

from fleet.core.result import parse_result


def test_followups_absent_defaults_to_empty() -> None:
    result = parse_result(json.dumps({"schema": 1, "status": "done", "summary": "ok"}))
    assert result is not None
    assert result.followups == []


def test_followups_partial_parsed() -> None:
    followups = [{"title": "a", "body": "b", "cwd": None, "depends_on": []}]
    result = parse_result(
        json.dumps({"schema": 1, "status": "partial", "summary": "more", "followups": followups})
    )
    assert result is not None
    assert result.followups == followups


def test_followups_non_list_defaults_to_empty() -> None:
    result = parse_result(json.dumps({"schema": 1, "status": "partial", "followups": "nope"}))
    assert result is not None
    assert result.followups == []
