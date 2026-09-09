"""Tests for opencode event normalisation (unit under test: coders/opencode.py normalize_event)."""

from pathlib import Path

from fleet.coders.opencode import OpencodeCoder
from fleet.state.paths import fleet_home

_STEP_START = (
    '{"type":"step_start","timestamp":1781181263432,"sessionID":"ses_14952f145ffe6i6cC5sr4'
    'MneT7","part":{"id":"prt_eb6ad2e41001rLoEveqAPkh9KB","messageID":"msg_eb6ad0f32001Bv5'
    'NbG4qKIw7aq","sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","type":"step-start"}}'
)


_TOOL_COMPLETED = (
    '{"type":"tool_use","timestamp":1781181264224,"sessionID":"ses_14952f145ffe6i6cC5sr4Mn'
    'eT7","part":{"id":"prt_eb6ad31440017I2D03Fe31LaMa","messageID":"msg_eb6ad0f32001Bv5Nb'
    'G4qKIw7aq","sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","type":"tool","tool":"write",'
    '"callID":"call_cqjai8qz","state":{"status":"completed","input":{"filePath":"/tmp/prob'
    'e.txt","content":"tunnel works."},"output":"Wrote file successfully."}}}'
)


_STEP_FINISH_TOOL_CALLS = (
    '{"type":"step_finish","timestamp":1781181264225,"sessionID":"ses_14952f145ffe6i6cC5sr'
    '4MneT7","part":{"id":"prt_eb6ad315d001k6lnYIigM3F02u","reason":"tool-calls","messageI'
    'D":"msg_eb6ad0f32001Bv5NbG4qKIw7aq","sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","typ'
    'e":"step-finish","tokens":{"total":10520,"input":10385,"output":135,"reasoning":0,"ca'
    'che":{"write":0,"read":0}},"cost":0}}'
)


_TEXT = (
    '{"type":"text","timestamp":1781181264469,"sessionID":"ses_14952f145ffe6i6cC5sr4MneT7"'
    ',"part":{"id":"prt_eb6ad324d001rlcct26AoaSGNK","messageID":"msg_eb6ad3164001I77nTRvr5'
    'Dm23h","sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","type":"text","text":"DONE","time'
    '":{"start":1781181264468,"end":1781181264468}}}'
)


_STEP_FINISH_STOP = (
    '{"type":"step_finish","timestamp":1781181264472,"sessionID":"ses_14952f145ffe6i6cC5sr'
    '4MneT7","part":{"id":"prt_eb6ad3255001219bWTz4Hcu2jt","reason":"stop","messageID":"ms'
    'g_eb6ad3164001I77nTRvr5Dm23h","sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","type":"st'
    'ep-finish","tokens":{"total":10466,"input":10461,"output":5,"reasoning":0,"cache":{"w'
    'rite":0,"read":0}},"cost":0}}'
)


_TOOL_ERROR = (
    '{"type":"tool_use","timestamp":1234,"sessionID":"ses_test","part":{"type":"tool","too'
    'l":"write","callID":"call_abc","state":{"status":"error"}}}'
)


_STEP_FINISH_LENGTH = (
    '{"type":"step_finish","timestamp":1781181264472,"sessionID":"ses_14952f145ffe6i6cC5sr'
    '4MneT7","part":{"id":"prt_xxx","reason":"length","messageID":"msg_xxx","sessionID":"s'
    'es_14952f145ffe6i6cC5sr4MneT7","type":"step-finish","tokens":{"total":131072,"input":'
    '131000,"output":72,"reasoning":0,"cache":{"write":0,"read":0}},"cost":0}}'
)


_SESSION_ID = "ses_14952f145ffe6i6cC5sr4MneT7"


def _coder(**kwargs) -> OpencodeCoder:
    kwargs.setdefault("fleet_home", fleet_home())
    return OpencodeCoder(**kwargs)


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


def test_normalize_step_start_is_session_started():
    evt = _coder().normalize_event(_STEP_START)
    assert evt is not None
    assert evt.kind == "session_started"
    assert evt.session_id == _SESSION_ID


def test_normalize_tool_completed_is_tool_result():
    evt = _coder().normalize_event(_TOOL_COMPLETED)
    assert evt is not None
    assert evt.kind == "tool_result"
    assert evt.tool_name == "write"


def test_normalize_step_finish_tool_calls_is_assistant_text_with_usage():
    # step_finish with reason "tool-calls" should emit usage so the runner
    # can track context growth mid-session (context-pressure reclaim).
    evt = _coder().normalize_event(_STEP_FINISH_TOOL_CALLS)
    assert evt is not None
    assert evt.kind == "assistant_text"
    assert evt.usage is not None
    assert evt.usage["input_tokens"] == 10385
    assert evt.usage["output_tokens"] == 135
    assert evt.usage["cache_creation_input_tokens"] == 0
    assert evt.usage["cache_read_input_tokens"] == 0


def test_normalize_step_finish_tool_calls_no_tokens_returns_none():
    # step_finish with a non-stop reason but no tokens payload → None
    line = (
        '{"type":"step_finish","timestamp":1781181264225,'
        '"sessionID":"ses_14952f145ffe6i6cC5sr4MneT7",'
        '"part":{"id":"prt_xxx","reason":"tool-calls","type":"step-finish"}}'
    )
    assert _coder().normalize_event(line) is None


def test_normalize_step_finish_length_is_error():
    # ollama returns finish_reason="length" when context is truncated; surface as error
    evt = _coder().normalize_event(_STEP_FINISH_LENGTH)
    assert evt is not None
    assert evt.kind == "error"
    assert evt.session_id == _SESSION_ID


def test_normalize_text_is_assistant_text():
    evt = _coder().normalize_event(_TEXT)
    assert evt is not None
    assert evt.kind == "assistant_text"
    assert evt.session_id == _SESSION_ID


def test_normalize_step_finish_stop_is_session_ended():
    evt = _coder().normalize_event(_STEP_FINISH_STOP)
    assert evt is not None
    assert evt.kind == "session_ended"
    assert evt.session_id == _SESSION_ID


def test_normalize_step_finish_stop_usage_numbers():
    evt = _coder().normalize_event(_STEP_FINISH_STOP)
    assert evt is not None
    assert evt.usage is not None
    assert evt.usage["input_tokens"] == 10461
    assert evt.usage["output_tokens"] == 5
    assert evt.usage["cache_creation_input_tokens"] == 0
    assert evt.usage["cache_read_input_tokens"] == 0


def test_normalize_tool_error_is_error():
    evt = _coder().normalize_event(_TOOL_ERROR)
    assert evt is not None
    assert evt.kind == "error"
    assert evt.tool_name == "write"


def test_write_runtime_config_hook_absent(tmp_path: Path):
    # Config travels via OPENCODE_CONFIG_CONTENT in env(); opencode exposes
    # no write_runtime_config hook, so workers skip the project write.
    assert getattr(_coder(), "write_runtime_config", None) is None
    assert not (tmp_path / "opencode.json").exists()
