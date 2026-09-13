"""TTL-cached map of beads status by task id, built from beads.client.list_all.

Avoids a `bd list` subprocess on every poll from the API/CLI layers.
Called by serve/api/tasks.py, serve/analytics/summary.py and cli/format.py.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from fleet.beads import client as beads_client
from fleet.beads.client import BdError

# TTL cache — key: str(fleet_home), value: (expires_at, result)
_beads_map_cache: dict[str, tuple[float, dict[str, dict] | None]] = {}
_BEADS_CACHE_TTL: float = 15.0

_beads_list_call_count: int = 0  # incremented on each real subprocess call; observable in tests

# Single-flight lock: only one thread may run the bd subprocess at a time.
# A thread that loses the race returns the last-known (possibly stale) map
# immediately instead of blocking behind the refresh.
_refresh_lock = threading.Lock()


def _build_status_map(items: list[dict]) -> dict[str, dict]:
    return {
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


def _do_refresh(fleet_home: Path, key: str) -> dict[str, dict] | None:
    """Run the bd subprocess and update the cache. Caller must hold `_refresh_lock`."""
    global _beads_list_call_count  # noqa: PLW0603  # ADR 0006 bead 4 owns beads/ shared state
    now = time.monotonic()
    previous = _beads_map_cache.get(key)
    previous_value = previous[1] if previous is not None else None

    result_value: dict[str, dict] | None = previous_value
    try:
        _beads_list_call_count += 1
        items = beads_client.list_all(fleet_home)
        result_value = _build_status_map(items)
    except BdError:
        # `bd` failed (missing binary, hung, bad DB): keep serving the
        # last-known map (possibly None) so callers never see a spurious gap.
        # Extend the expiry so we don't retry more than once per TTL.
        pass
    _beads_map_cache[key] = (now + _BEADS_CACHE_TTL, result_value)
    return result_value


def get_beads_status_map(fleet_home: Path) -> dict[str, dict] | None:
    """Return {task_id: {status, ...}} for all tasks in the beads DB at `fleet_home`.

    Returns None if beads is unavailable so the caller can skip reconciliation.
    Results are cached for _BEADS_CACHE_TTL seconds to avoid a subprocess on every poll.
    Never blocks a request behind a concurrent refresh: if another thread is
    already refreshing, the last-known (possibly stale) map is returned instead.
    """
    key = str(fleet_home)
    now = time.monotonic()
    cached = _beads_map_cache.get(key)
    if cached is not None and now < cached[0]:
        return cached[1]

    acquired = _refresh_lock.acquire(blocking=False)
    if not acquired:
        if cached is not None:
            return cached[1]
        # No last-known map yet: block for the first refresh so callers get data.
        with _refresh_lock:
            return _do_refresh(fleet_home, key)
    try:
        return _do_refresh(fleet_home, key)
    finally:
        _refresh_lock.release()


def refresh_beads_status_map(fleet_home: Path) -> dict[str, dict] | None:
    """Force a synchronous refresh of the cache, bypassing the TTL check.

    Used by a background refresher to keep the cache warm without waiting
    for a request to trigger an expiry.
    """
    key = str(fleet_home)
    with _refresh_lock:
        return _do_refresh(fleet_home, key)
