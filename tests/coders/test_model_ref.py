"""Tests for coders/model_ref.py: one model parser for the Ollama-routed coders."""

from fleet.coders.model_ref import CLAUDE_ALIASES, ModelRef, resolve_model


def test_bare_name_takes_default_provider():
    ref = resolve_model("qwen3.6:latest", "qwen3.6:latest", default_provider="ollama")
    assert ref == ModelRef(provider="ollama", name="qwen3.6:latest")
    assert ref.full_id == "ollama/qwen3.6:latest"


def test_bare_name_takes_opencode_provider():
    ref = resolve_model("gpt-oss:20b", "gpt-oss:20b", default_provider="ollama-rtx")
    assert ref.full_id == "ollama-rtx/gpt-oss:20b"
    assert ref.name == "gpt-oss:20b"


def test_qualified_name_passes_through():
    ref = resolve_model("ollama/deepseek-r1:32b", "qwen3.6:latest", default_provider="ollama")
    assert ref == ModelRef(provider="ollama", name="deepseek-r1:32b")


def test_bedrock_id_passes_through():
    ref = resolve_model(
        "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "qwen3.6:latest",
        default_provider="ollama",
    )
    assert ref.provider == "amazon-bedrock"
    assert ref.name == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert ref.full_id == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_sonnet_alias_maps_to_default():
    for alias in CLAUDE_ALIASES:
        ref = resolve_model(alias, "qwen3.6:latest", default_provider="ollama")
        assert ref.full_id == "ollama/qwen3.6:latest"


def test_alias_uses_custom_default():
    ref = resolve_model("sonnet", "qwen3.5:27b", default_provider="ollama-rtx")
    assert ref.full_id == "ollama-rtx/qwen3.5:27b"


def test_explicit_bare_name_ignores_default():
    ref = resolve_model("deepseek-r1:32b", "qwen3.6:latest", default_provider="ollama")
    assert ref.full_id == "ollama/deepseek-r1:32b"


def test_model_ref_is_frozen():
    ref = ModelRef(provider="ollama", name="qwen3.6:latest")
    try:
        ref.provider = "other"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("ModelRef should be frozen")
