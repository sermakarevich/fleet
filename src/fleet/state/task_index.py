"""The one walker of `tasks/*`, one owner.

Called by serve/watcher.py, serve/api/tasks_*.py, serve/api/search.py,
serve/analytics/records.py, state/archive.py (and through it
orchestrator/retention_gc.py). Nobody else lists the tasks directory.
Raw task.json bodies are cached by file mtime, which is the cache the
serve watcher needs to poll statuses without re-reading every file.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fleet.state.paths import TASK_JSON, tasks_root
from fleet.state.task_meta import TaskMeta


@dataclass
class TaskIndex:
    """Cached listing of one fleet home's task directories."""

    fleet_home: Path
    _raw_cache: dict[str, tuple[float, dict[str, Any] | None]] = field(
        default_factory=dict, repr=False
    )

    def _tasks_dir(self) -> Path:
        return tasks_root(self.fleet_home)

    @property
    def tasks_dir(self) -> Path:
        """The tasks/ root this index walks."""
        return self._tasks_dir()

    def iter_dirs(self) -> Iterator[Path]:
        """Every task directory, sorted by name (even without task.json)."""
        tasks_dir = self._tasks_dir()
        if not tasks_dir.is_dir():
            return
        yield from sorted((p for p in tasks_dir.iterdir() if p.is_dir()), key=lambda p: p.name)

    def list_ids(self) -> list[str]:
        """Ids (dir names) that contain a readable task.json, sorted."""
        return [p.name for p, _ in self.iter_meta()]

    def iter_meta(self) -> Iterator[tuple[Path, dict[str, Any]]]:
        """(task_dir, raw task.json dict) for every readable task, sorted."""
        for task_dir in self.iter_dirs():
            raw = self.read_raw(task_dir.name)
            if raw is not None:
                yield task_dir, raw

    def find(self, task_id: str) -> Path | None:
        """Task dir for *task_id*, or None when it has no readable task.json."""
        if self.read_raw(task_id) is None:
            return None
        return self._tasks_dir() / task_id

    def read_raw(self, task_id: str) -> dict[str, Any] | None:
        """Raw task.json dict, cached by file mtime; None when unreadable."""
        task_file = self._tasks_dir() / task_id / TASK_JSON
        try:
            mtime = task_file.stat().st_mtime
        except OSError:
            self._raw_cache.pop(task_id, None)
            return None
        cached = self._raw_cache.get(task_id)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        try:
            raw = json.loads(task_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        parsed = raw if isinstance(raw, dict) else None
        self._raw_cache[task_id] = (mtime, parsed)
        return parsed

    def load_meta(self, task_id: str) -> TaskMeta | None:
        """Typed task.json view, or None when missing or unparseable."""
        task_dir = self._tasks_dir() / task_id
        return TaskMeta.load(task_dir)

    def status(self, task_id: str) -> str | None:
        """Cached status field for *task_id* (the watcher's hot path)."""
        raw = self.read_raw(task_id)
        return raw.get("status") if raw is not None else None

    def invalidate(self, task_id: str) -> None:
        """Drop the cached body for *task_id* (after an external write)."""
        self._raw_cache.pop(task_id, None)
