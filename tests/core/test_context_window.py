"""Tests for core.context_window: the one denominator for supervisor and UI."""

import pytest

from fleet.core.context_window import (
    DEFAULT_WINDOWS,
    parse_context_windows,
    resolve_window,
)


def test_exact_model_id_resolves():
    assert resolve_window("muse-spark-1.3-contributor", None, 128_000) == 1_048_576


def test_provider_prefix_is_stripped():
    assert resolve_window("opencode-go/muse-spark-1.3-contributor", None, 128_000) == 1_048_576


def test_family_prefix_match_both_directions():
    # Short family id matches the longer table key.
    assert resolve_window("muse-spark-1.3", None, 128_000) == 1_048_576
    # Longer model string matches the shorter family key.
    assert resolve_window("muse-spark-1.3-contributor-extra", None, 128_000) == 1_048_576


def test_bedrock_ids_resolve_to_200k():
    assert (
        resolve_window(
            "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            None,
            128_000,
        )
        == 200_000
    )


def test_local_qwen_resolves_to_65k():
    assert resolve_window("qwen3.6:latest", None, 128_000) == 65_000


def test_unknown_model_falls_back_to_coder_default():
    assert resolve_window("some-future-model-9", None, 128_000) == 128_000


def test_none_and_blank_model_fall_back():
    assert resolve_window(None, None, 128_000) == 128_000
    assert resolve_window("   ", None, 128_000) == 128_000


def test_override_wins_over_builtin_table():
    overrides = {"qwen3.6:latest": 70_000}
    assert resolve_window("qwen3.6:latest", overrides, 128_000) == 70_000


def test_override_family_match_wins_over_builtin():
    overrides = {"qwen3": 70_000}
    assert resolve_window("qwen3.6:latest", overrides, 128_000) == 70_000


def test_override_for_unknown_model():
    overrides = {"my-model": 11_000}
    assert resolve_window("my-model", overrides, 128_000) == 11_000


def test_parse_context_windows_round_trip():
    assert parse_context_windows("a:1000,b:2000") == {"a": 1000, "b": 2000}
    assert parse_context_windows("  muse-spark-1.3-contributor:1048576  ") == {
        "muse-spark-1.3-contributor": 1_048_576
    }
    # Model tags contain colons: split on the LAST one.
    assert parse_context_windows("qwen3.6:latest:100000") == {"qwen3.6:latest": 100_000}
    assert parse_context_windows("") == {}
    assert parse_context_windows("   ") == {}


@pytest.mark.parametrize(
    "raw",
    [
        "no-colon-here",
        ":1000",
        "model:not-a-number",
        "model:0",
        "model:-5",
        "ok:1000,bad-entry",
    ],
)
def test_parse_context_windows_errors(raw: str):
    with pytest.raises(ValueError):
        parse_context_windows(raw)


def test_default_table_has_expected_families():
    assert DEFAULT_WINDOWS["muse-spark-1.3-contributor"] == 1_048_576
    assert DEFAULT_WINDOWS["sonnet"] == 200_000
