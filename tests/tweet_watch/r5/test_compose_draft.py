"""R5 draft half: compose_draft adds something new in the INTERESTS.md voice.

Covers F3 (not praise-only / not a restatement), F4 (no hype words),
F5 (abbreviations explained), F6 (concrete content first), F12 (postable
length), F14 (not trivially different from the source tweet).
"""

from __future__ import annotations

from fleet.tweet_watch.worker import compose_draft

from .conftest import (
    HYPE_WORDS,
    PRAISE_OPENERS,
    X_POST_LIMIT,
    first_sentence,
    is_praise_only,
    make_tweet,
    normalize,
    unexplained_abbreviations,
)


def test_draft_is_nonempty_postable_text(interests_text: str) -> None:
    draft = compose_draft(make_tweet(), interests_text)
    assert isinstance(draft, str)
    assert draft.strip() != ""
    assert len(draft) <= X_POST_LIMIT


def test_draft_adds_something_new_not_praise_only(interests_text: str) -> None:
    """F3: the draft makes a new point; it is not praise or a restatement."""
    tweet = make_tweet()
    draft = compose_draft(tweet, interests_text)
    assert not is_praise_only(draft)
    assert len(draft.split()) >= 8
    assert normalize(draft) != normalize(tweet.text)


def test_draft_not_trivially_different_from_source(interests_text: str) -> None:
    """F14: copying the tweet's sentence plus filler is a restatement."""
    tweet = make_tweet()
    draft = compose_draft(tweet, interests_text)
    assert normalize(tweet.text) != normalize(draft)
    assert normalize(draft) != normalize(tweet.text + " Exactly.")


def test_draft_has_no_hype_words(interests_text: str) -> None:
    """F4: INTERESTS.md voice bans hype words in the draft itself."""
    draft = compose_draft(make_tweet(), interests_text).casefold()
    for hype in HYPE_WORDS:
        assert hype not in draft


def test_draft_explains_abbreviations(interests_text: str) -> None:
    """F5: any abbreviation the draft introduces is expanded on first use."""
    draft = compose_draft(make_tweet(), interests_text)
    assert unexplained_abbreviations(draft) == []


def test_draft_leads_with_concrete_content(interests_text: str) -> None:
    """F6: the opening is a concrete observation, not praise or setup."""
    draft = compose_draft(make_tweet(), interests_text)
    opening = first_sentence(draft)
    first_word = "".join(ch for ch in opening.split(" ")[0] if ch.isalpha()).casefold()
    assert first_word not in PRAISE_OPENERS
    assert not is_praise_only(opening)
