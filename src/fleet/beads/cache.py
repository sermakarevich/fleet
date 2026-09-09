"""TTL-cached map of beads status by task id, built from beads.client.list_all.

Avoids a `bd list` subprocess on every poll from the API/CLI layers.
Called by serve/api/tasks.py, serve/analytics/summary.py and cli/format.py.
"""

from __future__ import annotations

import time
from pathlib import Path

from fleet.beads import client as beads_client
from fleet.beads.client import BdError

# TTL cache — key: str(fleet_home), value: (expires_at, result)
_beads_map_cache: dict[str, tuple[float, dict[str, dict] | None]] = {}
_BEADS_CACHE_TTL: float = 5.0

_beads_list_call_count: int = 0  # incremented on each real subprocess call; observable in tests


def get_beads_status_map(fleet_home: Path) -> dict[str, dict] | None:
    """Return {task_id: {status, ...}} for all tasks in the beads DB at `fleet_home`.

    Returns None if beads is unavailable so the caller can skip reconciliation.
    Results are cached for _BEADS_CACHE_TTL seconds to avoid a subprocess on every poll.
    """
    global _beads_list_call_count  # noqa: PLW0603  # ADR 0006 bead 4 owns beads/ shared state
    key = str(fleet_home)
    now = time.monotonic()
    cached = _beads_map_cache.get(key)
    if cached is not None and now < cached[0]:
        return cached[1]

    result_value: dict[str, dict] | None = None
    try:
        _beads_list_call_count += 1
        items = beads_client.list_all(fleet_home)
        result_value = {
            item["id"]: {
                "status": item.get("status", "open"),
                "created_at": item.get("created_at"),
                "priority": item.get("priority"),
                "title": item.get("title"),
                "description": item.get("description"),
                "notes": item.get("notes"),
            }
            for item in items
            if item.get("id")
        }
    except BdError:
        # `bd` failed (missing binary, hung, bad DB): keep serving the
        # last-known map (possibly None) until the TTL expires.
        pass
    _beads_map_cache[key] = (now + _BEADS_CACHE_TTL, result_value)
    return result_value
