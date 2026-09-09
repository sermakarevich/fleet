"""One context_limit_for test per coder: all resolve through the same table."""

from fleet.coders import context_limit_for
from fleet.coders.agy import AgyCoder
from fleet.coders.base import context_limit_for as spec_window
from fleet.coders.claude import ClaudeCoder
from fleet.coders.codex import CodexCoder
from fleet.coders.opencode import OpencodeCoder
from fleet.coders.pi import PiCoder


def test_claude_sonnet_is_200k():
    assert spec_window(ClaudeCoder.spec, "sonnet") == 200_000


def test_claude_unknown_model_falls_back_to_class_default():
    assert spec_window(ClaudeCoder.spec, "some-future-model") == 200_000
    assert spec_window(ClaudeCoder.spec, None) == 200_000


def test_agy_resolves_through_shared_table():
    # "GPT-OSS 120B" family-matches the gpt-oss row (128k == class default here,
    # so assert via an override to prove the shared lookup runs).
    assert spec_window(AgyCoder.spec, "GPT-OSS 120B") == 128_000
    assert spec_window(AgyCoder.spec, "GPT-OSS 120B", {"GPT-OSS 120B": 99_000}) == 99_000
    assert spec_window(AgyCoder.spec, None) == 128_000


def test_codex_resolves_through_shared_table():
    assert spec_window(CodexCoder.spec, "o4-mini") == 128_000
    assert spec_window(CodexCoder.spec, "muse-spark-1.3-contributor") == 1_048_576
    assert spec_window(CodexCoder.spec, None) == 128_000


def test_opencode_muse_spark_is_1m():
    assert spec_window(OpencodeCoder.spec, "muse-spark-1.3-contributor") == 1_048_576
    assert spec_window(OpencodeCoder.spec, "opencode-go/muse-spark-1.3-contributor") == 1_048_576


def test_opencode_qwen_is_65k():
    assert spec_window(OpencodeCoder.spec, "qwen3.6:latest") == 65_000


def test_opencode_bedrock_is_200k():
    model = "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert spec_window(OpencodeCoder.spec, model) == 200_000


def test_opencode_override_wins():
    assert spec_window(OpencodeCoder.spec, "qwen3.6:latest", {"qwen3.6:latest": 70_000}) == 70_000


def test_pi_muse_spark_is_1m():
    assert spec_window(PiCoder.spec, "muse-spark-1.3-contributor") == 1_048_576


def test_pi_qwen_is_65k():
    assert spec_window(PiCoder.spec, "qwen3.6:latest") == 65_000


def test_pi_bedrock_is_200k():
    model = "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert spec_window(PiCoder.spec, model) == 200_000


def test_pi_none_falls_back_to_class_default():
    assert spec_window(PiCoder.spec, None) == 128_000


def test_registry_helper_unknown_coder_falls_back():
    assert context_limit_for("no-such-coder", "whatever") == 200_000
    assert context_limit_for(None, "whatever") == 200_000


def test_registry_helper_matches_spec_windows():
    assert context_limit_for("claude", "sonnet") == 200_000
    assert context_limit_for("opencode", "qwen3.6:latest") == 65_000
    assert context_limit_for("pi", "qwen3.6:latest") == 65_000
    assert context_limit_for("codex", "o4-mini") == 128_000
    assert context_limit_for("agy", "GPT-OSS 120B") == 128_000
