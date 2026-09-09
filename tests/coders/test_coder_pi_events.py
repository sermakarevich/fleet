"""Tests for Pi event normalisation (unit under test: coders/pi.py normalize_event)."""

import json
from pathlib import Path

from fleet.coders.pi import PiCoder
from fleet.coders.settings import PiSettings
from fleet.state.paths import fleet_home


def _coder(agent_dir: Path | None = None, **kwargs) -> PiCoder:
    """Build PiCoder with an explicit agent dir (no env reads inside the coder)."""
    if agent_dir is not None and "settings" not in kwargs:
        kwargs["settings"] = PiSettings(agent_dir=agent_dir)
    kwargs.setdefault("fleet_home", fleet_home())
    return PiCoder(**kwargs)


def test_normalize_event_blank_returns_none():
    assert _coder().normalize_event("") is None
    assert _coder().normalize_event("   ") is None
    assert _coder().normalize_event("\n") is None


def test_normalize_event_malformed_json_returns_none():
    assert _coder().normalize_event("not json") is None
    assert _coder().normalize_event("{bad") is None


def test_normalize_event_json_array_returns_none():
    assert _coder().normalize_event("[1,2,3]") is None


def test_normalize_event_unknown_type_returns_none():
    assert _coder().normalize_event('{"type":"completely_unknown"}') is None


def test_normalize_event_agent_start_returns_none():
    assert _coder().normalize_event('{"type":"agent_start"}') is None


def test_normalize_event_turn_start_returns_none():
    assert _coder().normalize_event('{"type":"turn_start"}') is None


def test_normalize_event_message_update_returns_none():
    line = json.dumps({"type": "message_update", "delta": {"text": "hi"}})
    assert _coder().normalize_event(line) is None


def test_normalize_session_is_session_started_with_id():
    line = json.dumps({"type": "session", "id": "ses_abc123", "cwd": "/tmp"})
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.kind == "session_started"
    assert evt.session_id == "ses_abc123"


def test_normalize_message_end_assistant_is_assistant_text():
    line = json.dumps(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "stopReason": "stop",
                "usage": {"input": 100, "output": 20, "cacheWrite": 5, "cacheRead": 6},
                "content": [{"type": "text", "text": "DONE"}],
            },
        }
    )
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.kind == "assistant_text"


def test_normalize_message_end_assistant_usage_mapped():
    line = json.dumps(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "stopReason": "stop",
                "usage": {"input": 10385, "output": 135, "cacheWrite": 0, "cacheRead": 0},
            },
        }
    )
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.usage is not None
    assert evt.usage["input_tokens"] == 10385
    assert evt.usage["output_tokens"] == 135
    assert evt.usage["cache_creation_input_tokens"] == 0
    assert evt.usage["cache_read_input_tokens"] == 0


def test_normalize_message_end_cache_tokens_mapped():
    line = json.dumps(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "usage": {"input": 10, "output": 5, "cacheWrite": 2, "cacheRead": 3},
            },
        }
    )
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.usage["cache_creation_input_tokens"] == 2
    assert evt.usage["cache_read_input_tokens"] == 3


def test_normalize_message_end_length_stop_is_error():
    # pi reports stopReason "length" when the model is cut off; surface as error
    line = json.dumps(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "stopReason": "length",
                "usage": {"input": 131000, "output": 72},
            },
        }
    )
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.kind == "error"


def test_normalize_message_end_user_role_returns_none():
    line = json.dumps({"type": "message_end", "message": {"role": "user", "content": "hi"}})
    assert _coder().normalize_event(line) is None


def test_normalize_message_end_tool_role_returns_none():
    line = json.dumps({"type": "message_end", "message": {"role": "toolResult", "content": "out"}})
    assert _coder().normalize_event(line) is None


def test_normalize_message_end_missing_message_returns_none():
    assert _coder().normalize_event('{"type":"message_end"}') is None


def test_normalize_tool_execution_start_is_tool_use():
    line = json.dumps({"type": "tool_execution_start", "toolName": "write"})
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.kind == "tool_use"
    assert evt.tool_name == "write"


def test_normalize_tool_execution_end_is_tool_result():
    line = json.dumps({"type": "tool_execution_end", "toolName": "write", "isError": False})
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.kind == "tool_result"
    assert evt.tool_name == "write"


def test_normalize_tool_execution_end_missing_is_error_flag_is_tool_result():
    line = json.dumps({"type": "tool_execution_end", "toolName": "read"})
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.kind == "tool_result"


def test_normalize_tool_execution_end_error_is_error():
    line = json.dumps({"type": "tool_execution_end", "toolName": "write", "isError": True})
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.kind == "error"
    assert evt.tool_name == "write"


def test_normalize_agent_end_is_session_ended():
    evt = _coder().normalize_event('{"type":"agent_end"}')
    assert evt is not None
    assert evt.kind == "session_ended"


def test_normalize_error_type_is_error():
    evt = _coder().normalize_event('{"type":"error","message":"boom"}')
    assert evt is not None
    assert evt.kind == "error"
