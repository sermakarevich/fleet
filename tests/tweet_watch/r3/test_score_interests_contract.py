"""R3 failures F3, F4, F12: the INTERESTS.md contract.

score_tweet is a pure function of (tweet text, interests content): it must
never fall back to a hardcoded topic list, and empty/unparseable interests
must abort instead of silently scoring everything LOW.
"""

import pathlib

import pytest

from fleet.tweet_watch.worker import score_tweet

CORE_TWEET = (
    "Shipped a fleet of headless coding-agent worker loops draining a "
    "central beads queue with a supervisor retrying failed tasks."
)


def test_f3_no_hardcoded_fallback(interests_text: str) -> None:
    cooking_only = (
        "# Interests\n\n## Core\n\n- Sourdough baking and fermentation.\n\n"
        "## Adjacent\n\n- Pasta shapes of northern Italy.\n"
    )
    assert cooking_only != interests_text
    assert score_tweet(CORE_TWEET, cooking_only) != "HIGH"


def test_f4_empty_interests_aborts(interests_text: str) -> None:
    assert interests_text.strip() != ""
    with pytest.raises(Exception):
        score_tweet(CORE_TWEET, "")


def test_f4_whitespace_interests_aborts(interests_text: str) -> None:
    with pytest.raises(Exception):
        score_tweet(CORE_TWEET, "  \n\t\n ")


def test_f4_voice_notes_only_aborts(interests_text: str) -> None:
    voice_only = (
        "# Interests\n\n## Voice notes\n\n- Plain language, no hype words.\n"
        "- Lead with one concrete observation or number.\n"
    )
    with pytest.raises(Exception):
        score_tweet(CORE_TWEET, voice_only)


def test_f4_abort_is_not_silent_low(interests_text: str) -> None:
    try:
        label = score_tweet(CORE_TWEET, "")
    except Exception:
        return
    raise AssertionError(f"expected abort, got silent label {label!r}")


def test_f12_scoring_needs_no_filesystem(
    interests_text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(self: pathlib.Path, *args: object, **kwargs: object) -> str:
        raise AssertionError("score_tweet must not read files")

    monkeypatch.setattr(pathlib.Path, "read_text", _boom)
    assert score_tweet(CORE_TWEET, interests_text) == "HIGH"
