import json
import os
from pathlib import Path

import pytest

from fleet.coders.base import Coder
from fleet.coders import get_coder, list_coders
from fleet.coders.opencode import OpencodeCoder
from fleet.schemas import Task

# Real event lines captured from the live end-to-end probe (events.jsonl)
_STEP_START = '{"type":"step_start","timestamp":1781181263432,"sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","part":{"id":"prt_eb6ad2e41001rLoEveqAPkh9KB","messageID":"msg_eb6ad0f32001Bv5NbG4qKIw7aq","sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","type":"step-start"}}'
_TOOL_COMPLETED = '{"type":"tool_use","timestamp":1781181264224,"sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","part":{"id":"prt_eb6ad31440017I2D03Fe31LaMa","messageID":"msg_eb6ad0f32001Bv5NbG4qKIw7aq","sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","type":"tool","tool":"write","callID":"call_cqjai8qz","state":{"status":"completed","input":{"filePath":"/tmp/probe.txt","content":"tunnel works."},"output":"Wrote file successfully."}}}'
_STEP_FINISH_TOOL_CALLS = '{"type":"step_finish","timestamp":1781181264225,"sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","part":{"id":"prt_eb6ad315d001k6lnYIigM3F02u","reason":"tool-calls","messageID":"msg_eb6ad0f32001Bv5NbG4qKIw7aq","sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","type":"step-finish","tokens":{"total":10520,"input":10385,"output":135,"reasoning":0,"cache":{"write":0,"read":0}},"cost":0}}'
_TEXT = '{"type":"text","timestamp":1781181264469,"sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","part":{"id":"prt_eb6ad324d001rlcct26AoaSGNK","messageID":"msg_eb6ad3164001I77nTRvr5Dm23h","sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","type":"text","text":"DONE","time":{"start":1781181264468,"end":1781181264468}}}'
_STEP_FINISH_STOP = '{"type":"step_finish","timestamp":1781181264472,"sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","part":{"id":"prt_eb6ad3255001219bWTz4Hcu2jt","reason":"stop","messageID":"msg_eb6ad3164001I77nTRvr5Dm23h","sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","type":"step-finish","tokens":{"total":10466,"input":10461,"output":5,"reasoning":0,"cache":{"write":0,"read":0}},"cost":0}}'
_TOOL_ERROR = '{"type":"tool_use","timestamp":1234,"sessionID":"ses_test","part":{"type":"tool","tool":"write","callID":"call_abc","state":{"status":"error"}}}'

_SESSION_ID = "ses_14952f145ffe6i6cC5sr4MneT7"


def _coder() -> OpencodeCoder:
    return OpencodeCoder()


def _task(task_id: str = "test-001", cwd: str | None = None) -> Task:
    return Task(id=task_id, title="Test task", description="Do the thing.", status="in_progress", cwd=cwd)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_get_coder_returns_opencode_class():
    assert get_coder("opencode") is OpencodeCoder


def test_opencode_in_list_coders():
    names = [c["name"] for c in list_coders()]
    assert "opencode" in names


def test_opencode_coder_is_subclass_of_coder_base():
    assert issubclass(OpencodeCoder, Coder)


# ---------------------------------------------------------------------------
# build_argv
# ---------------------------------------------------------------------------

def test_build_argv_starts_with_opencode_run(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert argv[0] == "opencode"
    assert argv[1] == "run"


def test_build_argv_includes_format_json(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    idx = argv.index("--format")
    assert argv[idx + 1] == "json"


def test_build_argv_includes_model_flag_defaults_to_gpt_oss(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/gpt-oss:20b"


def test_build_argv_uses_custom_model(tmp_path: Path):
    argv = OpencodeCoder(model="qwen3.5:27b").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/qwen3.5:27b"


def test_build_argv_full_provider_model_passed_verbatim(tmp_path: Path):
    argv = OpencodeCoder(model="ollama-rtx/deepseek-r1:32b").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/deepseek-r1:32b"


def test_build_argv_sonnet_alias_resolved_to_default(tmp_path: Path):
    argv = OpencodeCoder(model="sonnet").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/gpt-oss:20b"


def test_build_argv_opus_alias_resolved_to_default(tmp_path: Path):
    argv = OpencodeCoder(model="opus").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/gpt-oss:20b"


def test_build_argv_haiku_alias_resolved_to_default(tmp_path: Path):
    argv = OpencodeCoder(model="haiku").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/gpt-oss:20b"


def test_build_argv_includes_dir_flag_when_task_has_cwd(tmp_path: Path):
    task = _task(cwd="/Users/me/project")
    argv = _coder().build_argv(task, tmp_path)
    idx = argv.index("--dir")
    assert argv[idx + 1] == "/Users/me/project"


def test_build_argv_omits_dir_flag_when_no_cwd(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert "--dir" not in argv


def test_build_argv_prompt_contains_task_id(tmp_path: Path):
    argv = _coder().build_argv(_task("my-task-id"), tmp_path)
    assert "my-task-id" in argv[-1]


def test_build_argv_prompt_contains_task_title(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert "Test task" in argv[-1]


def test_build_argv_prompt_contains_task_description(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert "Do the thing." in argv[-1]


def test_build_argv_inlines_instruction_md_content(tmp_path: Path):
    prompt = _coder().build_argv(_task(), tmp_path)[-1]
    assert "Fleet Task Protocol" in prompt
    assert "ask_human" in prompt
    assert "bd update" in prompt


def test_build_argv_includes_invocation_line_when_cwd_set(tmp_path: Path):
    task = _task(cwd="/Users/me/project-x")
    prompt = _coder().build_argv(task, tmp_path)[-1]
    assert "Invocation directory: /Users/me/project-x" in prompt


def test_build_argv_omits_invocation_line_when_no_cwd(tmp_path: Path):
    prompt = _coder().build_argv(_task(), tmp_path)[-1]
    assert "Invocation directory:" not in prompt


def test_default_model_attribute():
    assert _coder().model == "gpt-oss:20b"
    assert OpencodeCoder.default_model == "gpt-oss:20b"


# ---------------------------------------------------------------------------
# env
# ---------------------------------------------------------------------------

def test_env_includes_required_vars(tmp_path: Path):
    env = _coder().env(_task("t-42"), tmp_path)
    assert env["FLEET_TASK_ID"] == "t-42"
    assert env["FLEET_TASK_DIR"] == str(tmp_path)
    assert env["FLEET_ARTIFACT_DIR"] == str(tmp_path / "artifacts")


def test_env_exactly_three_keys(tmp_path: Path):
    env = _coder().env(_task(), tmp_path)
    assert set(env.keys()) == {"FLEET_TASK_ID", "FLEET_TASK_DIR", "FLEET_ARTIFACT_DIR"}


# ---------------------------------------------------------------------------
# normalize_event — malformed / unknown
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# normalize_event — real probe lines
# ---------------------------------------------------------------------------

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


def test_normalize_step_finish_tool_calls_returns_none():
    assert _coder().normalize_event(_STEP_FINISH_TOOL_CALLS) is None


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


# ---------------------------------------------------------------------------
# write_runtime_config
# ---------------------------------------------------------------------------

def test_write_runtime_config_fresh_dir_creates_file(tmp_path: Path):
    _coder().write_runtime_config(tmp_path, object())
    target = tmp_path / "opencode.json"
    assert target.exists()
    data = json.loads(target.read_text())
    assert data["$schema"] == "https://opencode.ai/config.json"
    assert "ollama-rtx" in data["provider"]


def test_write_runtime_config_provider_entry_structure(tmp_path: Path):
    _coder().write_runtime_config(tmp_path, object())
    data = json.loads((tmp_path / "opencode.json").read_text())
    entry = data["provider"]["ollama-rtx"]
    assert entry["npm"] == "@ai-sdk/openai-compatible"
    assert entry["name"] == "Ollama (rtx)"
    assert entry["options"]["baseURL"] == "http://127.0.0.1:11435/v1"
    assert "gpt-oss:20b" in entry["models"]
    assert entry["models"]["gpt-oss:20b"]["tools"] is True


def test_write_runtime_config_ollama_url_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FLEET_OPENCODE_OLLAMA_URL", "http://127.0.0.1:12345/v1")
    _coder().write_runtime_config(tmp_path, object())
    data = json.loads((tmp_path / "opencode.json").read_text())
    assert data["provider"]["ollama-rtx"]["options"]["baseURL"] == "http://127.0.0.1:12345/v1"


def test_write_runtime_config_preserves_foreign_keys(tmp_path: Path):
    existing = {
        "theme": "dark",
        "provider": {"mine": {"npm": "@custom/pkg", "name": "Mine", "options": {}, "models": {}}},
    }
    (tmp_path / "opencode.json").write_text(json.dumps(existing, indent=2))
    _coder().write_runtime_config(tmp_path, object())
    data = json.loads((tmp_path / "opencode.json").read_text())
    assert data.get("theme") == "dark"
    assert "mine" in data["provider"]
    assert "ollama-rtx" in data["provider"]


def test_write_runtime_config_does_not_clobber_existing_schema(tmp_path: Path):
    existing = {"$schema": "https://custom.example.com/schema.json"}
    (tmp_path / "opencode.json").write_text(json.dumps(existing))
    _coder().write_runtime_config(tmp_path, object())
    data = json.loads((tmp_path / "opencode.json").read_text())
    assert data["$schema"] == "https://custom.example.com/schema.json"


def test_write_runtime_config_tolerates_corrupted_json(tmp_path: Path):
    (tmp_path / "opencode.json").write_text("{not valid json!!")
    _coder().write_runtime_config(tmp_path, object())
    data = json.loads((tmp_path / "opencode.json").read_text())
    assert "ollama-rtx" in data["provider"]


def test_write_runtime_config_idempotent(tmp_path: Path):
    _coder().write_runtime_config(tmp_path, object())
    first = (tmp_path / "opencode.json").read_bytes()
    _coder().write_runtime_config(tmp_path, object())
    second = (tmp_path / "opencode.json").read_bytes()
    assert first == second
