"""Tests for `core.iso`: the one clock and timestamp parser."""

from __future__ import annotations

from datetime import UTC

from fleet.core.iso import now_iso, parse_iso


def test_now_iso_round_trips_through_parse_iso() -> None:
    stamp = now_iso()
    parsed = parse_iso(stamp)
    assert parsed is not None
    assert parsed.tzinfo is not None


def test_parse_iso_accepts_zulu_and_naive() -> None:
    zulu = parse_iso("2026-01-01T00:00:00Z")
    assert zulu is not None
    assert zulu.tzinfo is not None
    naive = parse_iso("2026-01-01T00:00:00")
    assert naive is not None
    assert naive.tzinfo == UTC


def test_parse_iso_rejects_garbage() -> None:
    assert parse_iso(None) is None
    assert parse_iso("") is None
    assert parse_iso("not-a-date") is None
    assert parse_iso(123) is None  # type: ignore[arg-type]
