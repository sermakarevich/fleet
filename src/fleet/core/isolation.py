"""One reader for git-isolation info: task.json plus the legacy marker.

Called by ``orchestrator/claim.py`` (spawn path), ``orchestrator/reap.py``
(isolated-success decision) and ``orchestrator/merge_validation.py``. The
dataclass is the single shape; ``read`` is the single reader. Replaces the
duplicated task.json + ``.worktree`` parsing that lived in claim and reap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class IsolationInfo:
    """Where an isolated task runs: repo root, base ref, worktree dir."""

    repo_root: str
    base_ref: str
    worktree_path: str


def from_meta(meta: dict) -> IsolationInfo | None:
    """Build IsolationInfo from a parsed task.json dict, or None when absent."""
    repo_root = meta.get("repo_root")
    base_ref = meta.get("base_ref")
    worktree_path = meta.get("worktree_path")
    if repo_root and base_ref and worktree_path:
        return IsolationInfo(
            repo_root=str(repo_root),
            base_ref=str(base_ref),
            worktree_path=str(worktree_path),
        )
    return None


def read(task_dir: Path) -> IsolationInfo | None:
    """Read repo_root/base_ref/worktree_path from task.json, or None.

    Falls back to the legacy ``.worktree`` marker for old task dirs.
    Never raises: missing or unparsable files read as "not isolated".
    """
    try:
        meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    if isinstance(meta, dict):
        info = from_meta(meta)
        if info is not None:
            return info
    try:
        marker = task_dir / ".worktree"
        if marker.exists():
            text = marker.read_text(encoding="utf-8").strip()
            if text:
                base = meta.get("base_ref") if isinstance(meta, dict) else None
                repo = meta.get("repo_root") if isinstance(meta, dict) else ""
                return IsolationInfo(
                    repo_root=str(repo or ""),
                    base_ref=str(base or "main"),
                    worktree_path=text,
                )
    except OSError:
        pass
    return None
