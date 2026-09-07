"""Archive closed task directories older than a retention window."""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from fleet.state.paths import tasks_root


@dataclass
class GcResult:
    archived: list[str]
    skipped: int
    bytes_moved: int

def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

def gc_tasks(home: Path, days: int = 30, dry_run: bool = False) -> GcResult:
    tasks_dir = tasks_root(home)
    archive_dir = home / "archive" / "tasks"
    cutoff = time.time() - days * 86400
    result = GcResult(archived=[], skipped=0, bytes_moved=0)
    if not tasks_dir.is_dir():
        return result
    for task_dir in sorted(tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        meta_path = task_dir / "task.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result.skipped += 1
            continue
        if meta.get("status") != "closed" or task_dir.stat().st_mtime > cutoff:
            result.skipped += 1
            continue
        size = _dir_size(task_dir)
        result.archived.append(task_dir.name)
        result.bytes_moved += size
        if not dry_run:
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(task_dir), str(archive_dir / task_dir.name))
    return result
