"""Tests for the opencode coder CLI shape (unit under test: coders/opencode.py argv and env)."""

import json
from pathlib import Path

from fleet.coders import get_coder, list_coders
from fleet.coders.base import CoderSpec
from fleet.coders.opencode import OpencodeCoder
from fleet.coders.settings import BedrockSettings, OpencodeSettings
from fleet.core.task import Task
from fleet.state.paths import fleet_home


def _coder(**kwargs) -> OpencodeCoder:
    kwargs.setdefault("fleet_home", fleet_home())
    return OpencodeCoder(**kwargs)


def _bedrock_coder(model: str, **kwargs) -> OpencodeCoder:
    """OpencodeCoder routed to Bedrock with a dev profile/region by default."""
    bedrock = BedrockSettings(
        profile=kwargs.pop("bedrock_profile", "dev"),
        region=kwargs.pop("bedrock_region", "us-east-1"),
        context_limit=kwargs.pop("bedrock_context_limit", None),
    )
    settings = kwargs.pop("settings", OpencodeSettings(bedrock=bedrock))
    kwargs.setdefault("fleet_home", fleet_home())
    return _coder(model=model, settings=settings, **kwargs)


def _task(task_id: str = "test-001", cwd: str | None = None) -> Task:
    return Task(
        id=task_id,
        title="Test task",
        description="Do the thing.",
        status="in_progress",
        cwd=cwd,
    )


def test_get_coder_returns_opencode_class():
    assert get_coder("opencode") is OpencodeCoder


def test_opencode_in_list_coders():
    names = [c["name"] for c in list_coders()]
    assert "opencode" in names


def test_opencode_spec_names_registry_entry():
    assert isinstance(OpencodeCoder.spec, CoderSpec)
    assert OpencodeCoder.spec.name == "opencode"
    assert OpencodeCoder.spec.context_limit == 128_000
    assert OpencodeCoder.spec.default_model == "gpt-oss:20b"


def test_build_argv_context_limit_default():
    coder = OpencodeCoder(fleet_home=fleet_home())
    assert coder.context_limit == 128_000


def test_build_argv_context_limit_custom():
    coder = OpencodeCoder(fleet_home=fleet_home(), context_limit_override=64_000)
    assert coder.context_limit == 64_000


def test_build_argv_default_model_custom_resolves_sonet():
    # When default_model is "qwen3.6:latest", sonnet alias should resolve to it
    argv = _coder(model="sonnet", default_model="qwen3.6:latest").build_argv(_task(), Path("/tmp"))
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/qwen3.6:latest"


def test_build_argv_default_model_custom_used_directly():
    # When default_model is a full provider model, it's used as-is
    argv = _coder(model="qwen3.6:latest", default_model="qwen3.6:latest").build_argv(
        _task(), Path("/tmp")
    )
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/qwen3.6:latest"


def test_build_config_default_model_in_provider_models():
    coder = _coder(model="sonnet", default_model="qwen3.6:latest")
    config = coder._build_config()
    entry = config["provider"]["ollama-rtx"]
    assert "qwen3.6:latest" in entry["models"]


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
    argv = _coder(model="qwen3.5:27b").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/qwen3.5:27b"


def test_build_argv_full_provider_model_passed_verbatim(tmp_path: Path):
    argv = _coder(model="ollama-rtx/deepseek-r1:32b").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/deepseek-r1:32b"


def test_build_argv_sonnet_alias_resolved_to_default(tmp_path: Path):
    argv = _coder(model="sonnet").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/gpt-oss:20b"


def test_build_argv_opus_alias_resolved_to_default(tmp_path: Path):
    argv = _coder(model="opus").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/gpt-oss:20b"


def test_build_argv_haiku_alias_resolved_to_default(tmp_path: Path):
    argv = _coder(model="haiku").build_argv(_task(), tmp_path)
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
    assert "fleet bd close" in prompt


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


def test_env_includes_required_vars(tmp_path: Path):
    env = _coder().env(_task("t-42"), tmp_path)
    assert env["FLEET_TASK_ID"] == "t-42"
    assert env["FLEET_TASK_DIR"] == str(tmp_path)


def test_env_keys_ollama(tmp_path: Path):
    env = _coder().env(_task(), tmp_path)
    assert set(env.keys()) == {
        "FLEET_TASK_ID",
        "FLEET_TASK_DIR",
        "OPENCODE_CONFIG_CONTENT",
    }


def test_env_config_content_is_valid_json_with_provider(tmp_path: Path):
    env = _coder().env(_task(), tmp_path)
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert "ollama-rtx" in config["provider"]
    assert config["$schema"] == "https://opencode.ai/config.json"


def test_env_does_not_write_opencode_json(tmp_path: Path):
    coder = _coder()
    coder.env(_task(), tmp_path)
    assert not (tmp_path / "opencode.json").exists()


def test_env_bedrock_injects_aws_profile_and_region(tmp_path: Path):
    coder = _bedrock_coder("amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    env = coder.env(_task("t-42"), tmp_path)
    assert env["AWS_PROFILE"] == "dev"
    assert env["AWS_REGION"] == "us-east-1"
    assert env["FLEET_TASK_ID"] == "t-42"
    assert env["FLEET_TASK_DIR"] == str(tmp_path)


def test_env_bedrock_empty_config_no_aws_keys(tmp_path: Path):
    coder = _coder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    env = coder.env(_task(), tmp_path)
    assert "AWS_PROFILE" not in env
    assert "AWS_REGION" not in env


def test_env_ollama_model_no_aws_keys_even_with_bedrock_config(tmp_path: Path):
    coder = _bedrock_coder("qwen3.6:latest")
    env = coder.env(_task(), tmp_path)
    assert "AWS_PROFILE" not in env
    assert "AWS_REGION" not in env


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
