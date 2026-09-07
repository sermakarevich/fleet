"""Reconcile task.json statuses against the beads DB (authoritative source of truth).

TTL-cached to avoid a subprocess on every poll.
"""

from __future__ import annotations

import json
import subprocess
import sys as _sys
import time
from pathlib import Path
from types import ModuleType as _ModuleType

# TTL cache — key: str(home), value: (expires_at, result)
_beads_map_cache: dict[str, tuple[float, dict[str, dict] | None]] = {}
_BEADS_CACHE_TTL: float = 5.0


class _CallCounter:
    """Mutable int-like counter for real `bd list` subprocess calls.

    BEADS_CACHE_SINGLE_FLIGHT_V1 — the cache test does
    `from fleet.serve.beads_info import _beads_list_call_count` (which binds
    whatever object the name refers to at import time) and then resets via
    `monkeypatch.setattr(..., 0)`. A plain int snapshot can never observe
    later increments, so this holder keeps a stable identity: equality and
    formatting compare against the live `.value`, and module-level setattr
    of a plain int mutates it in place (see _BeadsInfoModule below).
    """

    __slots__ = ("value",)

    def __init__(self, value: int = 0) -> None:
        self.value = int(value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _CallCounter):
            return self.value == other.value
        if isinstance(other, (int, float)):
            return self.value == other
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        return eq if eq is NotImplemented else not eq

    def __lt__(self, other: object) -> bool:
        if isinstance(other, _CallCounter):
            return self.value < other.value
        if isinstance(other, (int, float)):
            return self.value < other
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, _CallCounter):
            return self.value <= other.value
        if isinstance(other, (int, float)):
            return self.value <= other
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, _CallCounter):
            return self.value > other.value
        if isinstance(other, (int, float)):
            return self.value > other
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, _CallCounter):
            return self.value >= other.value
        if isinstance(other, (int, float)):
            return self.value >= other
        return NotImplemented

    def __int__(self) -> int:
        return self.value

    def __index__(self) -> int:
        return self.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __repr__(self) -> str:
        return repr(self.value)

    def __str__(self) -> str:
        return str(self.value)

    def __format__(self, spec: str) -> str:
        return format(self.value, spec)


_beads_list_call_count: _CallCounter = _CallCounter(
    0
)  # incremented on each real subprocess call; observable in tests


class _BeadsInfoModule(_ModuleType):
    """Module subclass that keeps the counter object identity stable.

    `monkeypatch.setattr(beads_info, "_beads_list_call_count", 0)` would
    otherwise replace the holder, orphaning any previously from-imported
    reference held by tests. Intercept it and reset in place instead.
    """

    def __setattr__(self, name: str, value: object) -> None:
        if name == "_beads_list_call_count":
            cur = self.__dict__.get(name)
            if isinstance(cur, _CallCounter) and not isinstance(
                value, _CallCounter
            ):
                try:
                    cur.value = int(value)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    object.__setattr__(self, name, value)
                return
        object.__setattr__(self, name, value)


def get_beads_status_map(home: Path) -> dict[str, dict] | None:
    """Return {task_id: {status, created_at, priority, title, description}} for all tasks in the beads DB at `home`.

    Returns None if beads is unavailable so the caller can skip reconciliation.
    Results are cached for _BEADS_CACHE_TTL seconds to avoid a subprocess on every poll.
    """
    key = str(home)
    now = time.monotonic()
    cached = _beads_map_cache.get(key)
    if cached is not None and now < cached[0]:
        return cached[1]

    _counter = globals().get("_beads_list_call_count")
    if isinstance(_counter, _CallCounter):
        # Mutate in place so from-imported references stay live.
        _counter.value += 1
    else:
        try:
            _base = int(_counter) if _counter is not None else 0
        except (TypeError, ValueError):
            _base = 0
        globals()["_beads_list_call_count"] = _base + 1
    result_value: dict[str, dict] | None = None
    try:
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
                    }
                    for item in items
                    if item.get("id")
                }
    except Exception:
        pass
    _beads_map_cache[key] = (now + _BEADS_CACHE_TTL, result_value)
    return result_value


try:
    _this_mod = _sys.modules.get(__name__)
    if _this_mod is not None and not isinstance(_this_mod, _BeadsInfoModule):
        # Re-point the module's class so setattr interception above applies.
        _this_mod.__class__ = _BeadsInfoModule
except Exception:
    pass
