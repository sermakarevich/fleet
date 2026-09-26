"""R6 failures F4-F5: malformed ids and bad explicit dates are unconfirmed."""

import pytest

from fleet.tweet_watch.worker import parse_confirmation


@pytest.mark.parametrize(
    "answer",
    [
        "posted, id: abc",
        "posted id xyz-not-a-number",
        "posted 12345abc",
    ],
)
def test_f4_malformed_id_is_unconfirmed(today, answer: str) -> None:
    assert parse_confirmation(answer, today) is None


def test_f4_non_numeric_id_value_is_unconfirmed(today) -> None:
    assert parse_confirmation("posted id: abc", today) is None


def test_f4_url_with_trailing_id_extracts_id(today) -> None:
    answer = "here: https://x.com/sergii/status/2103871751771898112?s=20"
    result = parse_confirmation(answer, today)
    assert result is not None
    assert result[0] == "2103871751771898112"


@pytest.mark.parametrize(
    "answer",
    [
        "posted 2103871751771898112 on 26/09/2026",
        "posted 2103871751771898112 yesterday",
        "posted 2103871751771898112 on Sept 26",
    ],
)
def test_f5_non_iso_date_is_unconfirmed(today, answer: str) -> None:
    assert parse_confirmation(answer, today) is None
