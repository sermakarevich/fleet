"""Tests for the Pi coder CLI shape (unit under test: coders/pi.py argv and env)."""

import os
from pathlib import Path

from fleet.coders.pi import PiCoder
from fleet.coders.settings import PiSettings, settings_from_env
from fleet.state.paths import fleet_home
from tests.coders.conftest import _bedrock_coder, _task


def _coder(agent_dir: Path | None = None, **kwargs) -> PiCoder:
    """Build PiCoder with an explicit agent dir (no env reads inside the coder)."""
    if agent_dir is not None and "settings" not in kwargs:
        kwargs["settings"] = PiSettings(agent_dir=agent_dir)
    kwargs.setdefault("fleet_home", fleet_home())
    return PiCoder(**kwargs)


def test_agent_dir_uses_env_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path))
    assert settings_from_env(os.environ).pi_agent_dir == tmp_path


def test_agent_dir_default_is_home_pi_agent(monkeypatch):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    assert settings_from_env(os.environ).pi_agent_dir == Path.home() / ".pi" / "agent"


def test_agent_dir_flows_into_write_runtime_config(monkeypatch, tmp_path: Path):
    """The env override reaches the coder through settings, never os.environ."""
    nested = tmp_path / "a" / "b"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(nested))
    env = settings_from_env(os.environ)
    _coder(settings=PiSettings(agent_dir=env.pi_agent_dir)).write_runtime_config(tmp_path, _task())
    assert (nested / "models.json").exists()


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
    argv = _coder(model="qwen3.5:27b").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/qwen3.5:27b"


def test_build_argv_full_provider_model_passed_verbatim(tmp_path: Path):
    argv = _coder(model="ollama/deepseek-r1:32b").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/deepseek-r1:32b"


def test_build_argv_sonnet_alias_resolved_to_default(tmp_path: Path):
    argv = _coder(model="sonnet").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/qwen3.6:latest"


def test_build_argv_opus_alias_resolved_to_default(tmp_path: Path):
    argv = _coder(model="opus").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/qwen3.6:latest"


def test_build_argv_haiku_alias_resolved_to_default(tmp_path: Path):
    argv = _coder(model="haiku").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/qwen3.6:latest"


def test_build_argv_sonnet_with_custom_default_resolves_custom(tmp_path: Path):
    argv = _coder(model="sonnet", default_model="qwen3.5:27b").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama/qwen3.5:27b"


def test_build_argv_explicit_bare_model_ignores_default(tmp_path: Path):
    argv = _coder(model="deepseek-r1:32b", default_model="qwen3.6:latest").build_argv(
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
    coder = _coder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    argv = coder.build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_env_includes_required_vars(tmp_path: Path):
    env = _coder().env(_task("t-42"), tmp_path)
    assert env["FLEET_TASK_ID"] == "t-42"
    assert env["FLEET_TASK_DIR"] == str(tmp_path)


def test_env_exactly_two_keys(tmp_path: Path):
    env = _coder().env(_task(), tmp_path)
    assert set(env.keys()) == {"FLEET_TASK_ID", "FLEET_TASK_DIR"}


def test_env_bedrock_injects_aws_profile_and_region(tmp_path: Path):
    coder = _bedrock_coder("amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    env = coder.env(_task("t-42"), tmp_path)
    assert env["AWS_PROFILE"] == "dev"
    assert env["AWS_REGION"] == "us-east-1"
    assert env["FLEET_TASK_ID"] == "t-42"
    assert env["FLEET_TASK_DIR"] == str(tmp_path)


def test_env_bedrock_empty_config_no_aws_keys(tmp_path: Path):
    coder = _coder(
        model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )
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
