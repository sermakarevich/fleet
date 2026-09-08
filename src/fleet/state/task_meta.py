"""The one owner of ``task.json``.

Every read and write of ``tasks/<id>/task.json`` goes through
:class:`TaskMeta`. Callers are ``beads/queue.py`` (claim snapshots,
overrides, block/close/release), ``state/archive.py`` (retention scans),
``orchestrator/spawn.py`` (via the queue's ``freeze_coder_model``) and
``serve/api/tasks.py`` (unblock, remove-assignee). File format is unchanged:
``extra`` carries every key without a named field so nothing is ever lost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fleet.state.atomic import write_json_atomic
from fleet.state.paths import TASK_JSON


@dataclass
class TaskMeta:
    """Typed view of one task.json file; unknown keys live in ``extra``."""

    id: str = ""
    title: str | None = None
    description: str | None = None
    status: str | None = None
    cwd: str | None = None
    coder: str | None = None
    model: str | None = None
    worker: str | None = None
    isolation: str | None = None
    blocked_reason: str | None = None
    blocked_at: str | None = None
    repo_root: str | None = None
    base_ref: str | None = None
    worktree_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def known_fields(cls) -> tuple[str, ...]:
        """Field names stored as named attributes (everything else is extra)."""
        return (
            "id",
            "title",
            "description",
            "status",
            "cwd",
            "coder",
            "model",
            "worker",
            "isolation",
            "blocked_reason",
            "blocked_at",
            "repo_root",
            "base_ref",
            "worktree_path",
        )

    @classmethod
    def from_dict(cls, task_id: str, data: dict[str, Any]) -> TaskMeta:
        """Split a raw task.json dict into named fields plus ``extra``."""
        known = cls.known_fields()
        values = {k: data.get(k) for k in known if k != "id"}
        leftovers = {k: v for k, v in data.items() if k not in known}
        return cls(id=data.get("id", task_id), extra=leftovers, **values)

    def to_dict(self) -> dict[str, Any]:
        """Render back to a plain task.json dict (None fields omitted).

        Absent and null mean the same to every reader (``meta.get(...)``),
        and omitting keeps ``clear()``/pops byte-stable with the old code.
        ``extra`` is kept verbatim so unknown keys are never lost.
        """
        data = {k: getattr(self, k) for k in self.known_fields() if getattr(self, k) is not None}
        data.update(self.extra)
        return data

    @classmethod
    def load(cls, task_dir: Path) -> TaskMeta | None:
        """Read task.json, or None when missing or unparseable."""
        try:
            raw = json.loads((task_dir / TASK_JSON).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        return cls.from_dict(task_dir.name, raw)

    def save(self, task_dir: Path) -> None:
        """Write this meta back to task.json through the atomic writer."""
        write_json_atomic(task_dir / TASK_JSON, self.to_dict())

    @classmethod
    def update(cls, task_dir: Path, **fields: Any) -> TaskMeta:
        """Read-merge-write: set *fields* (None writes null), return the meta."""
        meta = cls.load(task_dir) or cls(id=task_dir.name)
        known = set(cls.known_fields())
        for key, value in fields.items():
            if key in known:
                setattr(meta, key, value)
            else:
                meta.extra[key] = value
        meta.save(task_dir)
        return meta

    @classmethod
    def clear(cls, task_dir: Path, *keys: str) -> TaskMeta:
        """Read-merge-write: drop *keys* (named fields reset to None)."""
        meta = cls.load(task_dir) or cls(id=task_dir.name)
        known = set(cls.known_fields())
        for key in keys:
            if key in known:
                setattr(meta, key, None)
            else:
                meta.extra.pop(key, None)
        meta.save(task_dir)
        return meta
