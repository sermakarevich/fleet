"""Tests for Claude event normalisation (unit under test: coders/claude.py normalize_event)."""

import json
from pathlib import Path

import pytest

from tests.coders.conftest import _coder

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _lines(fixture: str) -> list[str]:
    return [line for line in (FIXTURES / fixture).read_text().splitlines() if line.strip()]


def test_normalize_event_returns_none_for_malformed_json():
    coder = _coder()
    assert coder.normalize_event("not json") is None
    assert coder.normalize_event("") is None
    assert coder.normalize_event("{bad") is None


def test_normalize_event_returns_none_for_non_dict():
    coder = _coder()
    assert coder.normalize_event("[1,2,3]") is None


def test_normalize_event_returns_none_for_unknown_type():
    coder = _coder()
    assert coder.normalize_event('{"type": "completely_unknown_type"}') is None


def test_normalize_assistant_text():
    coder = _coder()
    [line] = _lines("claude_stream_basic.jsonl")[:1]
    evt = coder.normalize_event(line)
    assert evt is not None
    assert evt.kind == "assistant_text"
    assert evt.session_id == "sess_abc123"
    assert evt.usage is not None
    assert evt.usage["input_tokens"] == 100


def test_normalize_tool_use():
    coder = _coder()
    lines = _lines("claude_stream_basic.jsonl")
    # second line is tool_use
    evt = coder.normalize_event(lines[1])
    assert evt is not None
    assert evt.kind == "tool_use"
    assert evt.tool_name == "Read"


def test_normalize_assistant_tool_use_block():
    """Real stream-json wraps tool_use as a content block of an assistant message."""
    coder = _coder()
    line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_02",
                        "name": "Edit",
                        "input": {"file_path": "/bar.py"},
                    }
                ],
                "usage": {"input_tokens": 40, "output_tokens": 7},
            },
            "session_id": "sess_abc123",
        }
    )
    evt = coder.normalize_event(line)
    assert evt is not None
    assert evt.kind == "tool_use"
    assert evt.tool_name == "Edit"
    assert evt.session_id == "sess_abc123"
    # raw is the block itself so raw["input"]["file_path"] stays reachable
    assert evt.raw["input"]["file_path"] == "/bar.py"
    # usage rides along so token accounting keeps parity with assistant_text
    assert evt.usage == {"input_tokens": 40, "output_tokens": 7}


def test_normalize_tool_result():
    coder = _coder()
    lines = _lines("claude_stream_basic.jsonl")
    # third line is tool_result
    evt = coder.normalize_event(lines[2])
    assert evt is not None
    assert evt.kind == "tool_result"
    assert evt.tool_name == "Read"


def test_normalize_session_started():
    coder = _coder()
    [init_line, _result_line] = _lines("claude_stream_session.jsonl")
    evt = coder.normalize_event(init_line)
    assert evt is not None
    assert evt.kind == "session_started"
    assert evt.session_id == "sess_xyz789"


def test_normalize_session_ended():
    coder = _coder()
    [_init_line, result_line] = _lines("claude_stream_session.jsonl")
    evt = coder.normalize_event(result_line)
    assert evt is not None
    assert evt.kind == "session_ended"
    assert evt.session_id == "sess_xyz789"
    assert evt.usage is not None
    assert evt.usage["input_tokens"] == 2500


def test_normalize_rate_limit_info():
    coder = _coder()
    [line] = _lines("claude_stream_rate_limit_info.jsonl")
    evt = coder.normalize_event(line)
    assert evt is not None
    assert evt.kind == "rate_limit_info"
    assert evt.rate_info is not None
    assert evt.rate_info["usage_pct"] == pytest.approx(85.5)
    assert evt.rate_info["resets_at"] == 1748001000
    assert evt.rate_info["status"] == "approaching"


def test_normalize_rate_limit_info_utilization_fraction():
    """Real Claude CLI reports usage via `utilization` (0-1 fraction)."""
    coder = _coder()
    [line] = _lines("claude_stream_rate_limit_utilization.jsonl")
    evt = coder.normalize_event(line)
    assert evt is not None
    assert evt.kind == "rate_limit_info"
    assert evt.rate_info is not None
    assert evt.rate_info["usage_pct"] == pytest.approx(90.0)
    assert evt.rate_info["resets_at"] == 1779564600
    assert evt.rate_info["status"] == "allowed_warning"


def test_normalize_rate_limit_info_utilization_above_one():
    """`utilization` can exceed 1.0 for the session cap; gauge must accept it."""
    coder = _coder()
    raw = json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "allowed_warning",
                "utilization": 1.07,
                "rateLimitType": "five_hour",
                "resetsAt": 1779564600,
            },
        }
    )
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.rate_info is not None
    assert evt.rate_info["usage_pct"] == pytest.approx(107.0)


def test_normalize_rate_limit_overage_returns_none():
    """Overage events track a long-horizon budget and must not gate spawning."""
    coder = _coder()
    raw = json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "allowed_warning",
                "utilization": 1.07,
                "rateLimitType": "overage",
                "resetsAt": 1779564600,
            },
        }
    )
    evt = coder.normalize_event(raw)
    assert evt is None


def test_normalize_rate_limit_weekly_returns_none():
    """Weekly rate-limit events must be ignored; only session-level usage counts."""
    coder = _coder()
    [line] = _lines("claude_stream_rate_limit_weekly.jsonl")
    evt = coder.normalize_event(line)
    assert evt is None


def test_normalize_rate_limit_weekly_ignored_inline():
    """Inline weekly event also returns None."""
    coder = _coder()
    raw = json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "allowed_warning",
                "rateLimitType": "weekly",
                "utilization": 0.72,
                "resetsAt": 1779564600,
            },
        }
    )
    evt = coder.normalize_event(raw)
    assert evt is None


def test_normalize_rate_limit_info_missing_usage_fields():
    """No usage_pct, usagePct, or utilization -> rate_info['usage_pct'] is None."""
    coder = _coder()
    raw = json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "allowed",
                "resetsAt": 1779564600,
                "rateLimitType": "five_hour",
            },
        }
    )
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.rate_info is not None
    assert evt.rate_info["usage_pct"] is None
    assert evt.rate_info["resets_at"] == 1779564600


def test_normalize_rate_limit_rejected():
    coder = _coder()
    [line] = _lines("claude_stream_rate_limit_rejected.jsonl")
    evt = coder.normalize_event(line)
    assert evt is not None
    assert evt.kind == "rate_limit"
    assert evt.rate_info is not None
    assert evt.rate_info["status"] == "rejected"
    assert evt.rate_info["resets_at"] == 1748001600


def test_normalize_thinking_event():
    coder = _coder()
    raw = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "thinking", "thinking": "Let me reason..."}],
                "usage": {"input_tokens": 50, "output_tokens": 30},
            },
            "session_id": "sess_think",
        }
    )
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "thinking"
    assert evt.session_id == "sess_think"
