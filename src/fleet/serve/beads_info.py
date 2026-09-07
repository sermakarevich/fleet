"""Reconcile task.json statuses against the beads DB (authoritative source of truth).

TTL-cached to avoid a subprocess on every poll.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

# TTL cache — key: str(home), value: (expires_at, result)
_beads_map_cache: dict[str, tuple[float, dict[str, dict] | None]] = {}
_BEADS_CACHE_TTL: float = 5.0

_beads_list_call_count: int = 0  # incremented on each real subprocess call; observable in tests


def get_beads_status_map(home: Path) -> dict[str, dict] | None:
    """Return {task_id: {status, created_at, priority, title, description, notes}} for all tasks in the beads DB at `home`.

    Returns None if beads is unavailable so the caller can skip reconciliation.
    Results are cached for _BEADS_CACHE_TTL seconds to avoid a subprocess on every poll.
    """
    global _beads_list_call_count
    key = str(home)
    now = time.monotonic()
    cached = _beads_map_cache.get(key)
    if cached is not None and now < cached[0]:
        return cached[1]

    result_value: dict[str, dict] | None = None
    try:
        _beads_list_call_count += 1
        result = subprocess.run(
            ["bd", "list", "--all", "--json", "--limit", "0"],
            capture_output=True,
            text=True,
            cwd=home,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            items: list = (
                data.get("data", data) if isinstance(data, dict) else (data or [])
            )
            if isinstance(items, list):
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
    except Exception:
        pass
    _beads_map_cache[key] = (now + _BEADS_CACHE_TTL, result_value)
    return result_value
