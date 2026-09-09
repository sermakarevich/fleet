"""Beads-backed task queue: the orchestrator's view of `bd`.

Called by ``orchestrator/`` (claim, spawn, reap, leases, triage,
merge_validation), ``serve/api/tasks.py``, ``cli/tasks.py``,
``cli/beads.py``, ``workers/observe.py``, ``workers/job.py`` and
``integrations/telegram/commands.py``. This module only talks to ``bd``
(through :class:`BdClient`); every task.json read or write lives in
``beads/task_store.py``.
"""

from __future__ import annotations

import contextlib
import shlex
import shutil
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from fleet.beads.client import BdClient, BdError, children_of
from fleet.beads.task_store import TaskStore, build_task, order_ready
from fleet.core.job_ready import BeadSummary, children_terminal
from fleet.core.task import Task


class Queue(ABC):
    """Everything the orchestrator, serve, CLI and workers need from `bd`."""

    # -- claiming: ready() lists, claim(id) moves, claim_next picks --
    @abstractmethod
    def claim_next(
        self, claimer_id: str, *, can_claim: Callable[[str | None], bool] | None = None
    ) -> Task | None:
        """Claim the highest-priority claimable open task, or None."""
        ...

    @abstractmethod
    def claim(self, task_id: str, claimer_id: str) -> Task:
        """Move one open task to in_progress and write its lease."""
        ...

    @abstractmethod
    def release(self, task_id: str, reason: str = "", wait_sec: int = 0) -> None:
        """Return a task to open, with an optional retry delay."""
        ...

    # -- terminal/reporting transitions: close, block, comment --
    @abstractmethod
    def close(self, task_id: str, reason: str = "completed") -> None:
        """Close a task with a reason."""
        ...

    @abstractmethod
    def set_blocked(self, task_id: str, reason: str) -> None:
        """Mark a task blocked with a reason."""
        ...

    @abstractmethod
    def comment(self, task_id: str, body: str) -> None:
        """Append a comment to a task."""
        ...

    # -- reads: show one, list by status, children --
    @abstractmethod
    def get(self, task_id: str) -> Task:
        """Show one task by id."""
        ...

    @abstractmethod
    def list_ready(self, limit: int = 50) -> list[Task]:
        """List open tasks whose dependencies are all closed."""
        ...

    @abstractmethod
    def list_in_progress(self, limit: int = 50) -> list[Task]:
        """List claimed tasks."""
        ...

    @abstractmethod
    def list_blocked(self, limit: int = 100) -> list[Task]:
        """List blocked tasks."""
        ...

    @abstractmethod
    def list_ignored(self, limit: int = 100) -> list[tuple[Task, str]]:
        """List blocked tasks whose triage ignore is still active."""
        ...

    @abstractmethod
    def list_by_metadata(self, field: str, value: str) -> list[Task]:
        """Tasks whose bd metadata `field` equals `value` (one workflow run)."""
        ...

    @abstractmethod
    def list_children(self, epic_id: str) -> list[BeadSummary]:
        """List an epic's child beads with their statuses."""
        ...

    @abstractmethod
    def delete(self, task_id: str) -> None:
        """Delete a task and drop its task dir."""
        ...

    # -- creation --
    @abstractmethod
    def create_task(  # noqa: PLR0913, PLR0917  # ADR 0006 bead 4
        self,
        title: str,
        description: str | None = None,
        depends_on: list[str] | None = None,
        labels: list[str] | None = None,
        cwd: str | None = None,
        coder: str | None = None,
        model: str | None = None,
        worker: str | None = None,
        extra_args: str | None = None,
    ) -> Task:
        """Open a new task and snapshot it to task.json."""
        ...

    @abstractmethod
    def create_child(self, epic_id: str, spec: dict) -> Task:
        """Open one child bead under an epic; raises when the dep link fails."""
        ...

    # -- task.json fields owned by TaskStore (set_* / clear_* / read_*) --
    @abstractmethod
    def set_cwd(self, task_id: str, cwd: str) -> None:
        """Persist the invocation cwd into task.json."""
        ...

    @abstractmethod
    def set_overrides(
        self,
        task_id: str,
        coder: str | None = None,
        model: str | None = None,
        worker: str | None = None,
        isolation: str | None = None,
        job_gate: str | None = None,
    ) -> None:
        """Persist per-task overrides into task.json."""
        ...

    @abstractmethod
    def set_bd_fields(self, task_id: str, body: dict) -> None:
        """Snapshot title/description/status/priority from a bd body."""
        ...

    @abstractmethod
    def freeze_coder_model(self, task_id: str, coder: str, model: str | None) -> None:
        """Lock the effective coder and model at first spawn (None model writes null)."""
        ...

    @abstractmethod
    def set_ignore(self, task_id: str, ignore_until: str) -> None:
        """Suppress triage for a blocked task until a time or "forever"."""
        ...

    @abstractmethod
    def clear_ignore(self, task_id: str) -> None:
        """Lift a triage ignore so the next tick asks again."""
        ...

    @abstractmethod
    def set_isolation_info(
        self, task_id: str, repo_root: str, base_ref: str, worktree_path: str
    ) -> None:
        """Persist git isolation info into task.json."""
        ...

    @abstractmethod
    def read_isolation_info(self, task_id: str) -> dict | None:
        """Return git isolation info, or None when not isolated."""
        ...

    @abstractmethod
    def clear_isolation_info(self, task_id: str) -> None:
        """Drop git isolation info after merge/cleanup."""
        ...


class BeadsQueue(Queue):
    """Queue backed by the `bd` CLI plus the on-disk TaskStore."""

    def __init__(
        self,
        repo_root: Path,
        *,
        client: BdClient | None = None,
        store: TaskStore | None = None,
    ) -> None:
        self.repo_root = repo_root
        self._client = client or BdClient(repo_root)
        self._store = store or TaskStore(repo_root)

    def claim(self, task_id: str, claimer_id: str) -> Task:
        self._client.run(["update", task_id, "--claim"], actor=claimer_id)
        body = self._client.run_json(["show", task_id])
        if isinstance(body, list):
            body = body[0] if body else None
        if not isinstance(body, dict):
            raise BdError(f"bd show {task_id}: no issue returned")
        self._store.write(task_id, self._store.snapshot(body, status="in_progress"))
        return build_task(body, self._store.read(task_id), status_override="in_progress")

    def claim_next(
        self, claimer_id: str, *, can_claim: Callable[[str | None], bool] | None = None
    ) -> Task | None:
        # `bd ready` only lists issues whose dependencies all closed. An epic
        # with a `blocked` child never becomes ready, so ready epics whose
        # children are all terminal are appended as extra candidates. Both
        # sources flow through the single claim(id) below.
        for rows in (self._ready_rows(), self._ready_epic_rows()):
            for cand in order_ready(rows):
                task_id = cand.get("id") if isinstance(cand, dict) else None
                if not task_id:
                    continue
                if self._store.retry_after_active(task_id):
                    continue
                if can_claim is not None and not can_claim(self._store.coder_of(task_id, cand)):
                    continue
                try:
                    return self.claim(task_id, claimer_id)
                except BdError:
                    continue
        return None

    def _ready_rows(self) -> list[dict]:
        """Raw `bd ready` rows (unlimited; we sort and filter above)."""
        try:
            data = self._client.run_json(["ready", "--limit", "0"])
        except BdError:
            return []
        items = data.get("data", data) if isinstance(data, dict) else (data or [])
        return items if isinstance(items, list) else []

    def _ready_epic_rows(self) -> list[dict]:
        """Open epics whose children are all closed/blocked (observer input)."""
        try:
            data = self._client.run_json(["list", "--status", "open", "--limit", "0"])
        except BdError:
            return []
        items = data.get("data", data) if isinstance(data, dict) else (data or [])
        if not isinstance(items, list):
            return []
        rows = []
        for cand in items:
            if not isinstance(cand, dict) or cand.get("issue_type") != "epic":
                continue
            epic_id = cand.get("id")
            if not epic_id:
                continue
            try:
                children = self.list_children(epic_id)
            except BdError:
                continue
            if not children or not children_terminal(children):
                continue
            rows.append(cand)
        return rows

    def list_children(self, epic_id: str) -> list[BeadSummary]:
        """The epic's child beads (its dependencies) with their statuses."""
        raw = children_of(epic_id, self.repo_root, timeout=self._client.timeout)
        return [
            BeadSummary(id=str(c.get("id")), status=str(c.get("status") or ""))
            for c in raw
            if isinstance(c, dict) and c.get("id")
        ]

    def create_child(self, epic_id: str, spec: dict) -> Task:
        """Open one child bead under *epic_id* (observer follow-up or job task).

        The epic gains a dependency on each child, so beads keeps it asleep
        until they close. A failed `dep add` raises BdError so the caller
        sees the orphan instead of silently leaving one behind.
        """
        epic = self.get(epic_id)
        title = spec.get("title") or epic.title
        body = spec.get("body") or ""
        child = self.create_task(
            title,
            description=body,
            depends_on=spec.get("depends_on") or [],
            cwd=spec.get("cwd") or epic.cwd,
            coder=spec.get("coder") or epic.coder,
            model=spec.get("model") or epic.model,
        )
        if spec.get("priority") is not None:
            with contextlib.suppress(BdError, TypeError, ValueError):
                self._client.run(["update", child.id, "--priority", str(int(spec["priority"]))])
        self._client.run(["dep", "add", epic_id, child.id])
        return child

    def release(self, task_id: str, reason: str = "", wait_sec: int = 0) -> None:
        """Return a task to open, with an optional retry delay."""
        self._client.run(["update", task_id, "--status", "open", "--assignee", ""])
        if reason:
            self._client.run(["comment", task_id, reason])
        self._store.mark_released(task_id, wait_sec)

    def set_blocked(self, task_id: str, reason: str) -> None:
        """Mark a task blocked with a reason."""
        self._client.run(["update", task_id, "--status", "blocked", "--notes", reason])
        self._store.mark_blocked(task_id, reason)

    def close(self, task_id: str, reason: str = "completed") -> None:
        """Close a task with a reason."""
        self._client.run(["close", task_id, "--reason", reason])
        self._store.mark_closed(task_id)

    def delete(self, task_id: str) -> None:
        """Delete a task and drop its task dir."""
        self._client.run(["delete", task_id, "--force"])
        task_dir = self._store.task_dir(task_id)
        if task_dir.exists():
            shutil.rmtree(task_dir)

    def comment(self, task_id: str, body: str) -> None:
        """Append a comment to a task."""
        self._client.run(["comment", task_id, body])

    def get(self, task_id: str) -> Task:
        """Show one task by id."""
        body = self._client.run_json(["show", task_id])
        if body is None:
            raise BdError(f"bd show {task_id}: empty response")
        if isinstance(body, list):
            if not body:
                raise BdError(f"bd show {task_id}: no issue returned")
            body = body[0]
        return build_task(body, self._store.read(task_id))

    def list_ready(self, limit: int = 50) -> list[Task]:
        """List open tasks whose dependencies are all closed."""
        rows = self._rows("ready", limit)
        return [build_task(item, self._store.read(item["id"])) for item in rows]

    def list_in_progress(self, limit: int = 50) -> list[Task]:
        """List claimed tasks."""
        rows = self._rows("list:status=in_progress", limit)
        return [
            build_task(item, self._store.read(item["id"]), status_override="in_progress")
            for item in rows
        ]

    def list_blocked(self, limit: int = 100) -> list[Task]:
        """List blocked tasks (fleet-blocked and human-blocked alike)."""
        rows = self._rows("list:status=blocked", limit)
        return [
            build_task(item, self._store.read(item["id"]), status_override="blocked")
            for item in rows
        ]

    def list_ignored(self, limit: int = 100) -> list[tuple[Task, str]]:
        """Blocked tasks whose task.json ignore_until is still active."""
        return self._store.select_ignored(self.list_blocked(limit=limit))

    def list_by_metadata(self, field: str, value: str) -> list[Task]:
        """Tasks whose bd metadata `field` equals `value` (one workflow run)."""
        data = self._client.run_json(
            ["list", "--all", "--limit", "0", "--metadata-field", f"{field}={value}"]
        )
        items = data if isinstance(data, list) else []
        return [
            build_task(item, self._store.read(item["id"]))
            for item in items
            if isinstance(item, dict) and item.get("id")
        ]

    def _rows(self, query: str, limit: int) -> list[dict]:
        """Run one list-shaped `bd` query and return its dict rows."""
        if query == "ready":
            argv = ["ready", "--limit", str(limit)]
        else:
            name, _, status = query.partition(":status=")
            argv = [name, "--status", status, "--limit", str(limit)]
        data = self._client.run_json(argv)
        items: list = data.get("data", data) if isinstance(data, dict) else (data or [])
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict) and item.get("id")]

    def create_task(  # noqa: PLR0913, PLR0917  # ADR 0006 bead 4
        self,
        title: str,
        description: str | None = None,
        depends_on: list[str] | None = None,
        labels: list[str] | None = None,
        cwd: str | None = None,
        coder: str | None = None,
        model: str | None = None,
        worker: str | None = None,
        extra_args: str | None = None,
    ) -> Task:
        """Open a new task and snapshot it to task.json.

        Dependencies ride on `bd create --deps` itself, so the bead is
        born with its edges: the supervisor can never claim it in
        between a create and a later `dep add`.
        """
        args = ["create", "--title", title, "--json"]
        if description:
            args += ["--description", description]
        if depends_on:
            args += ["--deps", ",".join(depends_on)]
        if extra_args:
            args += shlex.split(extra_args)
        body = self._client.run_json(args)
        task_id = body.get("id", "") if isinstance(body, dict) else ""
        if not task_id:
            raise BdError("bd create returned no task id")
        self._store.write(
            task_id,
            self._store.snapshot(
                body or {"id": task_id},
                cwd=cwd,
                coder=coder,
                model=model,
                worker=worker,
                depends_on=depends_on,
            ),
        )
        return self.get(task_id)

    def set_cwd(self, task_id: str, cwd: str) -> None:
        """Persist the invocation cwd into task.json."""
        self._store.set_cwd(task_id, cwd)

    def set_overrides(
        self,
        task_id: str,
        coder: str | None = None,
        model: str | None = None,
        worker: str | None = None,
        isolation: str | None = None,
        job_gate: str | None = None,
    ) -> None:
        """Persist per-task overrides into task.json."""
        self._store.set_overrides(
            task_id, coder=coder, model=model, worker=worker, isolation=isolation, job_gate=job_gate
        )

    def set_bd_fields(self, task_id: str, body: dict) -> None:
        """Snapshot title/description/status/priority from a bd body."""
        self._store.set_bd_fields(task_id, body)

    def freeze_coder_model(self, task_id: str, coder: str, model: str | None) -> None:
        """Lock the effective coder and model at first spawn."""
        self._store.freeze_coder_model(task_id, coder, model)

    def set_ignore(self, task_id: str, ignore_until: str) -> None:
        """Suppress triage for a blocked task until a time or "forever"."""
        self._store.set_ignore(task_id, ignore_until)

    def clear_ignore(self, task_id: str) -> None:
        """Lift a triage ignore so the next tick asks again."""
        self._store.clear_ignore(task_id)

    def set_isolation_info(
        self, task_id: str, repo_root: str, base_ref: str, worktree_path: str
    ) -> None:
        """Persist git isolation info into task.json."""
        self._store.set_isolation_info(task_id, repo_root, base_ref, worktree_path)

    def read_isolation_info(self, task_id: str) -> dict | None:
        """Return git isolation info, or None when not isolated."""
        return self._store.read_isolation_info(task_id)

    def clear_isolation_info(self, task_id: str) -> None:
        """Drop git isolation info after merge/cleanup."""
        self._store.clear_isolation_info(task_id)
