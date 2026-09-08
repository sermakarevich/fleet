"""One context_limit_for test per coder: all resolve through the same table."""

from fleet.coders.agy import AgyCoder
from fleet.coders.claude import ClaudeCoder
from fleet.coders.codex import CodexCoder
from fleet.coders.opencode import OpencodeCoder
from fleet.coders.pi import PiCoder


def test_claude_sonnet_is_200k():
    assert ClaudeCoder.context_limit_for("sonnet") == 200_000


def test_claude_unknown_model_falls_back_to_class_default():
    assert ClaudeCoder.context_limit_for("some-future-model") == 200_000
    assert ClaudeCoder.context_limit_for(None) == 200_000


def test_agy_resolves_through_shared_table():
    # "GPT-OSS 120B" family-matches the gpt-oss row (128k == class default here,
    # so assert via an override to prove the shared lookup runs).
    assert AgyCoder.context_limit_for("GPT-OSS 120B") == 128_000
    assert AgyCoder.context_limit_for("GPT-OSS 120B", {"GPT-OSS 120B": 99_000}) == 99_000
    assert AgyCoder.context_limit_for(None) == 128_000


def test_codex_resolves_through_shared_table():
    assert CodexCoder.context_limit_for("o4-mini") == 128_000
    assert CodexCoder.context_limit_for("muse-spark-1.3-contributor") == 1_048_576
    assert CodexCoder.context_limit_for(None) == 128_000


def test_opencode_muse_spark_is_1m():
    assert (
        OpencodeCoder.context_limit_for("muse-spark-1.3-contributor") == 1_048_576
    )
    assert (
        OpencodeCoder.context_limit_for("opencode-go/muse-spark-1.3-contributor")
        == 1_048_576
    )


def test_opencode_qwen_is_65k():
    assert OpencodeCoder.context_limit_for("qwen3.6:latest") == 65_000


def test_opencode_bedrock_is_200k():
    assert (
        OpencodeCoder.context_limit_for(
            "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        )
        == 200_000
    )


def test_opencode_override_wins():
    assert (
        OpencodeCoder.context_limit_for(
            "qwen3.6:latest", {"qwen3.6:latest": 70_000}
        )
        == 70_000
    )


def test_pi_muse_spark_is_1m():
    assert PiCoder.context_limit_for("muse-spark-1.3-contributor") == 1_048_576


def test_pi_qwen_is_65k():
    assert PiCoder.context_limit_for("qwen3.6:latest") == 65_000


def test_pi_bedrock_is_200k():
    assert (
        PiCoder.context_limit_for(
            "amazon-bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        )
        == 200_000
    )


def test_pi_none_falls_back_to_class_default():
    assert PiCoder.context_limit_for(None) == 128_000
