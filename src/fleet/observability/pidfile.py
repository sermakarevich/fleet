"""Typed PID-file record for fleet's managed daemons.

The single owner of daemon PID files (ADR 0006 rule 1): ``PidFile`` is the
one record, ``read`` the one reader, ``write`` the one writer. Called by
``observability/daemon.py`` (start/stop/status), ``observability/process.py``
(liveness for the serve API), ``cli/daemons.py`` (stored serve host/port)
and ``serve/api/supervisor.py`` (restart facts). Nobody else parses them.

Versioning: files written by :func:`write` carry ``"version": 1``. Older
files (a dict without the marker, a bare-integer file, a JSON integer)
still read, tagged ``version=0``, so daemons started before this change
keep reporting until their next restart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fleet.state.atomic import write_json_atomic

#: Current PID-file schema version stamped by write().
PIDFILE_VERSION: int = 1

#: Top-level keys owned by the record; everything else is daemon extras.
_RESERVED_KEYS: frozenset[str] = frozenset({"version", "pid", "started_at", "version_fingerprint"})


@dataclass(frozen=True)
class PidFile:
    """One daemon PID file: identity, start facts, and daemon extras."""

    version: int = PIDFILE_VERSION
    pid: int = 0
    started_at: str | None = None
    fingerprint: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _legacy_pid(value: Any) -> int | None:
    """PID int from a legacy payload, or None when unparseable."""
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid or None


def read(path: Path) -> PidFile | None:
    """Parse the PID file at *path*, or None when absent/unreadable."""
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return _legacy_record(text)
    if isinstance(data, int):
        return _legacy_record(data)
    if not isinstance(data, dict):
        return None
    return _record_from_dict(data)


def _legacy_record(value: Any) -> PidFile | None:
    """A pre-version PID payload (bare int or JSON int) as a version-0 record."""
    if isinstance(value, str) and not value.isdigit():
        return None
    pid = _legacy_pid(value)
    if pid is None:
        return None
    return PidFile(version=0, pid=pid)


def _record_from_dict(data: dict[str, Any]) -> PidFile | None:
    """A dict payload as a record; unversioned dicts are legacy (version 0)."""
    pid = _legacy_pid(data.get("pid"))
    if pid is None:
        return None
    try:
        version = int(data.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    extra = {k: v for k, v in data.items() if k not in _RESERVED_KEYS}
    return PidFile(
        version=version,
        pid=pid,
        started_at=data.get("started_at"),
        fingerprint=data.get("version_fingerprint"),
        extra=extra,
    )


def write(path: Path, record: PidFile) -> None:
    """Persist *record* atomically, flattening extras beside the owned keys."""
    payload: dict[str, Any] = {
        "version": record.version,
        "pid": record.pid,
        "started_at": record.started_at,
        "version_fingerprint": record.fingerprint,
        **record.extra,
    }
    write_json_atomic(Path(path), payload)
