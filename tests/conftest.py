"""Shared fixtures and doubles for the whole unit-test suite."""

import json
import shlex
from collections.abc import Callable
from dataclasses import is_dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import structlog

from fleet.beads.client import BdError
from fleet.beads.queue import BeadsQueue, Queue
from fleet.coders.base import Coder
from fleet.core.config import RuntimeConfig
from fleet.core.job_ready import BeadSummary
from fleet.core.task import Task
from fleet.orchestrator import Supervisor, SupervisorState, default_services
from fleet.orchestrator.checks import StartupCheckSpec
from fleet.orchestrator.rate_gauge import RateGauge
from fleet.orchestrator.service import Service
from fleet.orchestrator.state import RunningWorker
from fleet.state.config_file import load


@pytest.fixture
def queue(tmp_path: Path) -> BeadsQueue:
    """A real BeadsQueue rooted at a throwaway repo (needs no `bd` binary to construct)."""
    return BeadsQueue(repo_root=tmp_path)


class FakeQueue(Queue):
    """In-memory Queue for unit tests that need no `bd` binary.

    Implements the full Queue protocol, so new protocol methods fail
    loudly here instead of passing against a stale duck-typed fake.
    """

    def __init__(self, tasks: list[Task] | None = None) -> None:
        self._tasks: dict[str, Task] = {t.id: t for t in (tasks or [])}
        self.released: list[tuple[str, str]] = []
        self.closed: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []
        self.created: list[dict] = []
        self._ignores: dict[str, str] = {}
        self._children: dict[str, list[BeadSummary]] = {}
        self._isolation: dict[str, dict] = {}
        self._meta: dict[str, dict] = {}

    def claim(self, task_id: str, claimer_id: str) -> Task:
        """Move one open task to in_progress and record the claim."""
        _ = claimer_id
        task = self.get(task_id)
        updated = replace(task, status="in_progress")
        self._tasks[task_id] = updated
        return updated

    def claim_next(
        self,
        claimer_id: str,
        *,
        can_claim: Callable[[str | None], bool] | None = None,
    ) -> Task | None:
        """Claim the first open task the predicate allows, or None."""
        for tid, task in list(self._tasks.items()):
            if task.status != "open":
                continue
            if can_claim is not None and not can_claim(task.coder):
                continue
            return self.claim(tid, claimer_id)
        return None

    def release(self, task_id: str, reason: str = "", wait_sec: int = 0) -> None:
        """Return a task to open, with an optional retry delay."""
        _ = wait_sec
        self.released.append((task_id, reason))
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], status="open")

    def close(self, task_id: str, reason: str = "completed") -> None:
        """Close a task with a reason."""
        self.closed.append((task_id, reason))
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], status="closed")

    def set_blocked(self, task_id: str, reason: str) -> None:
        """Mark a task blocked with a reason."""
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], status="blocked")

    def comment(self, task_id: str, body: str) -> None:
        """Append a comment to a task."""
        self.comments.append((task_id, body))

    def get(self, task_id: str) -> Task:
        """Show one task by id."""
        if task_id not in self._tasks:
            raise BdError(f"Task {task_id} not found")
        return self._tasks[task_id]

    def list_ready(self, limit: int = 50) -> list[Task]:
        """List open tasks whose dependencies are all closed."""
        return [t for t in self._tasks.values() if t.status == "open"][:limit]

    def list_in_progress(self, limit: int = 50) -> list[Task]:
        """List claimed tasks."""
        return [t for t in self._tasks.values() if t.status == "in_progress"][:limit]

    def list_blocked(self, limit: int = 100) -> list[Task]:
        """List blocked tasks."""
        return [t for t in self._tasks.values() if t.status == "blocked"][:limit]

    def list_ignored(self, limit: int = 100) -> list[tuple[Task, str]]:
        """List blocked tasks whose triage ignore is still active."""
        return [
            (self._tasks[tid], until) for tid, until in self._ignores.items() if tid in self._tasks
        ][:limit]

    def list_by_metadata(self, field: str, value: str) -> list[Task]:
        """Tasks whose recorded `--metadata` JSON has `field` equal to `value`."""
        return [
            task
            for task_id, task in self._tasks.items()
            if self._meta.get(task_id, {}).get(field) == value
        ]

    def list_children(self, epic_id: str) -> list[BeadSummary]:
        """List an epic's child beads with their statuses."""
        return list(self._children.get(epic_id, []))

    def delete(self, task_id: str) -> None:
        """Delete a task and drop its task dir."""
        self._tasks.pop(task_id, None)

    def create_task(  # noqa: PLR0913, PLR0917  # mirrors Queue.create_task signature
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
        task_id = f"fake-{len(self._tasks):03d}"
        task = Task(
            id=task_id,
            title=title,
            description=description,
            status="open",
            cwd=cwd,
            coder=coder,
            model=model,
            worker=worker,
        )
        self._tasks[task_id] = task
        self._meta[task_id] = _metadata_of(extra_args)
        self.created.append(
            {
                "id": task_id,
                "title": title,
                "description": description,
                "depends_on": list(depends_on or []),
                "deps_argv": ",".join(depends_on) if depends_on else None,
                "labels": list(labels or []),
                "cwd": cwd,
                "coder": coder,
                "model": model,
                "worker": worker,
                "extra_args": extra_args,
            }
        )
        return task

    def create_child(self, epic_id: str, spec: dict) -> Task:
        """Open one child bead under an epic; raises when the dep link fails."""
        epic = self.get(epic_id)
        child = self.create_task(
            spec.get("title") or epic.title,
            description=spec.get("body") or "",
            cwd=spec.get("cwd") or epic.cwd,
            coder=spec.get("coder") or epic.coder,
            model=spec.get("model") or epic.model,
        )
        self._children.setdefault(epic_id, []).append(BeadSummary(id=child.id, status="open"))
        return child

    def set_cwd(self, task_id: str, cwd: str) -> None:
        """Persist the invocation cwd into task.json."""
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], cwd=cwd)

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
        if task_id in self._tasks:
            task = self._tasks[task_id]
            self._tasks[task_id] = replace(
                task,
                coder=coder if coder is not None else task.coder,
                model=model if model is not None else task.model,
                worker=worker if worker is not None else task.worker,
                isolation=isolation if isolation is not None else task.isolation,
                job_gate=job_gate if job_gate is not None else task.job_gate,
            )

    def set_bd_fields(self, task_id: str, body: dict) -> None:
        """Snapshot title/description/status/priority from a bd body."""
        if task_id in self._tasks:
            task = self._tasks[task_id]
            self._tasks[task_id] = replace(
                task,
                title=body.get("title", task.title),
                description=body.get("description", task.description),
                status=body.get("status", task.status),
            )

    def freeze_coder_model(self, task_id: str, coder: str, model: str) -> None:
        """Lock the effective coder and model at first spawn."""
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], coder=coder, model=model)

    def set_ignore(self, task_id: str, ignore_until: str) -> None:
        """Suppress triage for a blocked task until a time or "forever"."""
        self._ignores[task_id] = ignore_until

    def clear_ignore(self, task_id: str) -> None:
        """Lift a triage ignore so the next tick asks again."""
        self._ignores.pop(task_id, None)

    def set_isolation_info(
        self, task_id: str, repo_root: str, base_ref: str, worktree_path: str
    ) -> None:
        """Persist git isolation info into task.json."""
        self._isolation[task_id] = {
            "repo_root": repo_root,
            "base_ref": base_ref,
            "worktree_path": worktree_path,
        }

    def read_isolation_info(self, task_id: str) -> dict | None:
        """Return git isolation info, or None when not isolated."""
        return self._isolation.get(task_id)

    def clear_isolation_info(self, task_id: str) -> None:
        """Drop git isolation info after merge/cleanup."""
        self._isolation.pop(task_id, None)


def _metadata_of(extra_args: str | None) -> dict:
    """Parse the `--metadata <json>` payload out of a create extra_args string."""
    if not extra_args:
        return {}
    try:
        tokens = shlex.split(extra_args)
        raw = tokens[tokens.index("--metadata") + 1]
        parsed = json.loads(raw)
    except (ValueError, IndexError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def make_supervisor(
    tmp_path: Path,
    *,
    config: RuntimeConfig | None = None,
    queue=None,
    services: list[Service] | None = None,
    checks: list[StartupCheckSpec] | None = None,
    coder: Coder | None = None,
    fleet_home: Path | None = None,
    intervals: dict[str, float] | None = None,
    shutdown_grace_sec: float | None = None,
) -> Supervisor:
    """Build a Supervisor over a minimal runtime.toml for tests.

    `intervals` maps a service name (or class name, case-insensitive) to a
    tick interval, applied to every built service that has `interval_sec`.
    `shutdown_grace_sec` overrides the Supervisor shutdown grace window.
    """
    runtime_toml = tmp_path / "runtime.toml"
    if not runtime_toml.exists():
        runtime_toml.parent.mkdir(parents=True, exist_ok=True)
        runtime_toml.write_text("max_concurrent = 3\n", encoding="utf-8")
    log = structlog.get_logger()
    state = SupervisorState(
        config=config if config is not None else load(runtime_toml),
        fleet_home=fleet_home if fleet_home is not None else tmp_path,
        runtime_toml_path=runtime_toml,
        queue=queue if queue is not None else BeadsQueue(repo_root=tmp_path),
        log=log,
        rate_gauge=RateGauge(log=log),
        coder_factory=(lambda name, model: coder) if coder is not None else None,
    )
    built = services if services is not None else default_services()
    if intervals:
        rebuilt: list[Service] = []
        for svc in built:
            names = {type(svc).__name__.lower(), getattr(svc, "name", "").lower()}
            override = next(
                (value for key, value in intervals.items() if key.lower() in names), None
            )
            adjusted = svc
            if override is not None and hasattr(svc, "interval_sec"):
                if is_dataclass(svc) and not isinstance(svc, type):
                    # Frozen PeriodicService instances are replaced, not mutated.
                    adjusted = replace(svc, interval_sec=override)
                else:
                    svc.interval_sec = override
            rebuilt.append(adjusted)
        built = rebuilt
    return Supervisor(
        state=state,
        services=built,
        checks=checks,
        shutdown_grace_sec=shutdown_grace_sec,
    )


def make_running_worker(
    task_id: str,
    tmp_path: Path | None = None,
    *,
    task: Task | None = None,
    run=None,
    future=None,
    attempt_n: int = 1,
) -> RunningWorker:
    """Build a RunningWorker for tests (fake run/future unless given)."""
    _ = tmp_path  # reserved: callers pass it for symmetry with make_supervisor
    return RunningWorker(
        task=task or Task(id=task_id, title="T", description=None, status="in_progress"),
        run=run if run is not None else MagicMock(),
        future=future if future is not None else MagicMock(),
        attempt_n=attempt_n,
        started_at=datetime.now(tz=UTC),
    )
