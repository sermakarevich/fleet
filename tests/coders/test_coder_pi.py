import json
from pathlib import Path

import pytest

from fleet.coders.base import Coder
from fleet.coders import get_coder, list_coders
from fleet.coders.pi import (
    PiCoder,
    _map_usage,
    _pi_agent_dir,
    _resolve_model,
)
from fleet.core.task import Task


def _coder(**kwargs) -> PiCoder:
    return PiCoder(**kwargs)


def _task(task_id: str = "test-001", cwd: str | None = None) -> Task:
    return Task(
        id=task_id,
        title="Test task",
        description="Do the thing.",
        status="in_progress",
        cwd=cwd,
    )


def _agent_dir(monkeypatch, tmp_path: Path) -> Path:
    """Point pi's global agent dir at tmp_path; return it."""
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path))
    return tmp_path


def _read_models(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "models.json").read_text())


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_get_coder_returns_pi_class():
    assert get_coder("pi") is PiCoder


def test_pi_in_list_coders():
    names = [c["name"] for c in list_coders()]
    assert "pi" in names


def test_pi_coder_is_subclass_of_coder_base():
    assert issubclass(PiCoder, Coder)


# ---------------------------------------------------------------------------
# _resolve_model — provider id is "ollama", bare names get "ollama/" prefix
# ---------------------------------------------------------------------------


def test_resolve_model_bare_name_gets_ollama_prefix():
    full_id, local_key = _resolve_model("qwen3.6:latest", "qwen3.6:latest")
    assert full_id == "ollama/qwen3.6:latest"
    assert local_key == "qwen3.6:latest"


def test_resolve_model_bare_custom_name_gets_ollama_prefix():
    full_id, local_key = _resolve_model("qwen3.5:27b", "qwen3.6:latest")
    assert full_id == "ollama/qwen3.5:27b"
    assert local_key == "qwen3.5:27b"


def test_resolve_model_with_slash_used_as_is():
    full_id, local_key = _resolve_model(
        "ollama/deepseek-r1:32b", "qwen3.6:latest"
    )
    assert full_id == "ollama/deepseek-r1:32b"
    assert local_key == "deepseek-r1:32b"


def test_resolve_model_bedrock_id_used_as_is():
    full_id, local_key = _resolve_model(
        "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "qwen3.6:latest",
    )
    assert full_id == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert local_key == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_resolve_model_sonnet_alias_maps_to_default():
    full_id, local_key = _resolve_model("sonnet", "qwen3.6:latest")
    assert full_id == "ollama/qwen3.6:latest"
    assert local_key == "qwen3.6:latest"


def test_resolve_model_opus_alias_maps_to_default():
    full_id, local_key = _resolve_model("opus", "qwen3.6:latest")
    assert full_id == "ollama/qwen3.6:latest"


def test_resolve_model_haiku_alias_maps_to_default():
    full_id, local_key = _resolve_model("haiku", "qwen3.6:latest")
    assert full_id == "ollama/qwen3.6:latest"


def test_resolve_model_alias_uses_custom_default():
    full_id, local_key = _resolve_model("sonnet", "qwen3.5:27b")
    assert full_id == "ollama/qwen3.5:27b"
    assert local_key == "qwen3.5:27b"


def test_resolve_model_explicit_bare_ignores_default():
    full_id, _ = _resolve_model("deepseek-r1:32b", "qwen3.6:latest")
    assert full_id == "ollama/deepseek-r1:32b"


# ---------------------------------------------------------------------------
# _map_usage — pi usage keys mapped to fleet usage dict
# ---------------------------------------------------------------------------


def test_map_usage_full_block():
    usage = _map_usage({"input": 10, "output": 5, "cacheWrite": 2, "cacheRead": 3})
    assert usage == {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_creation_input_tokens": 2,
        "cache_read_input_tokens": 3,
    }


def test_map_usage_missing_keys_default_to_zero():
    usage = _map_usage({})
    assert usage == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def test_map_usage_partial_block():
    usage = _map_usage({"input": 100, "output": 7})
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 7
    assert usage["cache_creation_input_tokens"] == 0
    assert usage["cache_read_input_tokens"] == 0


def test_map_usage_non_dict_returns_none():
    assert _map_usage(None) is None
    assert _map_usage("nope") is None
    assert _map_usage([1, 2]) is None


# ---------------------------------------------------------------------------
# _pi_agent_dir — honours PI_CODING_AGENT_DIR
# ---------------------------------------------------------------------------


def test_pi_agent_dir_uses_env_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path))
    assert _pi_agent_dir() == tmp_path


def test_pi_agent_dir_default_is_home_pi_agent(monkeypatch):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    assert _pi_agent_dir() == Path.home() / ".pi" / "agent"


# ---------------------------------------------------------------------------
# build_argv — ["pi", "-p", "--mode", "json", "--model", full_id, prompt]
# ---------------------------------------------------------------------------


def test_build_argv_head_is_pi_dash_p_mode_json(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert argv[0:4] == ["pi", "-p", "--mode", "json"]


def test_build_argv_has_exactly_seven_elements(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert len(argv) == 7


def test_build_argv_has_no_run_subcommand(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert "run" not in argv


def test_build_argv_has_no_format_flag(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert "--format" not in argv


def test_build_argv_has_no_dir_flag_even_with_cwd(tmp_path: Path):
    task = _task(cwd="/Users/me/project")
    argv = _coder().build_argv(task, tmp_path)
    assert "--dir" not in argv


def test_build_argv_model_flag_defaults_to_ollama_prefixed(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/qwen3.6:latest"


def test_build_argv_uses_custom_bare_model_with_ollama_prefix(tmp_path: Path):
    argv = PiCoder(model="qwen3.5:27b").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/qwen3.5:27b"


def test_build_argv_full_provider_model_passed_verbatim(tmp_path: Path):
    argv = PiCoder(model="ollama/deepseek-r1:32b").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/deepseek-r1:32b"


def test_build_argv_sonnet_alias_resolved_to_default(tmp_path: Path):
    argv = PiCoder(model="sonnet").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/qwen3.6:latest"


def test_build_argv_opus_alias_resolved_to_default(tmp_path: Path):
    argv = PiCoder(model="opus").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/qwen3.6:latest"


def test_build_argv_haiku_alias_resolved_to_default(tmp_path: Path):
    argv = PiCoder(model="haiku").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/qwen3.6:latest"


def test_build_argv_sonnet_with_custom_default_resolves_custom(tmp_path: Path):
    argv = PiCoder(model="sonnet", default_model="qwen3.5:27b").build_argv(
        _task(), tmp_path
    )
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/qwen3.5:27b"


def test_build_argv_explicit_bare_model_ignores_default(tmp_path: Path):
    argv = PiCoder(model="deepseek-r1:32b", default_model="qwen3.6:latest").build_argv(
        _task(), tmp_path
    )
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/deepseek-r1:32b"


def test_build_argv_model_is_second_to_last_element(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert argv[-2] == "ollama/qwen3.6:latest"
    assert argv[-3] == "--model"


def test_build_argv_prompt_is_last_element(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert isinstance(argv[-1], str)
    assert len(argv[-1]) > 0


def test_build_argv_cwd_embedded_in_prompt_not_flag(tmp_path: Path):
    task = _task(cwd="/Users/me/project")
    argv = _coder().build_argv(task, tmp_path)
    assert "--dir" not in argv
    assert "Invocation directory: /Users/me/project" in argv[-1]


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
    assert "fleet bd close" in prompt


def test_build_argv_includes_invocation_line_when_cwd_set(tmp_path: Path):
    task = _task(cwd="/Users/me/project-x")
    prompt = _coder().build_argv(task, tmp_path)[-1]
    assert "Invocation directory: /Users/me/project-x" in prompt


def test_build_argv_omits_invocation_line_when_no_cwd(tmp_path: Path):
    prompt = _coder().build_argv(_task(), tmp_path)[-1]
    assert "Invocation directory:" not in prompt


def test_default_model_of_class():
    assert _coder().model == "qwen3.6:latest"
    assert PiCoder.default_model == "qwen3.6:latest"


def test_build_argv_bedrock_model_passed_verbatim(tmp_path: Path):
    coder = PiCoder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    argv = coder.build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert (
        argv[idx + 1] == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )


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
    coder = PiCoder(
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
    coder = PiCoder(
        model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )
    env = coder.env(_task(), tmp_path)
    assert "AWS_PROFILE" not in env
    assert "AWS_REGION" not in env


def test_env_ollama_model_no_aws_keys_even_with_bedrock_config(tmp_path: Path):
    coder = PiCoder(
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
    assert "Do NOT run `fleet bd close`" in prompt


def test_build_argv_without_worktree_marker_excludes_isolation_protocol(tmp_path: Path):
    """Without a .worktree marker, the prompt must NOT contain the isolation block."""
    argv = _coder().build_argv(_task(), tmp_path)
    prompt = argv[-1]
    assert "Do NOT run `fleet bd close`" not in prompt


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


def test_normalize_event_agent_start_returns_none():
    assert _coder().normalize_event('{"type":"agent_start"}') is None


def test_normalize_event_turn_start_returns_none():
    assert _coder().normalize_event('{"type":"turn_start"}') is None


def test_normalize_event_message_update_returns_none():
    line = json.dumps({"type": "message_update", "delta": {"text": "hi"}})
    assert _coder().normalize_event(line) is None


# ---------------------------------------------------------------------------
# normalize_event — session
# ---------------------------------------------------------------------------


def test_normalize_session_is_session_started_with_id():
    line = json.dumps({"type": "session", "id": "ses_abc123", "cwd": "/tmp"})
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.kind == "session_started"
    assert evt.session_id == "ses_abc123"


# ---------------------------------------------------------------------------
# normalize_event — message_end
# ---------------------------------------------------------------------------


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
            "message": {"role": "assistant", "stopReason": "length",
                        "usage": {"input": 131000, "output": 72}},
        }
    )
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.kind == "error"


def test_normalize_message_end_user_role_returns_none():
    line = json.dumps(
        {"type": "message_end", "message": {"role": "user", "content": "hi"}}
    )
    assert _coder().normalize_event(line) is None


def test_normalize_message_end_tool_role_returns_none():
    line = json.dumps(
        {"type": "message_end", "message": {"role": "toolResult", "content": "out"}}
    )
    assert _coder().normalize_event(line) is None


def test_normalize_message_end_missing_message_returns_none():
    assert _coder().normalize_event('{"type":"message_end"}') is None


# ---------------------------------------------------------------------------
# normalize_event — tool execution
# ---------------------------------------------------------------------------


def test_normalize_tool_execution_start_is_tool_use():
    line = json.dumps({"type": "tool_execution_start", "toolName": "write"})
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.kind == "tool_use"
    assert evt.tool_name == "write"


def test_normalize_tool_execution_end_is_tool_result():
    line = json.dumps(
        {"type": "tool_execution_end", "toolName": "write", "isError": False}
    )
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
    line = json.dumps(
        {"type": "tool_execution_end", "toolName": "write", "isError": True}
    )
    evt = _coder().normalize_event(line)
    assert evt is not None
    assert evt.kind == "error"
    assert evt.tool_name == "write"


# ---------------------------------------------------------------------------
# normalize_event — agent_end / error
# ---------------------------------------------------------------------------


def test_normalize_agent_end_is_session_ended():
    evt = _coder().normalize_event('{"type":"agent_end"}')
    assert evt is not None
    assert evt.kind == "session_ended"


def test_normalize_error_type_is_error():
    evt = _coder().normalize_event('{"type":"error","message":"boom"}')
    assert evt is not None
    assert evt.kind == "error"


# ---------------------------------------------------------------------------
# write_runtime_config — writes models.json into PI_CODING_AGENT_DIR
# ---------------------------------------------------------------------------


def test_write_runtime_config_creates_models_json_in_agent_dir(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    _coder().write_runtime_config(tmp_path / "project", _task())
    target = tmp_path / "models.json"
    assert target.exists()
    data = json.loads(target.read_text())
    assert "ollama" in data["providers"]


def test_write_runtime_config_does_not_write_project_pi_json(
    monkeypatch, tmp_path: Path
):
    agent_dir = tmp_path / "agent"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_dir))
    _coder().write_runtime_config(project, _task())
    assert not (project / "pi.json").exists()
    assert (agent_dir / "models.json").exists()


def test_write_runtime_config_ollama_provider_entry_structure(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    _coder().write_runtime_config(tmp_path, _task())
    entry = _read_models(tmp_path)["providers"]["ollama"]
    assert entry["baseUrl"] == "http://127.0.0.1:11435/v1"
    assert entry["api"] == "openai-completions"
    assert entry["apiKey"] == "ollama"
    assert entry["compat"]["supportsDeveloperRole"] is False
    assert entry["compat"]["supportsReasoningEffort"] is False
    assert {"id": "qwen3.6:latest"} in entry["models"]


def test_write_runtime_config_models_is_list_of_id_dicts(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    _coder().write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert isinstance(models, list)
    assert all(set(m.keys()) == {"id"} for m in models)


def test_write_runtime_config_default_model_sonnet_alias_in_models(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    coder = PiCoder(model="sonnet", default_model="qwen3.6:latest")
    coder.write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert {"id": "qwen3.6:latest"} in models


def test_write_runtime_config_custom_default_used_for_alias(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    coder = PiCoder(model="sonnet", default_model="qwen3.5:27b")
    coder.write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert {"id": "qwen3.5:27b"} in models
    assert {"id": "qwen3.6:latest"} not in models


def test_write_runtime_config_ollama_url_constructor(monkeypatch, tmp_path: Path):
    _agent_dir(monkeypatch, tmp_path)
    coder = PiCoder(ollama_url="http://127.0.0.1:12345/v1")
    coder.write_runtime_config(tmp_path, _task())
    cfg = _read_models(tmp_path)
    assert (
        cfg["providers"]["ollama"]["baseUrl"] == "http://127.0.0.1:12345/v1"
    )


def test_write_runtime_config_preserves_foreign_top_level_keys(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    (tmp_path / "models.json").write_text(json.dumps({"theme": "dark"}))
    _coder().write_runtime_config(tmp_path, _task())
    data = _read_models(tmp_path)
    assert data.get("theme") == "dark"
    assert "ollama" in data["providers"]


def test_write_runtime_config_preserves_other_providers(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    existing = {"providers": {"mine": {"baseUrl": "http://x", "models": []}}}
    (tmp_path / "models.json").write_text(json.dumps(existing, indent=2))
    _coder().write_runtime_config(tmp_path, _task())
    data = _read_models(tmp_path)
    assert "mine" in data["providers"]
    assert "ollama" in data["providers"]


def test_write_runtime_config_merges_models_without_clobbering(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    existing = {
        "providers": {"ollama": {"baseUrl": "http://old", "models": [{"id": "other-model"}]}}
    }
    (tmp_path / "models.json").write_text(json.dumps(existing, indent=2))
    _coder().write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert {"id": "other-model"} in models
    assert {"id": "qwen3.6:latest"} in models


def test_write_runtime_config_does_not_duplicate_model_id(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    _coder().write_runtime_config(tmp_path, _task())
    _coder().write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    ids = [m["id"] for m in models]
    assert ids.count("qwen3.6:latest") == 1


def test_write_runtime_config_tolerates_corrupted_json(monkeypatch, tmp_path: Path):
    _agent_dir(monkeypatch, tmp_path)
    (tmp_path / "models.json").write_text("{not valid json!!")
    _coder().write_runtime_config(tmp_path, _task())
    data = _read_models(tmp_path)
    assert "ollama" in data["providers"]


def test_write_runtime_config_tolerates_non_dict_json(monkeypatch, tmp_path: Path):
    _agent_dir(monkeypatch, tmp_path)
    (tmp_path / "models.json").write_text("[1,2,3]")
    _coder().write_runtime_config(tmp_path, _task())
    data = _read_models(tmp_path)
    assert "ollama" in data["providers"]


def test_write_runtime_config_tolerates_non_list_models(monkeypatch, tmp_path: Path):
    _agent_dir(monkeypatch, tmp_path)
    existing = {"providers": {"ollama": {"models": {"id": "weird"}}}}
    (tmp_path / "models.json").write_text(json.dumps(existing))
    _coder().write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert {"id": "qwen3.6:latest"} in models


def test_write_runtime_config_idempotent(monkeypatch, tmp_path: Path):
    _agent_dir(monkeypatch, tmp_path)
    _coder().write_runtime_config(tmp_path, _task())
    first = (tmp_path / "models.json").read_bytes()
    _coder().write_runtime_config(tmp_path, _task())
    second = (tmp_path / "models.json").read_bytes()
    assert first == second


def test_write_runtime_config_no_tmp_file_left_behind(monkeypatch, tmp_path: Path):
    _agent_dir(monkeypatch, tmp_path)
    _coder().write_runtime_config(tmp_path, _task())
    assert not (tmp_path / "models.json.tmp").exists()


def test_write_runtime_config_writes_no_mcp_block(monkeypatch, tmp_path: Path):
    _agent_dir(monkeypatch, tmp_path)
    _coder().write_runtime_config(tmp_path, _task())
    assert "mcp" not in _read_models(tmp_path)


def test_write_runtime_config_writes_no_permission_block(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    _coder().write_runtime_config(tmp_path, _task())
    assert "permission" not in _read_models(tmp_path)


def test_write_runtime_config_writes_no_schema_key(monkeypatch, tmp_path: Path):
    _agent_dir(monkeypatch, tmp_path)
    _coder().write_runtime_config(tmp_path, _task())
    assert "$schema" not in _read_models(tmp_path)


def test_write_runtime_config_custom_model_entry(monkeypatch, tmp_path: Path):
    _agent_dir(monkeypatch, tmp_path)
    coder = PiCoder(model="qwen3.5:27b")
    coder.write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert {"id": "qwen3.5:27b"} in models


# ---------------------------------------------------------------------------
# write_runtime_config — bedrock is not configured for pi
# ---------------------------------------------------------------------------


def test_write_runtime_config_bedrock_model_writes_no_file(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    coder = PiCoder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    coder.write_runtime_config(tmp_path, _task())
    assert not (tmp_path / "models.json").exists()


def test_write_runtime_config_bedrock_leaves_existing_file_untouched(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    existing = {"providers": {"ollama": {"models": [{"id": "qwen3.6:latest"}]}}}
    (tmp_path / "models.json").write_text(json.dumps(existing, indent=2))
    before = (tmp_path / "models.json").read_bytes()
    coder = PiCoder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    coder.write_runtime_config(tmp_path, _task())
    assert (tmp_path / "models.json").read_bytes() == before


def test_write_runtime_config_ollama_model_writes_no_bedrock_provider(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    PiCoder(model="qwen3.6:latest").write_runtime_config(tmp_path, _task())
    providers = _read_models(tmp_path)["providers"]
    assert "amazon-bedrock" not in providers


# ---------------------------------------------------------------------------
# constructor params / is_bedrock / context limits
# ---------------------------------------------------------------------------


def test_default_model_constructor_value():
    coder = PiCoder()
    assert coder.model == "qwen3.6:latest"


def test_default_context_limit_constructor():
    coder = PiCoder()
    assert coder.context_limit == 65_000


def test_build_argv_context_limit_default():
    coder = PiCoder()
    assert coder.context_limit == 65_000


def test_build_argv_context_limit_custom():
    coder = PiCoder(context_limit=64_000)
    assert coder.context_limit == 64_000


def test_context_limit_custom_value():
    coder = PiCoder(context_limit=256_000)
    assert coder.context_limit == 256_000


def test_bedrock_params_stored_on_instance():
    coder = PiCoder(
        bedrock_region="us-east-1", bedrock_profile="dev", bedrock_context_limit=150_000
    )
    assert coder.bedrock_region == "us-east-1"
    assert coder.bedrock_profile == "dev"
    # Default model is not a Bedrock model, so the bedrock compat kwarg is
    # inert: the window resolves for the actual model.
    assert coder.context_limit == 65_000


def test_bedrock_params_default_values():
    coder = PiCoder()
    assert coder.bedrock_region == ""
    assert coder.bedrock_profile == ""
    # Default model is ollama qwen: resolved per-model window, not bedrock's.
    assert coder.context_limit == 65_000


def test_bedrock_model_is_bedrock_true_and_context_limit():
    coder = PiCoder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert coder.is_bedrock is True
    assert coder.context_limit == 200_000


def test_bedrock_model_with_custom_context_limit():
    coder = PiCoder(
        model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        bedrock_context_limit=150_000,
    )
    assert coder.is_bedrock is True
    assert coder.context_limit == 150_000


def test_non_bedrock_model_is_bedrock_false():
    coder = PiCoder(model="qwen3.6:latest")
    assert coder.is_bedrock is False
    assert coder.context_limit == 65_000


def test_ollama_prefixed_model_is_bedrock_false():
    coder = PiCoder(model="ollama/qwen3.6:latest")
    assert coder.is_bedrock is False


def test_context_limit_for_bedrock_model():
    assert (
        PiCoder.context_limit_for(
            "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        )
        == 200_000
    )


def test_context_limit_for_ollama_model():
    assert PiCoder.context_limit_for("qwen3.6:latest") == 65_000


def test_context_limit_for_ollama_prefixed_model():
    assert PiCoder.context_limit_for("ollama/qwen3.6:latest") == 65_000


def test_context_limit_for_none_model():
    assert PiCoder.context_limit_for(None) == 128_000


def test_bedrock_kwargs_accepted_but_inert_for_ollama_routing(
    monkeypatch, tmp_path: Path
):
    _agent_dir(monkeypatch, tmp_path)
    coder = PiCoder(
        model="qwen3.6:latest",
        bedrock_region="us-east-1",
        bedrock_profile="dev",
    )
    argv = coder.build_argv(_task(), tmp_path)
    assert argv[argv.index("--model") + 1] == "ollama/qwen3.6:latest"
    coder.write_runtime_config(tmp_path, _task())
    assert "ollama" in _read_models(tmp_path)["providers"]


def test_write_runtime_config_creates_agent_dir_recursively(
    monkeypatch, tmp_path: Path
):
    nested = tmp_path / "a" / "b"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(nested))
    _coder().write_runtime_config(tmp_path, _task())
    assert (nested / "models.json").exists()


@pytest.mark.parametrize("alias", ["sonnet", "opus", "haiku"])
def test_build_argv_claude_aliases_all_resolve_to_default(
    tmp_path: Path, alias: str
):
    argv = PiCoder(model=alias).build_argv(_task(), tmp_path)
    assert argv[argv.index("--model") + 1] == "ollama/qwen3.6:latest"
