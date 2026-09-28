"""R6 failures F1-F3: declines, ambiguity, and id-less claims store nothing."""

import pytest

from fleet.tweet_watch.worker import parse_confirmation


@pytest.mark.parametrize(
    "answer",
    [
        "skip",
        "not this one",
        "I posted it myself elsewhere, skip the file",
        "declined",
    ],
)
def test_f1_decline_skip_or_self_post_is_unconfirmed(today, answer: str) -> None:
    assert parse_confirmation(answer, today) is None


@pytest.mark.parametrize("answer", ["", "   ", "hmm", "maybe later?", "ok"])
def test_f2_empty_or_ambiguous_answer_is_unconfirmed(today, answer: str) -> None:
    assert parse_confirmation(answer, today) is None


@pytest.mark.parametrize(
    "answer",
    [
        "posted",
        "posted it!",
        "yes, replied",
    ],
)
def test_f3_posted_without_id_is_unconfirmed(today, answer: str) -> None:
    assert parse_confirmation(answer, today) is None


def test_f3_id_must_come_from_the_answer_not_invented(today) -> None:
    result = parse_confirmation("posted, will send the id later", today)
    assert result is None
