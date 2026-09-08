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


@dataclass
class PurgeResult:
    deleted: list[str]
    skipped: int
    bytes_freed: int


@dataclass
class StaleWorktree:
    task_id: str
    path: Path
    repo_root: str | None


def _dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def gc_tasks(home: Path, days: int = 30, dry_run: bool = False) -> GcResult:
    tasks_dir = tasks_root(home)
    archive_dir = home / "archive" / "tasks"
    result = GcResult(archived=[], skipped=0, bytes_moved=0)
    if days <= 0:
        return result
    cutoff = time.time() - days * 86400
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


def purge_archive(home: Path, days: int = 90, dry_run: bool = False) -> PurgeResult:
    """Permanently delete archived task dirs older than *days*.

    Only directories under ``<home>/archive/tasks/`` are considered.
    *days* <= 0 disables purging (returns everything as skipped).
    """
    result = PurgeResult(deleted=[], skipped=0, bytes_freed=0)
    archive_dir = home / "archive" / "tasks"
    if days <= 0 or not archive_dir.is_dir():
        return result
    cutoff = time.time() - days * 86400
    for entry in sorted(archive_dir.iterdir()):
        if not entry.is_dir() or entry.stat().st_mtime > cutoff:
            result.skipped += 1
            continue
        size = _dir_size(entry)
        result.deleted.append(entry.name)
        result.bytes_freed += size
        if not dry_run:
            shutil.rmtree(entry, ignore_errors=True)
    return result


def _task_meta(task_dir: Path) -> dict:
    try:
        data = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _closed_and_old(task_dir: Path, cutoff: float) -> bool:
    """True when task.json says closed and the dir predates *cutoff*."""
    try:
        old_mtime = task_dir.stat().st_mtime <= cutoff
    except OSError:
        return False
    return old_mtime and _task_meta(task_dir).get("status") == "closed"


def find_stale_worktrees(home: Path, days: int = 30) -> list[StaleWorktree]:
    """Worktrees whose task is closed and older than *days*.

    Selection only — the caller removes them (e.g. via
    ``orchestrator.worktree.cleanup_worktree``). A worktree dir matches a
    task when it is named ``<task_id>`` (legacy) or
    ``<repo>-<task_id>``. *days* <= 0 returns no candidates.
    """
    if days <= 0:
        return []
    tasks_dir = tasks_root(home)
    worktrees_dir = home / "worktrees"
    if not worktrees_dir.is_dir():
        return []
    cutoff = time.time() - days * 86400
    stale_tasks: dict[str, dict] = {}
    if tasks_dir.is_dir():
        for task_dir in sorted(tasks_dir.iterdir()):
            if task_dir.is_dir() and _closed_and_old(task_dir, cutoff):
                stale_tasks[task_dir.name] = _task_meta(task_dir)
    found: list[StaleWorktree] = []
    for wt in sorted(worktrees_dir.iterdir()):
        if not wt.is_dir():
            continue
        match = next(
            (tid for tid in stale_tasks if wt.name == tid or wt.name.endswith(f"-{tid}")),
            None,
        )
        if match is None:
            continue
        meta = stale_tasks[match]
        wt_path = meta.get("worktree_path")
        repo_root = meta.get("repo_root")
        if wt_path and Path(wt_path).resolve() != wt.resolve():
            continue
        found.append(StaleWorktree(task_id=match, path=wt, repo_root=repo_root))
    return found
