"""The one owner of task.json inside `beads/`.

Called only by ``beads/queue.py``: every task.json read or write behind a
queue operation goes through :class:`TaskStore`, which persists through
``state/task_meta.py``. ``queue.py`` itself only talks to ``bd``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fleet.core.iso import now_iso, parse_iso
from fleet.core.task import Task
from fleet.core.triage_policy import ignore_active
from fleet.state.paths import task_dir
from fleet.state.task_meta import TaskMeta


def order_ready(items: list[dict]) -> list[dict]:
    """Claim order: highest priority first, then oldest created_at first."""
    return sorted(
        items,
        key=lambda c: (c.get("priority", 99), c.get("created_at") or ""),
    )


def build_task(body: dict, meta: dict, *, status_override: str | None = None) -> Task:
    """Build a Task from a `bd` body plus its task.json meta dict.

    The task.json fields win once they exist; `bd` metadata is the fallback
    that closes the race window for brand-new beads.
    """
    bd_meta = body.get("metadata") or {}
    raw_max = meta.get("max_attempt_minutes", bd_meta.get("fleet_max_attempt_minutes"))
    try:
        max_minutes = int(raw_max) if raw_max is not None else None
    except (TypeError, ValueError):
        max_minutes = None
    return Task(
        id=body["id"],
        title=body["title"],
        description=body.get("description"),
        status=status_override or body.get("status", "open"),
        cwd=meta.get("cwd") or bd_meta.get("fleet_cwd"),
        coder=meta.get("coder") or bd_meta.get("fleet_coder"),
        model=meta.get("model") or bd_meta.get("fleet_model"),
        type=body.get("issue_type"),
        worker=meta.get("worker") or bd_meta.get("fleet_worker"),
        max_attempt_minutes=max_minutes,
        retry_after=meta.get("retry_after"),
        ignore_until=meta.get("ignore_until"),
        isolation=meta.get("isolation") or bd_meta.get("fleet_isolation"),
        job_gate=meta.get("job_gate") or bd_meta.get("fleet_job_gate"),
        repo_root=meta.get("repo_root"),
        base_ref=meta.get("base_ref"),
        worktree_path=meta.get("worktree_path"),
    )


class TaskStore:
    """Reads and writes `tasks/<id>/task.json`; the only writer in `beads/`."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def _dir(self, task_id: str) -> Path:
        return task_dir(self.repo_root, task_id)

    def task_dir(self, task_id: str) -> Path:
        """Return the task's dir (used by delete to drop it)."""
        return self._dir(task_id)

    def read(self, task_id: str) -> dict:
        """Return the task.json dict, or {} when it does not exist yet."""
        meta = TaskMeta.load(self._dir(task_id))
        return meta.to_dict() if meta is not None else {}

    def write(self, task_id: str, data: dict) -> None:
        """Persist a full task.json dict (creates the task dir)."""
        task_dir = self._dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        TaskMeta.from_dict(task_id, data).save(task_dir)

    def set_cwd(self, task_id: str, cwd: str) -> None:
        """Persist the invocation cwd, preserving other fields if present."""
        TaskMeta.update(self._dir(task_id), cwd=cwd)

    def set_overrides(
        self,
        task_id: str,
        coder: str | None = None,
        model: str | None = None,
        worker: str | None = None,
        isolation: str | None = None,
        job_gate: str | None = None,
    ) -> None:
        """Persist per-task overrides; only non-None fields are written."""
        updates = {}
        if coder is not None:
            updates["coder"] = coder
        if model is not None:
            updates["model"] = model
        if worker is not None:
            updates["worker"] = worker
        if isolation is not None:
            updates["isolation"] = isolation
        if job_gate is not None:
            updates["job_gate"] = job_gate
        if updates:
            TaskMeta.update(self._dir(task_id), **updates)

    def set_bd_fields(self, task_id: str, body: dict) -> None:
        """Snapshot title/description/status/priority from a bd body into task.json."""
        meta = self.read(task_id) or {"id": task_id}
        for key in ("title", "description", "status", "priority"):
            val = body.get(key)
            if val is not None:
                meta[key] = val
        self.write(task_id, meta)

    def freeze_coder_model(self, task_id: str, coder: str, model: str | None) -> None:
        """Lock the effective coder and model at first spawn."""
        TaskMeta.update(self._dir(task_id), coder=coder, model=model)

    def snapshot(
        self,
        body: dict,
        status: str | None = None,
        cwd: str | None = None,
        coder: str | None = None,
        model: str | None = None,
        worker: str | None = None,
        depends_on: list[str] | None = None,
    ) -> dict:
        """Build a task.json payload from a bd body, preserving fleet fields."""
        existing = self.read(body["id"])
        result: dict = {
            "id": body["id"],
            "title": body.get("title", existing.get("title")),
            "description": body.get("description", existing.get("description")),
            "status": status or body.get("status") or existing.get("status", "open"),
            "cwd": cwd if cwd is not None else existing.get("cwd"),
            "coder": coder if coder is not None else existing.get("coder"),
            "model": model if model is not None else existing.get("model"),
        }
        eff_worker = worker if worker is not None else existing.get("worker")
        if eff_worker is not None:
            result["worker"] = eff_worker
        priority = (
            body.get("priority") if body.get("priority") is not None else existing.get("priority")
        )
        if priority is not None:
            result["priority"] = priority
        deps = depends_on if depends_on is not None else existing.get("depends_on")
        if deps:
            result["depends_on"] = deps
        for key in (
            "retry_after",
            "max_attempt_minutes",
            "ignore_until",
            "isolation",
            "job_gate",
            "repo_root",
            "base_ref",
            "worktree_path",
        ):
            if existing.get(key) is not None:
                result[key] = existing.get(key)
        return result

    def mark_released(self, task_id: str, wait_sec: int = 0) -> None:
        """Record an open release in task.json, with an optional retry delay."""
        meta = self.read(task_id) or {"id": task_id}
        meta["status"] = "open"
        meta.pop("blocked_reason", None)
        meta.pop("blocked_at", None)
        meta.pop("ignore_until", None)
        if wait_sec and wait_sec > 0:
            meta["retry_after"] = (
                datetime.now(tz=UTC) + timedelta(seconds=int(wait_sec))
            ).isoformat()
        else:
            meta.pop("retry_after", None)
        self.write(task_id, meta)

    def mark_blocked(self, task_id: str, reason: str) -> None:
        """Record a blocked transition in task.json."""
        meta = self.read(task_id) or {"id": task_id}
        meta["status"] = "blocked"
        meta["blocked_reason"] = reason
        meta["blocked_at"] = now_iso()
        meta.pop("retry_after", None)
        meta.pop("ignore_until", None)
        self.write(task_id, meta)

    def mark_closed(self, task_id: str) -> None:
        """Record a closed transition in task.json."""
        meta = self.read(task_id) or {"id": task_id}
        meta["status"] = "closed"
        meta.pop("blocked_reason", None)
        meta.pop("blocked_at", None)
        meta.pop("retry_after", None)
        meta.pop("ignore_until", None)
        self.write(task_id, meta)

    def retry_after_active(self, task_id: str) -> bool:
        """True when task.json retry_after is still in the future."""
        raw = self.read(task_id).get("retry_after")
        if not raw or not isinstance(raw, str):
            return False
        parsed = parse_iso(raw)
        if parsed is None:
            return False
        return parsed > datetime.now(tz=UTC)

    def set_ignore(self, task_id: str, ignore_until: str) -> None:
        """Suppress triage for a blocked task until an ISO time or "forever"."""
        meta = self.read(task_id) or {"id": task_id}
        meta["ignore_until"] = ignore_until
        self.write(task_id, meta)

    def clear_ignore(self, task_id: str) -> None:
        """Lift a triage ignore so the next tick asks again."""
        meta = self.read(task_id) or {"id": task_id}
        if "ignore_until" in meta:
            del meta["ignore_until"]
            self.write(task_id, meta)

    def active_ignore(self, task_id: str) -> str | None:
        """Return the ignore_until value when it is still active, else None."""
        raw = self.read(task_id).get("ignore_until")
        if isinstance(raw, str) and ignore_active(raw):
            return raw
        return None

    def set_isolation_info(
        self,
        task_id: str,
        repo_root: str,
        base_ref: str,
        worktree_path: str,
    ) -> None:
        """Persist git isolation info, preserving other fields."""
        TaskMeta.update(
            self._dir(task_id),
            repo_root=repo_root,
            base_ref=base_ref,
            worktree_path=worktree_path,
        )

    def clear_isolation_info(self, task_id: str) -> None:
        """Drop git isolation info after merge/cleanup."""
        if not any(k in self.read(task_id) for k in ("repo_root", "base_ref", "worktree_path")):
            return
        TaskMeta.clear(self._dir(task_id), "repo_root", "base_ref", "worktree_path")

    def read_isolation_info(self, task_id: str) -> dict | None:
        """Return {repo_root, base_ref, worktree_path} or None when not isolated."""
        meta = self.read(task_id)
        repo_root = meta.get("repo_root")
        base_ref = meta.get("base_ref")
        worktree_path = meta.get("worktree_path")
        if repo_root and base_ref and worktree_path:
            return {
                "repo_root": repo_root,
                "base_ref": base_ref,
                "worktree_path": worktree_path,
            }
        try:
            marker = self._dir(task_id) / ".worktree"
            if marker.exists():
                text = marker.read_text(encoding="utf-8").strip()
                if text:
                    return {
                        "repo_root": repo_root or "",
                        "base_ref": base_ref or "main",
                        "worktree_path": text,
                    }
        except OSError:
            pass
        return None

    def select_ignored(self, tasks: list[Task]) -> list[tuple[Task, str]]:
        """Filter blocked tasks down to those with an active triage ignore."""
        out: list[tuple[Task, str]] = []
        for task in tasks:
            raw = self.active_ignore(task.id)
            if raw is not None:
                out.append((task, raw))
        return out

    def coder_of(self, task_id: str, body: dict[str, Any]) -> str | None:
        """Effective coder for claim filtering: task.json first, bd metadata fallback."""
        return self.read(task_id).get("coder") or (body.get("metadata") or {}).get("fleet_coder")
