"""Tests for opencode runtime config and providers (unit under test: coders/opencode.py config)."""

import json
from pathlib import Path

from fleet.coders.base import context_limit_for as spec_window
from fleet.coders.opencode import OpencodeCoder
from fleet.coders.settings import BedrockSettings, OpencodeSettings
from fleet.core.task import Task
from fleet.integrations.mcp_servers import fleet_mcp_servers
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


def _isolated_task_dir(tmp_path: Path, task_id: str, worktree: Path) -> Path:
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(
        json.dumps({"id": task_id, "cwd": "/repo/main", "worktree_path": str(worktree)})
    )
    return task_dir


def test_build_config_schema_and_provider():
    config = _coder()._build_config()
    assert config["$schema"] == "https://opencode.ai/config.json"
    assert "ollama-rtx" in config["provider"]


def test_build_config_provider_entry_structure():
    config = _coder()._build_config()
    entry = config["provider"]["ollama-rtx"]
    assert entry["npm"] == "@ai-sdk/openai-compatible"
    assert entry["name"] == "Ollama (rtx)"
    assert entry["options"]["baseURL"] == "http://127.0.0.1:11435/v1"
    assert "gpt-oss:20b" in entry["models"]
    assert entry["models"]["gpt-oss:20b"]["tools"] is True


def test_build_config_ollama_url_constructor():
    coder = _coder(settings=OpencodeSettings(ollama_url="http://127.0.0.1:12345/v1"))
    config = coder._build_config()
    assert config["provider"]["ollama-rtx"]["options"]["baseURL"] == "http://127.0.0.1:12345/v1"


def test_build_config_permission_block():
    config = _coder()._build_config()
    assert config["permission"] == {"external_directory": "allow"}


def test_build_config_mcp_matches_shared_definitions():
    """The ask-human/web_fetch entries must come from integrations.mcp_servers."""

    shared = fleet_mcp_servers(fleet_home())
    config = _coder()._build_config()
    ask_entry = config["mcp"]["ask-human"]
    assert ask_entry["command"] == [shared["ask_human"]["command"], *shared["ask_human"]["args"]]
    assert shared["ask_human"]["env"]["ASK_HUMAN_DB"] in repr(ask_entry)
    web_entry = config["mcp"]["web_fetch"]
    assert web_entry["command"] == [shared["web_fetch"]["command"], *shared["web_fetch"]["args"]]


def test_build_config_mcp_ask_human():
    entry = _coder()._build_config()["mcp"]["ask-human"]
    assert entry["type"] == "local"
    assert any("fleet.integrations.ask_human.server" in part for part in entry["command"])


def test_build_config_mcp_claude_code_available():
    entry = _coder()._build_config()["mcp"]["claude_code"]
    assert entry["enabled"] is True
    assert entry["type"] == "local"
    assert entry["command"][-1].endswith("claude_code/server.py")


def test_build_config_mcp_playwright_available():
    entry = _coder()._build_config()["mcp"]["playwright"]
    assert entry["enabled"] is True
    assert entry["type"] == "local"
    assert "@playwright/mcp@latest" in entry["command"]
    assert "--headless" in entry["command"]
    assert "--isolated" in entry["command"]


def test_build_config_mcp_web_fetch_available():
    config = _coder()._build_config()
    entry = config["mcp"]["web_fetch"]
    assert entry["enabled"] is True
    assert entry["type"] == "local"
    assert entry["command"][-1] == "fleet.integrations.web_fetch.server"
    assert entry["environment"]["FLEET_WEBFETCH_MODEL"]
    assert entry["environment"]["FLEET_WEBFETCH_OLLAMA_URL"]
    assert "ask-human" in config["mcp"]


def test_default_model_constructor_defaults_to_gpt_oss():
    coder = _coder()
    assert coder.model == "gpt-oss:20b"


def test_default_context_limit_constructor():
    coder = OpencodeCoder(fleet_home=fleet_home())
    assert coder.context_limit == 128_000


def test_build_argv_sonnet_with_custom_default_resolves_default():
    argv = _coder(model="sonnet", default_model="qwen3.5:27b").build_argv(_task(), Path("/tmp"))
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/qwen3.5:27b"


def test_build_argv_sonnet_with_gpt_oss_default_resolves_correctly():
    argv = _coder(model="sonnet", default_model="gpt-oss:20b").build_argv(_task(), Path("/tmp"))
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/gpt-oss:20b"


def test_build_argv_explicit_model_ignores_default():
    argv = _coder(model="deepseek-r1:32b", default_model="gpt-oss:20b").build_argv(
        _task(), Path("/tmp")
    )
    idx = argv.index("--model")
    assert argv[idx + 1] == "ollama-rtx/deepseek-r1:32b"


def test_context_limit_custom_value():
    coder = _coder(context_limit_override=256_000)
    assert coder.context_limit == 256_000


def test_build_config_uses_default_model_in_entry():
    coder = _coder(model="sonnet", default_model="qwen3.5:27b")
    entry = coder._build_config()["provider"]["ollama-rtx"]
    assert "qwen3.5:27b" in entry["models"]
    assert "gpt-oss:20b" not in entry["models"]


def test_build_config_model_has_limit_context():
    """limit.context must match the constructor's context_limit (default 128_000)."""
    coder = _coder()
    models = coder._build_config()["provider"]["ollama-rtx"]["models"]
    assert models[coder.model]["limit"]["context"] == 128_000


def test_build_config_limit_context_custom():
    """limit.context must reflect an explicit context_limit value (252_000)."""
    coder = _coder(context_limit_override=252_000)
    models = coder._build_config()["provider"]["ollama-rtx"]["models"]
    assert models[coder.model]["limit"]["context"] == 252_000


def test_build_config_limit_output_always_8192():
    """limit.output MUST always be 8192."""
    coder = _coder()
    models = coder._build_config()["provider"]["ollama-rtx"]["models"]
    assert models[coder.model]["limit"]["output"] == 8192


def test_build_config_limit_propagates_with_custom_model():
    """limit block is written when using a custom model and context_limit."""
    coder = _coder(model="qwen3.5:27b", context_limit_override=200_000)
    models = coder._build_config()["provider"]["ollama-rtx"]["models"]
    assert models["qwen3.5:27b"]["limit"]["context"] == 200_000
    assert models["qwen3.5:27b"]["limit"]["output"] == 8192


def test_bedrock_params_stored_on_instance():
    coder = _bedrock_coder("gpt-oss:20b", bedrock_context_limit=150_000)
    assert coder.settings.bedrock is not None
    assert coder.settings.bedrock.region == "us-east-1"
    assert coder.settings.bedrock.profile == "dev"
    # Default model is not a Bedrock model, so the bedrock compat kwarg is
    # inert: the window resolves for the actual model.
    assert coder.context_limit == 128_000


def test_bedrock_params_default_values():
    coder = _coder()
    assert coder.settings.bedrock is None
    # Default model is ollama gpt-oss: resolved per-model window, not bedrock's.
    assert coder.context_limit == 128_000


def test_bedrock_model_is_bedrock_true_and_context_limit():
    coder = _bedrock_coder("amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert coder.is_bedrock is True
    assert coder.context_limit == 200_000


def test_bedrock_model_with_custom_context_limit():
    coder = _bedrock_coder(
        "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        bedrock_context_limit=150_000,
    )
    assert coder.is_bedrock is True
    assert coder.context_limit == 150_000


def test_build_config_bedrock_model_has_bedrock_provider():
    coder = _coder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    config = coder._build_config()
    bedrock_entry = config["provider"]["amazon-bedrock"]
    assert bedrock_entry["name"] == "Amazon Bedrock"
    model_key = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert bedrock_entry["models"][model_key]["limit"]["context"] == 200_000
    assert bedrock_entry["models"][model_key]["tools"] is True
    assert "ollama-rtx" in config["provider"]


def test_build_config_bedrock_not_added_for_ollama_model():
    coder = _coder(model="qwen3.6:latest")
    config = coder._build_config()
    assert "amazon-bedrock" not in config.get("provider", {})


def test_build_config_bedrock_preserves_mcp_and_permission():
    coder = _coder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    config = coder._build_config()
    assert "ask-human" in config["mcp"]
    assert config["permission"]["external_directory"] == "allow"


def test_non_bedrock_model_is_bedrock_false():
    coder = _coder(model="qwen3.6:latest")
    assert coder.is_bedrock is False
    assert coder.context_limit == 65_000


def test_ollama_model_is_bedrock_false():
    coder = _coder(model="ollama-rtx/qwen3.6:latest")
    assert coder.is_bedrock is False


def test_build_argv_bedrock_model_passed_verbatim(tmp_path: Path):
    coder = _coder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    argv = coder.build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_context_limit_for_bedrock_model():
    model = "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert spec_window(OpencodeCoder.spec, model) == 200_000


def test_context_limit_for_ollama_model():
    assert spec_window(OpencodeCoder.spec, "qwen3.6:latest") == 65_000


def test_context_limit_for_none_model():
    assert spec_window(OpencodeCoder.spec, None) == 128_000


def test_build_argv_dir_flag_follows_the_isolated_worktree(tmp_path: Path) -> None:
    """Regression (fleet-o5xr2): `--dir` pointed at the original repo while the
    process ran in the worktree, so resumed attempts edited the shared tree."""
    worktree = tmp_path / "worktrees" / "repo-t-iso"
    task = Task(id="t-iso", title="t", description="d", status="open", cwd="/repo/main")
    task_dir = _isolated_task_dir(tmp_path, task.id, worktree)

    argv = _coder().build_argv(task, task_dir)

    assert argv[argv.index("--dir") + 1] == str(worktree)
    prompt = argv[-1]
    assert f"Invocation directory: {worktree}" in prompt
    assert f"checked out at\n> `{worktree}`" in prompt
    assert "{worktree_path}" not in prompt


def test_build_argv_dir_flag_uses_cwd_when_not_isolated(tmp_path: Path) -> None:
    task = Task(id="t-plain", title="t", description="d", status="open", cwd="/repo/main")
    task_dir = tmp_path / "tasks" / task.id
    task_dir.mkdir(parents=True)

    argv = _coder().build_argv(task, task_dir)

    assert argv[argv.index("--dir") + 1] == "/repo/main"
    assert "Isolation mode" not in argv[-1]
