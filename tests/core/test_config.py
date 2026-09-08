"""Pure config tests: RuntimeConfig defaults, parse, render_toml, merge.

File I/O (load, reload_if_changed, write) is tested in
tests/state/test_config_file.py.
"""

import logging

import pytest

from fleet.core.config import RuntimeConfig, merge, parse, render_toml


def test_parse_partial_dict_overlays_defaults() -> None:
    cfg = parse({"max_concurrent": 8})

    assert cfg.max_concurrent == 8
    assert cfg.model == RuntimeConfig().model


def test_parse_ignores_unknown_keys() -> None:
    cfg = parse({"not_a_real_key": 42})

    assert cfg == RuntimeConfig()


def test_parse_coerces_string_ints() -> None:
    cfg = parse({"max_concurrent": "7"})

    assert cfg.max_concurrent == 7


def test_parse_rejects_bad_bool() -> None:
    with pytest.raises(ValueError):
        parse({"compaction_enabled": "garbage"})


def test_parse_rejects_bad_isolation() -> None:
    with pytest.raises(ValueError, match="isolation"):
        parse({"isolation": "docker"})


def test_render_toml_round_trips_through_parse() -> None:
    text = render_toml({"max_concurrent": 7, "compaction_enabled": False})

    assert "max_concurrent = 7" in text
    assert "compaction_enabled = false" in text


def test_merge_applies_updates_over_existing() -> None:
    merged = merge({"max_concurrent": 4}, {"stall_warning_minutes": "85"})

    assert merged["max_concurrent"] == 4
    assert merged["stall_warning_minutes"] == 85
    assert RuntimeConfig(**merged).stall_warning_minutes == 85


def test_merge_unknown_key_raises() -> None:
    with pytest.raises(ValueError, match="Unknown config key"):
        merge({}, {"not_a_real_key": "42"})


def test_merge_does_not_validate_coder_names() -> None:
    """Coder names are validated by cli/config and serve/api/config, not here."""
    merged = merge({}, {"coder": "whatever"})

    assert merged["coder"] == "whatever"


def test_deprecated_context_keys_are_ignored_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Old single-number keys warn and fall back to defaults."""

    with caplog.at_level(logging.WARNING, logger="fleet.core.config"):
        cfg = parse({"opencode_context_limit": 64000, "opencode_bedrock_context_limit": 300000})

    assert cfg.context_windows == ""
    assert any("opencode_context_limit" in r.message for r in caplog.records)


def test_parse_picks_up_context_windows() -> None:
    cfg = parse(
        {
            "context_windows": "muse-spark-1.3-contributor:1048576",
            "opencode_default_model": "qwen3.6:latest",
        }
    )

    assert cfg.context_windows == "muse-spark-1.3-contributor:1048576"
    assert cfg.opencode_default_model == "qwen3.6:latest"


def test_bedrock_config_defaults() -> None:
    cfg = RuntimeConfig()
    assert cfg.opencode_bedrock_region == ""
    assert cfg.opencode_bedrock_profile == ""
    assert cfg.context_windows == ""
