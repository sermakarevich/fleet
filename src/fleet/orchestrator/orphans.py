from __future__ import annotations

import json
import os
import signal

from fleet.state.counters import needs_validation
from fleet.state.paths import task_dir as _task_dir

from . import worktree


class OrphansMixin:
    def _sweep_orphan_worktrees(self) -> None:
        """Remove worktrees with no corresponding active task (startup sweep)."""
        worktrees_dir = worktree.worktree_path("")
        if not worktrees_dir.is_dir():
            return

        fleet_home = worktrees_dir.parent

        for worktree_dir in worktrees_dir.iterdir():
            if not worktree_dir.is_dir():
                continue

            task_id = worktree_dir.name

            if task_id in self.in_flight:
                continue

            task_dir = _task_dir(fleet_home, task_id)
            if needs_validation(task_dir):
                continue

            self._log.info("worktree.sweep.removed", task_id=task_id)
            worktree.remove_worktree(self._project_root, task_id)

    def _reconcile_orphans(self) -> None:
        """Release in_progress claims left behind by a previous supervisor."""
        try:
            in_progress = self._queue.list_in_progress(limit=500)
        except Exception as exc:
            self._log.warning("reconcile_list_failed", error=str(exc))
            return
        for task in in_progress:
            if task.id in self.in_flight:
                continue
            run_file = self._task_dir_for(task) / "run.json"
            pid: int | None = None
            ended = False
            try:
                data = json.loads(run_file.read_text(encoding="utf-8"))
                pid = data.get("pid")
                ended = data.get("ended_at") is not None
            except (OSError, ValueError):
                pass
            alive = False
            if pid and not ended:
                try:
                    os.kill(pid, 0)
                    alive = True
                except (ProcessLookupError, PermissionError):
                    alive = False
            if alive:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            reason = "supervisor restarted; orphaned claim released" + (" (stale process terminated)" if alive else "")
            try:
                self._queue.release(task.id, reason=reason)
                self._log.warning("task_orphan_released", task_id=task.id, pid=pid, was_alive=alive)
            except Exception as exc:
                self._log.warning("task_orphan_release_failed", task_id=task.id, error=str(exc))
