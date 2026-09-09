"""Tests for Pi runtime config and provider routing (unit under test: coders/pi.py config)."""

import json
from pathlib import Path

import pytest

from fleet.coders.base import context_limit_for as spec_window
from fleet.coders.pi import PiCoder
from fleet.coders.settings import PiSettings
from fleet.state.paths import fleet_home
from tests.coders.conftest import _bedrock_coder, _task


def _coder(agent_dir: Path | None = None, **kwargs) -> PiCoder:
    """Build PiCoder with an explicit agent dir (no env reads inside the coder)."""
    if agent_dir is not None and "settings" not in kwargs:
        kwargs["settings"] = PiSettings(agent_dir=agent_dir)
    kwargs.setdefault("fleet_home", fleet_home())
    return PiCoder(**kwargs)


def _read_models(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "models.json").read_text())


def test_write_runtime_config_creates_models_json_in_agent_dir(monkeypatch, tmp_path: Path):
    _coder(tmp_path).write_runtime_config(tmp_path / "project", _task())
    target = tmp_path / "models.json"
    assert target.exists()
    data = json.loads(target.read_text())
    assert "ollama" in data["providers"]


def test_write_runtime_config_does_not_write_project_pi_json(monkeypatch, tmp_path: Path):
    agent_dir = tmp_path / "agent"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_dir))
    _coder(agent_dir).write_runtime_config(project, _task())
    assert not (project / "pi.json").exists()
    assert (agent_dir / "models.json").exists()


def test_write_runtime_config_ollama_provider_entry_structure(monkeypatch, tmp_path: Path):
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    entry = _read_models(tmp_path)["providers"]["ollama"]
    assert entry["baseUrl"] == "http://127.0.0.1:11435/v1"
    assert entry["api"] == "openai-completions"
    assert entry["apiKey"] == "ollama"
    assert entry["compat"]["supportsDeveloperRole"] is False
    assert entry["compat"]["supportsReasoningEffort"] is False
    assert {"id": "qwen3.6:latest"} in entry["models"]


def test_write_runtime_config_models_is_list_of_id_dicts(monkeypatch, tmp_path: Path):
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert isinstance(models, list)
    assert all(set(m.keys()) == {"id"} for m in models)


def test_write_runtime_config_default_model_sonnet_alias_in_models(monkeypatch, tmp_path: Path):
    coder = _coder(model="sonnet", default_model="qwen3.6:latest", agent_dir=tmp_path)
    coder.write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert {"id": "qwen3.6:latest"} in models


def test_write_runtime_config_custom_default_used_for_alias(monkeypatch, tmp_path: Path):
    coder = _coder(model="sonnet", default_model="qwen3.5:27b", agent_dir=tmp_path)
    coder.write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert {"id": "qwen3.5:27b"} in models
    assert {"id": "qwen3.6:latest"} not in models


def test_write_runtime_config_ollama_url_constructor(monkeypatch, tmp_path: Path):
    coder = _coder(settings=PiSettings(agent_dir=tmp_path, ollama_url="http://127.0.0.1:12345/v1"))
    coder.write_runtime_config(tmp_path, _task())
    config = _read_models(tmp_path)
    assert config["providers"]["ollama"]["baseUrl"] == "http://127.0.0.1:12345/v1"


def test_write_runtime_config_preserves_foreign_top_level_keys(monkeypatch, tmp_path: Path):
    (tmp_path / "models.json").write_text(json.dumps({"theme": "dark"}))
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    data = _read_models(tmp_path)
    assert data.get("theme") == "dark"
    assert "ollama" in data["providers"]


def test_write_runtime_config_preserves_other_providers(monkeypatch, tmp_path: Path):
    existing = {"providers": {"mine": {"baseUrl": "http://x", "models": []}}}
    (tmp_path / "models.json").write_text(json.dumps(existing, indent=2))
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    data = _read_models(tmp_path)
    assert "mine" in data["providers"]
    assert "ollama" in data["providers"]


def test_write_runtime_config_merges_models_without_clobbering(monkeypatch, tmp_path: Path):
    existing = {
        "providers": {"ollama": {"baseUrl": "http://old", "models": [{"id": "other-model"}]}}
    }
    (tmp_path / "models.json").write_text(json.dumps(existing, indent=2))
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert {"id": "other-model"} in models
    assert {"id": "qwen3.6:latest"} in models


def test_write_runtime_config_does_not_duplicate_model_id(monkeypatch, tmp_path: Path):
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    ids = [m["id"] for m in models]
    assert ids.count("qwen3.6:latest") == 1


def test_write_runtime_config_tolerates_corrupted_json(monkeypatch, tmp_path: Path):
    (tmp_path / "models.json").write_text("{not valid json!!")
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    data = _read_models(tmp_path)
    assert "ollama" in data["providers"]


def test_write_runtime_config_tolerates_non_dict_json(monkeypatch, tmp_path: Path):
    (tmp_path / "models.json").write_text("[1,2,3]")
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    data = _read_models(tmp_path)
    assert "ollama" in data["providers"]


def test_write_runtime_config_tolerates_non_list_models(monkeypatch, tmp_path: Path):
    existing = {"providers": {"ollama": {"models": {"id": "weird"}}}}
    (tmp_path / "models.json").write_text(json.dumps(existing))
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert {"id": "qwen3.6:latest"} in models


def test_write_runtime_config_idempotent(monkeypatch, tmp_path: Path):
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    first = (tmp_path / "models.json").read_bytes()
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    second = (tmp_path / "models.json").read_bytes()
    assert first == second


def test_write_runtime_config_no_tmp_file_left_behind(monkeypatch, tmp_path: Path):
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    assert not (tmp_path / "models.json.tmp").exists()


def test_write_runtime_config_writes_no_mcp_block(monkeypatch, tmp_path: Path):
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    assert "mcp" not in _read_models(tmp_path)


def test_write_runtime_config_writes_no_permission_block(monkeypatch, tmp_path: Path):
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    assert "permission" not in _read_models(tmp_path)


def test_write_runtime_config_writes_no_schema_key(monkeypatch, tmp_path: Path):
    _coder(tmp_path).write_runtime_config(tmp_path, _task())
    assert "$schema" not in _read_models(tmp_path)


def test_write_runtime_config_custom_model_entry(monkeypatch, tmp_path: Path):
    coder = _coder(tmp_path, model="qwen3.5:27b")
    coder.write_runtime_config(tmp_path, _task())
    models = _read_models(tmp_path)["providers"]["ollama"]["models"]
    assert {"id": "qwen3.5:27b"} in models


def test_write_runtime_config_bedrock_model_writes_no_file(monkeypatch, tmp_path: Path):
    coder = _coder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    coder.write_runtime_config(tmp_path, _task())
    assert not (tmp_path / "models.json").exists()


def test_write_runtime_config_bedrock_leaves_existing_file_untouched(monkeypatch, tmp_path: Path):
    existing = {"providers": {"ollama": {"models": [{"id": "qwen3.6:latest"}]}}}
    (tmp_path / "models.json").write_text(json.dumps(existing, indent=2))
    before = (tmp_path / "models.json").read_bytes()
    coder = _coder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    coder.write_runtime_config(tmp_path, _task())
    assert (tmp_path / "models.json").read_bytes() == before


def test_write_runtime_config_ollama_model_writes_no_bedrock_provider(monkeypatch, tmp_path: Path):
    _coder(tmp_path, model="qwen3.6:latest").write_runtime_config(tmp_path, _task())
    providers = _read_models(tmp_path)["providers"]
    assert "amazon-bedrock" not in providers


def test_default_model_constructor_value():
    coder = _coder()
    assert coder.model == "qwen3.6:latest"


def test_default_context_limit_constructor():
    coder = _coder()
    assert coder.context_limit == 65_000


def test_build_argv_context_limit_default():
    coder = _coder()
    assert coder.context_limit == 65_000


def test_build_argv_context_limit_custom():
    coder = _coder(context_limit_override=64_000)
    assert coder.context_limit == 64_000


def test_context_limit_custom_value():
    coder = _coder(context_limit_override=256_000)
    assert coder.context_limit == 256_000


def test_bedrock_params_stored_on_instance():
    coder = _bedrock_coder("qwen3.6:latest", bedrock_context_limit=150_000)
    assert coder.settings.bedrock is not None
    assert coder.settings.bedrock.region == "us-east-1"
    assert coder.settings.bedrock.profile == "dev"
    # Default model is not a Bedrock model, so the bedrock compat kwarg is
    # inert: the window resolves for the actual model.
    assert coder.context_limit == 65_000


def test_bedrock_params_default_values():
    coder = _coder()
    assert coder.settings.bedrock is None
    # Default model is ollama qwen: resolved per-model window, not bedrock's.
    assert coder.context_limit == 65_000


def test_bedrock_model_is_bedrock_true_and_context_limit():
    coder = _coder(model="amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert coder.is_bedrock is True
    assert coder.context_limit == 200_000


def test_bedrock_model_with_custom_context_limit():
    coder = _bedrock_coder(
        "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        bedrock_context_limit=150_000,
    )
    assert coder.is_bedrock is True
    assert coder.context_limit == 150_000


def test_non_bedrock_model_is_bedrock_false():
    coder = _coder(model="qwen3.6:latest")
    assert coder.is_bedrock is False
    assert coder.context_limit == 65_000


def test_ollama_prefixed_model_is_bedrock_false():
    coder = _coder(model="ollama/qwen3.6:latest")
    assert coder.is_bedrock is False


def test_context_limit_for_bedrock_model():
    model = "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert spec_window(PiCoder.spec, model) == 200_000


def test_context_limit_for_ollama_model():
    assert spec_window(PiCoder.spec, "qwen3.6:latest") == 65_000


def test_context_limit_for_ollama_prefixed_model():
    assert spec_window(PiCoder.spec, "ollama/qwen3.6:latest") == 65_000


def test_context_limit_for_none_model():
    assert spec_window(PiCoder.spec, None) == 128_000


def test_bedrock_kwargs_accepted_but_inert_for_ollama_routing(monkeypatch, tmp_path: Path):
    coder = _bedrock_coder("qwen3.6:latest", agent_dir=tmp_path)
    argv = coder.build_argv(_task(), tmp_path)
    assert argv[argv.index("--model") + 1] == "ollama/qwen3.6:latest"
    coder.write_runtime_config(tmp_path, _task())
    assert "ollama" in _read_models(tmp_path)["providers"]


def test_write_runtime_config_creates_agent_dir_recursively(monkeypatch, tmp_path: Path):
    nested = tmp_path / "a" / "b"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(nested))
    _coder(nested).write_runtime_config(tmp_path, _task())
    assert (nested / "models.json").exists()


@pytest.mark.parametrize("alias", ["sonnet", "opus", "haiku"])
def test_build_argv_claude_aliases_all_resolve_to_default(tmp_path: Path, alias: str):
    argv = _coder(model=alias).build_argv(_task(), tmp_path)
    assert argv[argv.index("--model") + 1] == "ollama/qwen3.6:latest"
