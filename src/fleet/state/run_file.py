"""The one owner of ``attempts/<n>/run.json``.

:class:`RunRecord` is the typed view of one attempt's run file: identity
(pid, host), lease (heartbeat), launch record, step timeline and exit
metrics. :meth:`RunRecord.load` is the only reader; :meth:`RunRecord.merge`
is the read-merge-write every step writer uses so concurrent writers (the
``llm_session`` heartbeat) never clobber each other's keys. Callers are
``workers/base.py``, ``workers/llm_session.py``, ``workers/task.py``,
``orchestrator/leases.py``, ``serve``/``state`` summary readers. The file
stays ``run.json`` on disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fleet.core.iso import now_iso
from fleet.state.atomic import write_json_atomic
from fleet.state.paths import RUN_JSON


@dataclass
class RunRecord:
    """Typed view of one attempt's run.json; unknown keys live in ``extra``."""

    pid: int | None = None
    pgid: int | None = None
    started_at: str | None = None
    heartbeat_at: str | None = None
    lease_until: str | None = None
    host: str | None = None
    worker: str | None = None
    coder: str | None = None
    supervisor_pid: int | None = None
    launch: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    exit_code: int | None = None
    ended_at: str | None = None
    peak_context_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def known_fields(cls) -> tuple[str, ...]:
        """Field names stored as named attributes (everything else is extra)."""
        return (
            "pid",
            "pgid",
            "started_at",
            "heartbeat_at",
            "lease_until",
            "host",
            "worker",
            "coder",
            "supervisor_pid",
            "launch",
            "steps",
            "exit_code",
            "ended_at",
            "peak_context_tokens",
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunRecord:
        """Split a raw run.json dict into named fields plus ``extra``."""
        known = cls.known_fields()
        values: dict[str, Any] = {}
        for key in known:
            if key == "steps":
                steps = data.get("steps")
                values["steps"] = (
                    [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []
                )
            else:
                values[key] = data.get(key)
        leftovers = {k: v for k, v in data.items() if k not in known}
        return cls(extra=leftovers, **values)

    def to_dict(self) -> dict[str, Any]:
        """Render back to a plain run.json dict (None fields omitted)."""
        data: dict[str, Any] = {}
        for key in self.known_fields():
            value = getattr(self, key)
            if key == "steps":
                data["steps"] = value
            elif value is not None:
                data[key] = value
        data.update(self.extra)
        return data

    @classmethod
    def path_for(cls, attempt_dir: Path) -> Path:
        """The run file inside *attempt_dir*."""
        return attempt_dir / RUN_JSON

    @classmethod
    def load(cls, attempt_dir: Path) -> RunRecord | None:
        """Read this attempt's run.json, or None when missing or unparseable."""
        try:
            raw = json.loads(cls.path_for(attempt_dir).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        return cls.from_dict(raw)

    def save(self, attempt_dir: Path) -> None:
        """Write this record back through the atomic writer."""
        write_json_atomic(self.path_for(attempt_dir), self.to_dict())

    @classmethod
    def merge(cls, attempt_dir: Path, **updates: Any) -> RunRecord:
        """Read-merge-write updates into run.json; steps never clobber keys."""
        record = cls.load(attempt_dir) or cls()
        known = set(cls.known_fields())
        for key, value in updates.items():
            if key in known:
                setattr(record, key, value)
            else:
                record.extra[key] = value
        record.save(attempt_dir)
        return record

    @classmethod
    def touch_lease(
        cls, attempt_dir: Path, until: str, heartbeat_at: str | None = None
    ) -> RunRecord:
        """Refresh the claim lease: set lease_until (and heartbeat_at=now)."""
        return cls.merge(
            attempt_dir,
            heartbeat_at=heartbeat_at or now_iso(),
            lease_until=until,
        )

    @classmethod
    def record_step(cls, attempt_dir: Path, worker_name: str, entry: dict[str, Any]) -> RunRecord:
        """Append one step timing entry and stamp the worker name."""
        record = cls.load(attempt_dir) or cls()
        record.worker = worker_name
        record.steps.append(entry)
        record.save(attempt_dir)
        return record
