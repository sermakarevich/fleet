"""R6 parse_confirmation: confirmations carrying a posted reply id are accepted."""

from datetime import date

from fleet.tweet_watch.worker import parse_confirmation


def test_bare_numeric_id_confirms_with_today(today) -> None:
    assert parse_confirmation("posted 2103871751771898112", today) == (
        "2103871751771898112",
        "2026-09-26",
    )


def test_x_com_url_confirms_with_id_extracted(today) -> None:
    answer = "posted: https://x.com/sergii/status/2103871751771898112"
    assert parse_confirmation(answer, today) == ("2103871751771898112", "2026-09-26")


def test_explicit_posting_date_used_when_given(today) -> None:
    answer = "posted 2103871751771898112 on 2026-09-26"
    assert parse_confirmation(answer, today) == ("2103871751771898112", "2026-09-26")


def test_confirmation_with_no_date_uses_confirmation_day() -> None:
    result = parse_confirmation("posted 2103871751771898112", date(2026, 9, 27))
    assert result == ("2103871751771898112", "2026-09-27")
