"""TTL-cached map of beads status by task id, built from beads.client.list_all.

Avoids a `bd list` subprocess on every poll from the API/CLI layers.
Called by serve/api/tasks_list.py, serve/analytics/summary.py and cli/render.py.

When `bd` fails the last-known good map keeps being served (never a
silent fallback to raw task.json statuses): the snapshot carries
``available=False`` plus the error string so callers can banner it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from fleet.beads import client as beads_client
from fleet.beads.client import BdError

logger = logging.getLogger(__name__)

# TTL cache — key: str(fleet_home), value: (expires_at, result)
_beads_map_cache: dict[str, tuple[float, dict[str, dict] | None]] = {}
_BEADS_CACHE_TTL: float = 5.0

_beads_list_call_count: int = 0  # incremented on each real subprocess call; observable in tests

# Last-known good map per fleet home: served (marked stale) while bd fails.
_beads_last_good: dict[str, dict[str, dict]] = {}
# (monotonic timestamp, message) of the most recent BdError per fleet home.
_beads_last_error: dict[str, tuple[float, str]] = {}
# Monotonic timestamp of the most recent successful `bd list` per fleet home.
_beads_last_ok_at: dict[str, float] = {}
# Monotonic timestamp of the last "beads unavailable" warning per fleet home.
_beads_last_warn_at: dict[str, float] = {}


@dataclass
class BeadsSnapshot:
    """One beads read: the map plus whether bd is currently reachable.

    ``available`` is False when the map is None (bd never succeeded) or
    stale (a previous good map is served while bd fails). ``error`` is
    the bd failure string, None on a fresh read.
    """

    map: dict[str, dict] | None
    available: bool
    error: str | None = None
    stale: bool = False


def _warn_once_per_window(key: str, now: float, fleet_home: Path, message: str) -> None:
    """Log the bd failure, at most once per cache TTL window per fleet home."""
    if now - _beads_last_warn_at.get(key, 0.0) >= _BEADS_CACHE_TTL:
        logger.warning("beads unavailable for %s: %s (serving last-known map)", fleet_home, message)
        _beads_last_warn_at[key] = now


def get_beads_snapshot(fleet_home: Path) -> BeadsSnapshot:
    """Return the cached beads map plus bd reachability for `fleet_home`.

    Success refreshes the TTL entry and clears the recorded error. On
    BdError the previous non-None map keeps being served (marked stale,
    ``available=False``); only when bd never succeeded is the map None.
    Results are cached for _BEADS_CACHE_TTL seconds to avoid a subprocess
    on every poll.
    """
    global _beads_list_call_count  # noqa: PLW0603  # ADR 0006 bead 4 owns beads/ shared state
    key = str(fleet_home)
    now = time.monotonic()
    cached = _beads_map_cache.get(key)
    if cached is not None and now < cached[0]:
        value = cached[1]
        err = _beads_last_error.get(key)
        if err is None:
            return BeadsSnapshot(map=value, available=True)
        if value is None:
            return BeadsSnapshot(map=None, available=False, error=err[1])
        return BeadsSnapshot(map=value, available=False, error=err[1], stale=True)

    try:
        _beads_list_call_count += 1
        items = beads_client.list_all(fleet_home)
        value = {
            item["id"]: {
                "status": item.get("status", "open"),
                "created_at": item.get("created_at"),
                "priority": item.get("priority"),
                "title": item.get("title"),
                "description": item.get("description"),
                "notes": item.get("notes"),
                "metadata": item.get("metadata") or {},
            }
            for item in items
            if item.get("id")
        }
    except BdError as exc:
        # `bd` failed (missing binary, hung, bad DB): keep serving the
        # last-known map (possibly None) until the TTL expires.
        message = str(exc) or "bd list failed"
        _beads_last_error[key] = (now, message)
        _warn_once_per_window(key, now, fleet_home, message)
        prev = _beads_last_good.get(key)
        # Stamp expiry after the (possibly slow) subprocess call so the
        # entry is not born expired when `bd` itself exceeds the TTL.
        expires_at = time.monotonic() + _BEADS_CACHE_TTL
        if prev is not None:
            _beads_map_cache[key] = (expires_at, prev)
            return BeadsSnapshot(map=prev, available=False, error=message, stale=True)
        _beads_map_cache[key] = (expires_at, None)
        return BeadsSnapshot(map=None, available=False, error=message)
    _beads_last_good[key] = value
    _beads_last_ok_at[key] = now
    _beads_last_error.pop(key, None)
    _beads_map_cache[key] = (time.monotonic() + _BEADS_CACHE_TTL, value)
    return BeadsSnapshot(map=value, available=True)


def get_beads_status_map(fleet_home: Path) -> dict[str, dict] | None:
    """Return {task_id: {status, ...}} for all tasks in the beads DB at `fleet_home`.

    Returns None if beads never succeeded so the caller can skip
    reconciliation; while bd fails a previous good map keeps being
    served. Prefer get_beads_snapshot when the caller must surface
    bd reachability. Results are cached for _BEADS_CACHE_TTL seconds.
    """
    return get_beads_snapshot(fleet_home).map
