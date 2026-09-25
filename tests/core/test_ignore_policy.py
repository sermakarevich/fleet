"""Tests for the ignore-period helpers (core/ignore_policy.py)."""

from datetime import UTC, datetime, timedelta

from fleet.core.ignore_policy import ignore_active, ignore_until_24h


def test_ignore_active():
    assert ignore_active("forever")
    assert ignore_active("FOREVER")
    future = (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat()
    assert ignore_active(future)
    past = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
    assert not ignore_active(past)
    assert not ignore_active(None)
    assert not ignore_active("")
    assert not ignore_active("not-a-date")


def test_ignore_until_24h_is_active_for_a_day():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    until = ignore_until_24h(now)
    assert until == (now + timedelta(hours=24)).isoformat()
    assert ignore_active(until, now + timedelta(hours=23))
    assert not ignore_active(until, now + timedelta(hours=25))
