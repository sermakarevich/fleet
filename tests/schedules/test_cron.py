"""Tests for `schedules.cron` (syntax, matching, next-fire math, zones)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fleet.schedules.cron import CronError, next_fire, parse, upcoming


def _at(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, tz: object = UTC
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=tz)  # type: ignore[arg-type]


def test_star_matches_every_minute() -> None:
    schedule = parse("* * * * *")
    assert schedule.matches(_at(2026, 3, 4, 12, 34))
    assert schedule.matches(_at(2026, 12, 31, 23, 59))


def test_single_values_and_lists() -> None:
    schedule = parse("5 9 * * *")
    assert schedule.matches(_at(2026, 3, 4, 9, 5))
    assert not schedule.matches(_at(2026, 3, 4, 9, 6))
    listed = parse("0,15,30,45 * * * *")
    assert listed.minutes == (0, 15, 30, 45)


def test_ranges_and_steps() -> None:
    schedule = parse("*/15 9-17 * * *")
    assert schedule.minutes == (0, 15, 30, 45)
    assert schedule.hours == (9, 10, 11, 12, 13, 14, 15, 16, 17)
    assert schedule.matches(_at(2026, 3, 4, 10, 30))
    assert not schedule.matches(_at(2026, 3, 4, 10, 31))
    assert not schedule.matches(_at(2026, 3, 4, 18, 0))


def test_range_with_step_and_open_start() -> None:
    assert parse("0-30/10 * * * *").minutes == (0, 10, 20, 30)
    assert parse("5/15 * * * *").minutes == (5, 20, 35, 50)


def test_both_sunday_spellings() -> None:
    zero = parse("* * * * 0")
    seven = parse("* * * * 7")
    sunday = _at(2026, 9, 6, 12, 0)  # a Sunday
    assert sunday.isoweekday() == 7
    assert zero.matches(sunday)
    assert seven.matches(sunday)
    assert seven.weekdays == (0,)
    assert not zero.matches(_at(2026, 9, 7, 12, 0))  # Monday


def test_names() -> None:
    schedule = parse("0 9 * jan mon")
    assert schedule.months == (1,)
    assert schedule.weekdays == (1,)
    assert parse("0 0 * * sun").weekdays == (0,)
    assert parse("0 0 * * sat").weekdays == (6,)
    assert parse("0 0 1 dec *").months == (12,)


def test_aliases() -> None:
    assert parse("@hourly").minutes == (0,)
    assert parse("@daily").hours == (0,) and parse("@daily").minutes == (0,)
    assert parse("@midnight").hours == (0,)
    assert parse("@weekly").weekdays == (0,)
    assert parse("@monthly").days == (1,)
    assert parse("@yearly").months == (1,)
    assert parse("@annually").months == (1,)


def test_dom_or_dow_when_both_restricted() -> None:
    schedule = parse("0 0 13 * 5")  # 13th of month OR Friday
    friday_not_13th = _at(2026, 9, 4, 0, 0)
    assert friday_not_13th.isoweekday() == 5
    assert schedule.matches(friday_not_13th)
    thirteenth = _at(2026, 9, 13, 0, 0)  # a Sunday in 2026
    assert schedule.matches(thirteenth)
    assert not schedule.matches(_at(2026, 9, 5, 0, 0))  # Saturday, not 13th


def test_only_restricted_side_applies() -> None:
    fridays = parse("0 0 * * 5")
    assert fridays.matches(_at(2026, 9, 4, 0, 0))
    assert not fridays.matches(_at(2026, 9, 13, 0, 0))  # 13th but Sunday
    thirteenths = parse("0 0 13 * *")
    assert thirteenths.matches(_at(2026, 9, 13, 0, 0))
    assert not thirteenths.matches(_at(2026, 9, 4, 0, 0))  # Friday but not 13th


def test_next_fire_is_strictly_after() -> None:
    moment = _at(2026, 3, 4, 9, 5)
    assert next_fire("5 9 * * *", moment) == _at(2026, 3, 5, 9, 5)
    assert next_fire("* * * * *", moment) == _at(2026, 3, 4, 9, 6)


def test_next_fire_across_month_and_year_boundary() -> None:
    assert next_fire("0 0 1 * *", _at(2026, 1, 31, 12, 0)) == _at(2026, 2, 1, 0, 0)
    assert next_fire("0 0 1 1 *", _at(2026, 6, 15, 12, 0)) == _at(2027, 1, 1, 0, 0)


def test_next_fire_feb_29() -> None:
    assert next_fire("0 0 29 2 *", _at(2025, 1, 1, 0, 0)) == _at(2028, 2, 29, 0, 0)


def test_next_fire_warsaw_summer_and_winter() -> None:
    # 09:00 Warsaw is 07:00 UTC in summer (CEST), 08:00 UTC in winter (CET).
    assert next_fire("0 9 * * *", _at(2026, 7, 1, 5, 0), "Europe/Warsaw") == _at(2026, 7, 1, 7, 0)
    assert next_fire("0 9 * * *", _at(2026, 1, 15, 5, 0), "Europe/Warsaw") == _at(2026, 1, 15, 8, 0)


def test_next_fire_returns_aware_utc() -> None:
    fired = next_fire("0 9 * * *", _at(2026, 7, 1, 5, 0), "Europe/Warsaw")
    assert fired.tzinfo is not None
    assert fired.utcoffset() == UTC.utcoffset(None)


def test_bad_fields_raise_cron_error_naming_the_field() -> None:
    with pytest.raises(CronError, match="minute"):
        parse("60 * * * *")
    with pytest.raises(CronError, match="hour"):
        parse("* 24 * * *")
    with pytest.raises(CronError, match="day"):
        parse("* * 0 * *")
    with pytest.raises(CronError, match="month"):
        parse("* * * 13 *")
    with pytest.raises(CronError, match="weekday"):
        parse("* * * * 9")
    with pytest.raises(CronError, match="expression"):
        parse("* * * *")
    with pytest.raises(CronError, match="minute"):
        parse("abc * * * *")


def test_unknown_zone_raises_cron_error() -> None:
    with pytest.raises(CronError, match="timezone"):
        next_fire("* * * * *", _at(2026, 1, 1), "Mars/Olympus")


def test_upcoming_count_and_cap() -> None:
    firings = upcoming("* * * * *", _at(2026, 1, 1, 0, 0), count=3)
    assert firings == [_at(2026, 1, 1, 0, 1), _at(2026, 1, 1, 0, 2), _at(2026, 1, 1, 0, 3)]
    assert len(upcoming("* * * * *", _at(2026, 1, 1, 0, 0), count=500)) == 50
    assert upcoming("* * * * *", _at(2026, 1, 1, 0, 0), count=0) == []
