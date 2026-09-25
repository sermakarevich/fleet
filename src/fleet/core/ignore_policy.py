"""Ignore-period helpers for blocked tasks. Pure: no I/O.

``ignore_active`` is shared by the helper service, the API summary, the
blocked-task trigger source, and the CLI's ``--ignored`` listing so
"ignored" means one thing everywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fleet.core.iso import parse_iso


def ignore_active(ignore_until: str | None, now: datetime | None = None) -> bool:
    """True when an ``ignore_until`` value still suppresses triage.

    ``"forever"`` never expires; otherwise the value is an ISO timestamp and
    is active while it lies in the future. Missing, empty, or unparsable
    values are inactive (fail open: triage still asks).
    """
    if not ignore_until or not isinstance(ignore_until, str):
        return False
    if ignore_until.strip().lower() == "forever":
        return True
    parsed = parse_iso(ignore_until)
    if parsed is None:
        return False
    ref = now if now is not None else datetime.now(tz=UTC)
    return parsed > ref


def ignore_until_24h(now: datetime | None = None) -> str:
    """ISO timestamp 24h in the future, for the "ignore 24h" answer."""
    ref = now if now is not None else datetime.now(tz=UTC)
    return (ref + timedelta(hours=24)).isoformat()
