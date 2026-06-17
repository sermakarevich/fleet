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
_STEP_FINISH_LENGTH = '{"type":"step_finish","timestamp":1781181264472,"sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","part":{"id":"prt_xxx","reason":"length","messageID":"msg_xxx","sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","type":"step-finish","tokens":{"total":131072,"input":131000,"output":72,"reasoning":0,"cache":{"write":0,"read":0}},"cost":0}}'

_SESSION_ID = "ses_14952f145ffe6i6cC5sr4MneT7"


def _coder() -> OpencodeCoder:
    return OpencodeCoder()


def _task(task_id: str = "test-001", cwd: str | None = None) -> Task:
    return Task(
        id=task_id,
        title="Test task",
        description="Do the thing.",
        status="in_progress",
        cwd=cwd,
    )


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


def test_build_argv_context_limit_default():
    coder = OpencodeCoder()
    assert coder.context_limit == 128_000


def test_build_argv_context_limit_custom():
    coder = OpencodeCoder(context_limit=64_000)
    assert coder.context_limit == 64_000


def test_build_argv_default_model_custom_resolves_sonet():
    # When default_model is "qwen3.6:latest", sonnet alias should resolve to it
    argv = OpencodeCoder(model="sonnet", default_model="qwen3.6:latest").build_argv(
        _task(), Path("/tmp")
    )
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/qwen3.6:latest"


def test_build_argv_default_model_custom_used_directly():
    # When default_model is a full provider model, it's used as-is
    argv = OpencodeCoder(
        model="qwen3.6:latest", default_model="qwen3.6:latest"
    ).build_argv(_task(), Path("/tmp"))
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/qwen3.6:latest"


def test_write_runtime_config_default_model_in_provider_models(tmp_path: Path):
    coder = OpencodeCoder(model="sonnet", default_model="qwen3.6:latest")
    coder.write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    entry = cfg["provider"]["ollama-rtx"]
    assert "qwen3.6:latest" in entry["models"]


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
    argv = OpencodeCoder(model="ollama-rtx/deepseek-r1:32b").build_argv(
        _task(), tmp_path
    )
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


def test_env_bedrock_injects_aws_profile_and_region(tmp_path: Path):
    coder = OpencodeCoder(
        model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        bedrock_profile="dev",
        bedrock_region="us-east-1",
    )
    env = coder.env(_task("t-42"), tmp_path)
    assert env["AWS_PROFILE"] == "dev"
    assert env["AWS_REGION"] == "us-east-1"
    assert env["FLEET_TASK_ID"] == "t-42"
    assert env["FLEET_TASK_DIR"] == str(tmp_path)
    assert env["FLEET_ARTIFACT_DIR"] == str(tmp_path / "artifacts")


def test_env_bedrock_empty_config_no_aws_keys(tmp_path: Path):
    coder = OpencodeCoder(
        model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )
    env = coder.env(_task(), tmp_path)
    assert "AWS_PROFILE" not in env
    assert "AWS_REGION" not in env


def test_env_ollama_model_no_aws_keys_even_with_bedrock_config(tmp_path: Path):
    coder = OpencodeCoder(
        model="qwen3.6:latest",
        bedrock_profile="dev",
        bedrock_region="us-east-1",
    )
    env = coder.env(_task(), tmp_path)
    assert "AWS_PROFILE" not in env
    assert "AWS_REGION" not in env


# ---------------------------------------------------------------------------
# build_argv — isolation / worktree marker
# ---------------------------------------------------------------------------


def test_build_argv_with_worktree_marker_includes_isolation_protocol(tmp_path: Path):
    """When a .worktree marker exists, the prompt must contain the isolation block."""
    (tmp_path / ".worktree").touch()
    argv = _coder().build_argv(_task("wt-001"), tmp_path)
    prompt = argv[-1]
    assert "Do NOT run `bd close`" in prompt


def test_build_argv_without_worktree_marker_excludes_isolation_protocol(tmp_path: Path):
    """Without a .worktree marker, the prompt must NOT contain the isolation block."""
    argv = _coder().build_argv(_task(), tmp_path)
    prompt = argv[-1]
    assert "Do NOT run `bd close`" not in prompt


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
    line = '{"type":"step_finish","timestamp":1781181264225,"sessionID":"ses_14952f145ffe6i6cC5sr4MneT7","part":{"id":"prt_xxx","reason":"tool-calls","type":"step-finish"}}'
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


def test_write_runtime_config_ollama_url_constructor(tmp_path: Path):
    coder = OpencodeCoder(ollama_url="http://127.0.0.1:12345/v1")
    task = _task()
    coder.write_runtime_config(tmp_path, task)
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    assert (
        cfg["provider"]["ollama-rtx"]["options"]["baseURL"]
        == "http://127.0.0.1:12345/v1"
    )


def test_write_runtime_config_preserves_foreign_keys(tmp_path: Path):
    existing = {
        "theme": "dark",
        "provider": {
            "mine": {"npm": "@custom/pkg", "name": "Mine", "options": {}, "models": {}}
        },
    }
    (tmp_path / "opencode.json").write_text(json.dumps(existing, indent=2))
    _coder().write_runtime_config(tmp_path, object())
    data = json.loads((tmp_path / "opencode.json").read_text())
    assert data.get("theme") == "dark"
    assert "mine" in data["provider"]
    assert "ollama-rtx" in data["provider"]
    assert "permission" in data
    assert "mcp" in data


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


def test_write_runtime_config_permission_block(tmp_path: Path):
    _coder().write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    assert cfg["permission"] == {"external_directory": "allow"}


def test_write_runtime_config_mcp_ask_human(tmp_path: Path):
    _coder().write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    entry = cfg["mcp"]["ask-human"]
    assert entry["type"] == "local"
    assert any("fleet.ask_human.server" in part for part in entry["command"])


def test_write_runtime_config_mcp_claude_code_available(tmp_path: Path):
    _coder().write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    entry = cfg["mcp"]["claude_code"]
    assert entry["enabled"] is True
    assert entry["type"] == "local"
    assert entry["command"][-1].endswith("claude_code/server.py")


def test_write_runtime_config_mcp_playwright_available(tmp_path: Path):
    _coder().write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    entry = cfg["mcp"]["playwright"]
    assert entry["enabled"] is True
    assert entry["type"] == "local"
    assert "@playwright/mcp@latest" in entry["command"]
    assert "--headless" in entry["command"]
    assert "--isolated" in entry["command"]


def test_write_runtime_config_mcp_web_fetch_available(tmp_path: Path):
    _coder().write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    entry = cfg["mcp"]["web_fetch"]
    assert entry["enabled"] is True
    assert entry["type"] == "local"
    assert entry["command"][-1] == "fleet.web_fetch.server"
    assert entry["environment"]["FLEET_WEBFETCH_MODEL"]
    assert entry["environment"]["FLEET_WEBFETCH_OLLAMA_URL"]
    assert "ask-human" in cfg["mcp"]


def test_write_runtime_config_mcp_ask_human_not_removed_after_playwright(
    tmp_path: Path,
):
    _coder().write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    assert "ask-human" in cfg["mcp"]
    assert any(
        "fleet.ask_human.server" in part for part in cfg["mcp"]["ask-human"]["command"]
    )


def test_write_runtime_config_mcp_ask_human_not_removed(tmp_path: Path):
    _coder().write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    assert "ask-human" in cfg["mcp"]
    assert any(
        "fleet.ask_human.server" in part for part in cfg["mcp"]["ask-human"]["command"]
    )


def test_write_runtime_config_mcp_preserves_existing(tmp_path: Path):
    existing = {"mcp": {"my-server": {"type": "local", "command": ["foo"]}}}
    (tmp_path / "opencode.json").write_text(json.dumps(existing, indent=2))
    _coder().write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    assert "my-server" in cfg["mcp"]
    assert "ask-human" in cfg["mcp"]


# ---------------------------------------------------------------------------
# default_model / context_limit parameters
# ---------------------------------------------------------------------------


def test_default_model_constructor_defaults_to_gpt_oss():
    coder = OpencodeCoder()
    assert coder.model == "gpt-oss:20b"


def test_default_context_limit_constructor():
    coder = OpencodeCoder()
    assert coder.context_limit == 128_000


def test_build_argv_sonnet_with_custom_default_resolves_default():
    argv = OpencodeCoder(model="sonnet", default_model="qwen3.5:27b").build_argv(
        _task(), Path("/tmp")
    )
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/qwen3.5:27b"


def test_build_argv_sonnet_with_gpt_oss_default_resolves_correctly():
    argv = OpencodeCoder(model="sonnet", default_model="gpt-oss:20b").build_argv(
        _task(), Path("/tmp")
    )
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/gpt-oss:20b"


def test_build_argv_explicit_model_ignores_default():
    argv = OpencodeCoder(
        model="deepseek-r1:32b", default_model="gpt-oss:20b"
    ).build_argv(_task(), Path("/tmp"))
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/deepseek-r1:32b"


def test_context_limit_custom_value():
    coder = OpencodeCoder(context_limit=256_000)
    assert coder.context_limit == 256_000


def test_write_runtime_config_uses_default_model_in_entry(tmp_path: Path):
    coder = OpencodeCoder(model="sonnet", default_model="qwen3.5:27b")
    coder.write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    entry = cfg["provider"]["ollama-rtx"]
    assert "qwen3.5:27b" in entry["models"]
    assert "gpt-oss:20b" not in entry["models"]


def test_write_runtime_config_merges_existing_models_and_permissions(tmp_path: Path):
    existing = {
        "provider": {
            "ollama-rtx": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Ollama (rtx)",
                "options": {"baseURL": "http://127.0.0.1:11435/v1"},
                "models": {"other-model": {"name": "other-model", "tools": True}},
            }
        },
        "permission": {"bash": "ask"},
    }
    (tmp_path / "opencode.json").write_text(json.dumps(existing, indent=2))
    _coder().write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    entry = cfg["provider"]["ollama-rtx"]
    assert "other-model" in entry["models"]
    assert "gpt-oss:20b" in entry["models"]
    assert cfg["permission"]["bash"] == "ask"
    assert cfg["permission"]["external_directory"] == "allow"


def test_write_runtime_config_no_tmp_file_left_behind(tmp_path: Path):
    _coder().write_runtime_config(tmp_path, object())
    target = tmp_path / "opencode.json"
    tmp = tmp_path / (target.name + ".tmp")
    assert not tmp.exists()


def test_write_runtime_config_model_has_limit_context(tmp_path: Path):
    """limit.context must match the constructor's context_limit (default 128_000)."""
    coder = OpencodeCoder()
    coder.write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    models = cfg["provider"]["ollama-rtx"]["models"]
    model_key = coder.model  # "gpt-oss:20b"
    assert models[model_key]["limit"]["context"] == 128_000


def test_write_runtime_config_limit_context_custom(tmp_path: Path):
    """limit.context must reflect an explicit context_limit value (252_000)."""
    coder = OpencodeCoder(context_limit=252_000)
    coder.write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    models = cfg["provider"]["ollama-rtx"]["models"]
    model_key = coder.model
    assert models[model_key]["limit"]["context"] == 252_000


def test_write_runtime_config_limit_output_always_8192(tmp_path: Path):
    """limit.output MUST always be 8192."""
    coder = OpencodeCoder()
    coder.write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    models = cfg["provider"]["ollama-rtx"]["models"]
    model_key = coder.model
    assert models[model_key]["limit"]["output"] == 8192


def test_write_runtime_config_limit_propagates_with_custom_model(tmp_path: Path):
    """limit block is written when using a custom model and context_limit."""
    coder = OpencodeCoder(model="qwen3.5:27b", context_limit=200_000)
    coder.write_runtime_config(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    models = cfg["provider"]["ollama-rtx"]["models"]
    assert models["qwen3.5:27b"]["limit"]["context"] == 200_000
    assert models["qwen3.5:27b"]["limit"]["output"] == 8192


def test_bedrock_params_stored_on_instance():
    coder = OpencodeCoder(
        bedrock_region="us-east-1", bedrock_profile="dev", bedrock_context_limit=150_000
    )
    assert coder.bedrock_region == "us-east-1"
    assert coder.bedrock_profile == "dev"
    assert coder.bedrock_context_limit == 150_000


def test_bedrock_params_default_values():
    coder = OpencodeCoder()
    assert coder.bedrock_region == ""
    assert coder.bedrock_profile == ""
    assert coder.bedrock_context_limit == 200_000


def test_write_runtime_config_merge_preserves_existing_models_limit(tmp_path: Path):
    """Models merged from existing configs keep their original entries; current model gets limit."""
    existing = {
        "provider": {
            "ollama-rtx": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Ollama (rtx)",
                "options": {"baseURL": "http://127.0.0.1:11435/v1"},
                "models": {"other-model": {"name": "other-model", "tools": True}},
            }
        },
        "permission": {"bash": "ask"},
    }
    (tmp_path / "opencode.json").write_text(json.dumps(existing, indent=2))
    coder = OpencodeCoder(context_limit=99_000)
    writer = coder.write_runtime_config
    writer(tmp_path, object())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    models = cfg["provider"]["ollama-rtx"]["models"]
    # current model gets limit
    assert models["gpt-oss:20b"]["limit"]["context"] == 99_000
    assert models["gpt-oss:20b"]["limit"]["output"] == 8192
    # existing models are preserved
    assert "other-model" in models
    assert models["other-model"]["name"] == "other-model"
    # merge keeps permission
    assert cfg["permission"]["bash"] == "ask"


def test_bedrock_model_is_bedrock_true_and_context_limit():
    coder = OpencodeCoder(
        model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )
    assert coder.is_bedrock is True
    assert coder.context_limit == 200_000


def test_bedrock_model_with_custom_context_limit():
    coder = OpencodeCoder(
        model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        bedrock_context_limit=150_000,
    )
    assert coder.is_bedrock is True
    assert coder.context_limit == 150_000


def test_write_runtime_config_bedrock_model_has_bedrock_provider(tmp_path: Path):
    coder = OpencodeCoder(
        model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )
    coder.write_runtime_config(tmp_path, _task())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    bedrock_entry = cfg["provider"]["amazon-bedrock"]
    assert bedrock_entry["name"] == "Amazon Bedrock"
    model_key = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert bedrock_entry["models"][model_key]["limit"]["context"] == 200_000
    assert bedrock_entry["models"][model_key]["tools"] is True
    assert "ollama-rtx" in cfg["provider"]


def test_write_runtime_config_bedrock_merges_existing_bedrock_entry(tmp_path: Path):
    existing = {
        "provider": {
            "amazon-bedrock": {
                "name": "Amazon Bedrock",
                "models": {
                    "us.anthropic.claude-3-5-sonnet-20241022-v2:0": {
                        "name": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
                        "tools": True,
                    }
                },
            }
        }
    }
    (tmp_path / "opencode.json").write_text(json.dumps(existing, indent=2))
    coder = OpencodeCoder(
        model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )
    coder.write_runtime_config(tmp_path, _task())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    bedrock_entry = cfg["provider"]["amazon-bedrock"]
    assert "us.anthropic.claude-3-5-sonnet-20241022-v2:0" in bedrock_entry["models"]
    assert "us.anthropic.claude-sonnet-4-5-20250929-v1:0" in bedrock_entry["models"]
    assert (
        bedrock_entry["models"]["us.anthropic.claude-sonnet-4-5-20250929-v1:0"][
            "limit"
        ]["context"]
        == 200_000
    )


def test_write_runtime_config_bedrock_not_added_for_ollama_model(tmp_path: Path):
    coder = OpencodeCoder(model="qwen3.6:latest")
    coder.write_runtime_config(tmp_path, _task())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    assert "amazon-bedrock" not in cfg.get("provider", {})


def test_write_runtime_config_bedrock_preserves_mcp_and_permission(tmp_path: Path):
    coder = OpencodeCoder(
        model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )
    coder.write_runtime_config(tmp_path, _task())
    cfg = json.loads((tmp_path / "opencode.json").read_text())
    assert "ask-human" in cfg["mcp"]
    assert cfg["permission"]["external_directory"] == "allow"


def test_non_bedrock_model_is_bedrock_false():
    coder = OpencodeCoder(model="qwen3.6:latest")
    assert coder.is_bedrock is False
    assert coder.context_limit == 128_000


def test_ollama_model_is_bedrock_false():
    coder = OpencodeCoder(model="ollama-rtx/qwen3.6:latest")
    assert coder.is_bedrock is False


def test_build_argv_bedrock_model_passed_verbatim(tmp_path: Path):
    coder = OpencodeCoder(
        model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )
    argv = coder.build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert (
        argv[idx + 1] == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )


# ------ tests for context_limit_for classmethod ------

def test_context_limit_for_bedrock_model():
    assert (
        OpencodeCoder.context_limit_for("amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
        
 == 200_000
    )


def test_context_limit_for_ollama_model():
    assert OpencodeCoder.context_limit_for("qwen3.6:latest") == 128_000


def test_context_limit_for_none_model():
    assert OpencodeCoder.context_limit_for(None) == 128_000
