"""R5 proposal gate, voice/content checks happen BEFORE the ask call.

F3/F14: praise-only or restating drafts are not proposed. F4: hype-worded
drafts are rewritten, never proposed as-is. F5: unexplained abbreviations
are expanded first. F6: setup-first drafts lead with the concrete content.
F12: over-limit drafts are rewritten/trimmed, never proposed over-limit and
never auto-truncated mid-word. Contract: skip (raise, ask uncalled) OR
propose a cleaned draft — never propose the dirty draft as-is.
"""

from __future__ import annotations

import pytest

from fleet.tweet_watch.worker import propose_tweet

from .conftest import (
    HYPE_WORDS,
    X_POST_LIMIT,
    AskRecorder,
    is_praise_only,
    make_tweet,
    unexplained_abbreviations,
)


def _attempt(tweet, draft: str) -> list[str] | None:
    """Return captured prompts, or None if the worker skipped the tweet."""
    ask = AskRecorder(answers=["skip"])
    try:
        propose_tweet(tweet, draft, ask)
    except NotImplementedError:
        raise
    except Exception:
        assert ask.prompts == []
        return None
    return ask.prompts


def test_praise_only_draft_never_proposed_as_is() -> None:
    """F3: 'Great point!' adds nothing new."""
    result = _attempt(make_tweet(), "Great point! So true.")
    assert result is None or not is_praise_only(result[0])


def test_restatement_draft_never_proposed_as_is() -> None:
    """F3/F14: echoing the tweet (plus filler) is not a new point."""
    tweet = make_tweet()
    restatement = tweet.text + " Exactly, well said."
    result = _attempt(tweet, restatement)
    assert result is None or restatement not in result[0]


@pytest.mark.parametrize("hype", list(HYPE_WORDS))
def test_hype_worded_draft_never_proposed_as_is(hype: str) -> None:
    """F4: the voice check runs before the ask call, not after."""
    tweet = make_tweet()
    result = _attempt(tweet, f"This is {hype}! Pipelined stages cut latency.")
    assert result is None or hype not in result[0].casefold()


def test_unexplained_abbreviation_never_proposed_as_is() -> None:
    """F5: FPR/VLM must be expanded on first use before proposing."""
    tweet = make_tweet()
    result = _attempt(tweet, "Cut your FPR with a second-pass VLM, it helps.")
    assert result is None or unexplained_abbreviations(result[0]) == []


def test_setup_first_draft_rewritten_to_lead_concrete() -> None:
    """F6: setup buried three sentences deep is rewritten to lead concrete."""
    tweet = make_tweet()
    setup_first = (
        "This is a really interesting topic and there is a lot of background "
        "worth covering before getting into the details of the approach. "
        "Many teams think about pipelines in different ways these days. "
        "Pipelined stages cut turn-taking to 120ms in our calls."
    )
    result = _attempt(tweet, setup_first)
    assert result is None or result[0].index("120") < 200


def test_overlong_draft_never_proposed_over_limit() -> None:
    """F12: only postable drafts reach the operator."""
    tweet = make_tweet()
    long_draft = ("Benchmark paragraph with concrete numbers 120ms. " * 8).strip()
    assert len(long_draft) > X_POST_LIMIT
    result = _attempt(tweet, long_draft)
    assert result is None or (
        long_draft not in result[0] and len(result[0]) <= X_POST_LIMIT + len(tweet.url) + 64
    )


def test_overlong_draft_never_truncated_mid_word() -> None:
    """F12: a trim that slices a word in half is still a bug."""
    tweet = make_tweet()
    padding = "Benchmark paragraph with concrete numbers 120ms. " * 5
    long_draft = padding + "Plus supercalifragilisticexpialidocious latency wins."
    assert len(long_draft) > X_POST_LIMIT
    assert len(padding) < X_POST_LIMIT < len(long_draft)
    result = _attempt(tweet, long_draft)
    if result is None:
        return
    lowered = result[0].casefold()
    assert "supercalifragilisticexpialidocious" in lowered or "supercali" not in lowered
