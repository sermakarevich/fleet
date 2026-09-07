from fleet.redact import redact


def test_exact_credential_keys_redacted():
    payload = {
        "ANTHROPIC_API_KEY": "sk-ant-123",
        "ANTHROPIC_AUTH_TOKEN": "tok-456",
        "OPENAI_API_KEY": "sk-openai-789",
        "GEMINI_API_KEY": "gm-abc",
    }
    result = redact(payload)
    assert all(v == "<redacted>" for v in result.values())


def test_substring_keys_redacted():
    result = redact({"db_password": "secret!", "my_secret": "xyz", "access_token": "tok"})
    assert result["db_password"] == "<redacted>"
    assert result["my_secret"] == "<redacted>"
    assert result["access_token"] == "<redacted>"


def test_non_credential_keys_unchanged():
    payload = {"name": "test", "count": 42, "enabled": True}
    assert redact(payload) == payload


def test_nested_dicts_redacted_recursively():
    payload = {
        "outer": {"ANTHROPIC_API_KEY": "sk-key", "safe": "value"},
        "top_level": "ok",
    }
    result = redact(payload)
    assert result["outer"]["ANTHROPIC_API_KEY"] == "<redacted>"
    assert result["outer"]["safe"] == "value"
    assert result["top_level"] == "ok"


def test_input_dict_not_mutated():
    original = {"ANTHROPIC_API_KEY": "sk-key", "name": "test"}
    snapshot = dict(original)
    redact(original)
    assert original == snapshot


def test_empty_dict():
    assert redact({}) == {}


def test_plural_token_count_fields_are_not_redacted():
    """LLM usage metrics use the plural `tokens` suffix; they are counts,
    not credentials, and must pass through redact unchanged."""
    payload = {
        "input_tokens": 1234,
        "output_tokens": 56,
        "cache_creation_input_tokens": 7890,
        "cache_read_input_tokens": 11,
        "usage": {
            "input_tokens": 100,
            "output_tokens": 200,
        },
    }
    result = redact(payload)
    assert result["input_tokens"] == 1234
    assert result["output_tokens"] == 56
    assert result["cache_creation_input_tokens"] == 7890
    assert result["cache_read_input_tokens"] == 11
    assert result["usage"]["input_tokens"] == 100
    assert result["usage"]["output_tokens"] == 200


def test_singular_token_credentials_still_redacted_alongside_token_counts():
    payload = {"access_token": "tok-1", "input_tokens": 42}
    result = redact(payload)
    assert result["access_token"] == "<redacted>"
    assert result["input_tokens"] == 42
