"""One clock and one timestamp parser for the whole codebase.

``now_iso()`` stamps new rows (attempts journal, run leases, task meta);
``parse_iso()`` reads them back. Callers in ``state/``, ``workers/``,
``orchestrator/`` and ``beads/`` use these instead of ad-hoc
``datetime.now(tz=UTC).isoformat()`` / ``datetime.fromisoformat()`` so every
timestamp has the same shape: ISO 8601, timezone-aware (naive inputs are
assumed UTC, a trailing ``Z`` is accepted).
"""

from __future__ import annotations

from datetime import UTC, datetime


def now_iso() -> str:
    """Current UTC time as an ISO 8601 string."""
    return datetime.now(tz=UTC).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp, or None when missing or malformed.

    A trailing ``Z`` is accepted; a naive datetime is assumed to be UTC so
    arithmetic against aware timestamps never raises ``TypeError``.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
