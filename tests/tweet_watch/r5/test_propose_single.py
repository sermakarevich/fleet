"""R5 proposal gate happy path: one HIGH tweet -> one ask_human call.

A proposal is one `ask` call carrying BOTH the tweet link and the draft.
The operator's answer is returned verbatim for R6 (F16/F17/F18: ambiguity,
declines, and id-less confirmations are never reinterpreted here).
F19: a possibly-dead link is still proposed with the cached text.
"""

from __future__ import annotations

from fleet.tweet_watch.worker import propose_tweet

from .conftest import GOOD_DRAFT, AskRecorder, make_tweet


def test_valid_high_tweet_proposed_once_with_link_and_draft() -> None:
    tweet = make_tweet()
    ask = AskRecorder(answers=["posted, reply id 987654321"])
    answer = propose_tweet(tweet, GOOD_DRAFT, ask)
    assert len(ask.prompts) == 1
    assert tweet.url in ask.prompts[0]
    assert GOOD_DRAFT in ask.prompts[0]
    assert answer == "posted, reply id 987654321"


def test_answer_returned_verbatim_for_decline() -> None:
    """F17: a decline is passed through; storing nothing is R6's job."""
    ask = AskRecorder(answers=["skip, not this one"])
    assert propose_tweet(make_tweet(), GOOD_DRAFT, ask) == "skip, not this one"
    assert len(ask.prompts) == 1


def test_answer_returned_verbatim_for_ambiguous_reply() -> None:
    """F16: ambiguity is never upgraded to a confirmation here."""
    ask = AskRecorder(answers=["hmm, not sure yet"])
    assert propose_tweet(make_tweet(), GOOD_DRAFT, ask) == "hmm, not sure yet"


def test_answer_returned_verbatim_for_confirmation_without_id() -> None:
    """F18: 'posted' with no reply id passes through; R6 stores nothing."""
    ask = AskRecorder(answers=["posted!"])
    assert propose_tweet(make_tweet(), GOOD_DRAFT, ask) == "posted!"


def test_possibly_dead_link_still_proposed_with_cached_text() -> None:
    """F19: the worker does not re-validate liveness; the operator decides."""
    tweet = make_tweet(url="https://x.com/omarsar0/status/0000000000000000000")
    ask = AskRecorder(answers=["skip"])
    propose_tweet(tweet, GOOD_DRAFT, ask)
    assert len(ask.prompts) == 1
    assert tweet.url in ask.prompts[0]
