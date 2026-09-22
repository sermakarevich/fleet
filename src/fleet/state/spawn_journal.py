"""Is a job's spawn phase finished? (children.json vs tasks.json).

SpawnChildren journals every child it creates, so a crash or a timeout
mid-spawn leaves a partial journal. Both the phase table (`workers.job`)
and the ready-epic filter (`beads.queue`) need the same answer, and the
beads layer may not import workers, so the check lives here.
"""

from __future__ import annotations

import json
from pathlib import Path


def _load_map(path: Path) -> dict:
    """Read a `{key: value}` journal; empty when missing or corrupt."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def spawn_complete(task_dir: Path) -> bool:
    """True when children.json covers every key in tasks.json.

    A missing or unreadable tasks.json, a plan without keys, and a missing
    journal (children created outside SpawnChildren) all count as complete,
    so callers fall back to their previous behaviour.
    """
    artifacts = task_dir / "artifacts"
    doc = _load_map(artifacts / "tasks.json")
    tasks = doc.get("tasks")
    if not isinstance(tasks, list):
        return True
    keys = [str(t["key"]) for t in tasks if isinstance(t, dict) and t.get("key")]
    if not keys:
        return True
    created = _load_map(artifacts / "children.json")
    if not created:
        return True
    skipped = _load_map(artifacts / "children_skipped.json")
    return all(key in created or key in skipped for key in keys)
