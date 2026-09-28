"""R5 proposal gate, bad input: skip (never propose), never invent content.

F1: empty/whitespace tweet text. F2: missing url or id (never invent a
URL). F9: empty draft after trimming. A skip raises (so the batch loop can
log the tweet id and continue) and never calls `ask`. F15: a tool failure
propagates as an error — never swallowed into a fake decline/confirmation.
"""

from __future__ import annotations

import pytest

from fleet.tweet_watch.worker import propose_tweet

from .conftest import GOOD_DRAFT, AskRecorder, make_tweet


def _assert_skipped(tweet, draft: str) -> None:
    ask = AskRecorder()
    with pytest.raises(Exception) as excinfo:
        propose_tweet(tweet, draft, ask)
    assert not isinstance(excinfo.value, NotImplementedError)
    assert ask.prompts == []


@pytest.mark.parametrize("blank", ["", "   ", "\n\t \n"])
def test_empty_tweet_text_skipped(blank: str) -> None:
    """F1: nothing to add something new to; rest of the batch continues."""
    _assert_skipped(make_tweet(text=blank), GOOD_DRAFT)


@pytest.mark.parametrize("field", ["url", "id"])
def test_tweet_missing_link_half_skipped(field: str) -> None:
    """F2: a proposal without a link is not a proposal; never invent one."""
    kwargs = {field: "" if field == "url" else "   "}
    tweet = make_tweet(**kwargs)  # type: ignore[arg-type]
    ask = AskRecorder()
    with pytest.raises(Exception) as excinfo:
        propose_tweet(tweet, GOOD_DRAFT, ask)
    assert not isinstance(excinfo.value, NotImplementedError)
    assert ask.prompts == []


@pytest.mark.parametrize("blank_draft", ["", "   ", "\n \t\n"])
def test_empty_draft_skipped(blank_draft: str) -> None:
    """F9: the generator returned nothing — no empty ask call."""
    _assert_skipped(make_tweet(), blank_draft)


def test_ask_tool_failure_propagates_as_error() -> None:
    """F15: a tool error is never a decline and never a confirmation."""
    ask = AskRecorder()
    ask.fail_on = {0}
    with pytest.raises(Exception) as excinfo:
        propose_tweet(make_tweet(), GOOD_DRAFT, ask)
    assert not isinstance(excinfo.value, NotImplementedError)
    assert len(ask.prompts) == 1  # the attempt happened; the batch continues
