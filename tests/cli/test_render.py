"""Tests for cli/render.py duration formatting (must match UI fmtDuration)."""

from __future__ import annotations

from fleet.cli.render import format_elapsed


def test_none_is_unknown() -> None:
    """Missing elapsed time renders as a dash."""
    assert format_elapsed(None) == "-"


def test_seconds() -> None:
    """Sub-minute durations render as whole seconds."""
    assert format_elapsed(0) == "0s"
    assert format_elapsed(42) == "42s"


def test_minutes_with_seconds() -> None:
    """Minute durations render as '5m 3s', matching UI fmtDuration."""
    assert format_elapsed(303) == "5m 3s"


def test_whole_minutes_omit_seconds() -> None:
    """Exact minutes render without a zero seconds part."""
    assert format_elapsed(300) == "5m"


def test_hours_with_minutes() -> None:
    """Hour durations render as '2h 5m', matching UI fmtDuration."""
    assert format_elapsed(7500) == "2h 5m"


def test_whole_hours_omit_minutes() -> None:
    """Exact hours render without a zero minutes part."""
    assert format_elapsed(7200) == "2h"
