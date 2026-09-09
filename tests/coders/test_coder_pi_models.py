"""Tests for the Pi coder model routing (unit under test: coders/pi.py model resolution)."""

from fleet.coders import get_coder, list_coders
from fleet.coders.base import CoderSpec
from fleet.coders.model_ref import resolve_model
from fleet.coders.pi import PiCoder, _map_usage


def _pi_resolve(model: str, default: str) -> tuple[str, str]:
    """Adapter for the shared model_ref.resolve_model with pi's provider."""
    ref = resolve_model(model, default, default_provider="ollama")
    return ref.full_id, ref.name


def test_get_coder_returns_pi_class():
    assert get_coder("pi") is PiCoder


def test_pi_in_list_coders():
    names = [c["name"] for c in list_coders()]
    assert "pi" in names


def test_pi_spec_names_registry_entry():
    assert isinstance(PiCoder.spec, CoderSpec)
    assert PiCoder.spec.name == "pi"
    assert PiCoder.spec.context_limit == 128_000
    assert PiCoder.spec.default_model == "qwen3.6:latest"


def test_resolve_model_bare_name_gets_ollama_prefix():
    full_id, local_key = _pi_resolve("qwen3.6:latest", "qwen3.6:latest")
    assert full_id == "ollama/qwen3.6:latest"
    assert local_key == "qwen3.6:latest"


def test_resolve_model_bare_custom_name_gets_ollama_prefix():
    full_id, local_key = _pi_resolve("qwen3.5:27b", "qwen3.6:latest")
    assert full_id == "ollama/qwen3.5:27b"
    assert local_key == "qwen3.5:27b"


def test_resolve_model_with_slash_used_as_is():
    full_id, local_key = _pi_resolve("ollama/deepseek-r1:32b", "qwen3.6:latest")
    assert full_id == "ollama/deepseek-r1:32b"
    assert local_key == "deepseek-r1:32b"


def test_resolve_model_bedrock_id_used_as_is():
    full_id, local_key = _pi_resolve(
        "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "qwen3.6:latest",
    )
    assert full_id == "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert local_key == "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_resolve_model_sonnet_alias_maps_to_default():
    full_id, local_key = _pi_resolve("sonnet", "qwen3.6:latest")
    assert full_id == "ollama/qwen3.6:latest"
    assert local_key == "qwen3.6:latest"


def test_resolve_model_opus_alias_maps_to_default():
    full_id, local_key = _pi_resolve("opus", "qwen3.6:latest")
    assert full_id == "ollama/qwen3.6:latest"


def test_resolve_model_haiku_alias_maps_to_default():
    full_id, local_key = _pi_resolve("haiku", "qwen3.6:latest")
    assert full_id == "ollama/qwen3.6:latest"


def test_resolve_model_alias_uses_custom_default():
    full_id, local_key = _pi_resolve("sonnet", "qwen3.5:27b")
    assert full_id == "ollama/qwen3.5:27b"
    assert local_key == "qwen3.5:27b"


def test_resolve_model_explicit_bare_ignores_default():
    full_id, _ = _pi_resolve("deepseek-r1:32b", "qwen3.6:latest")
    assert full_id == "ollama/deepseek-r1:32b"


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
