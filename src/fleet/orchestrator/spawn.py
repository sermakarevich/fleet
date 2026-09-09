"""Spawn workers for claimed tasks: resolve coder, isolate, start the run.

Plain functions, not a class. ``Claim`` calls :func:`spawn_worker` with the
shared state and registers the returned record itself; terminal setup
errors (unknown coder, bad cwd) are blocked inside and reported as None so
the caller registers nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from fleet.coders import coder_kwargs
from fleet.coders import resolve_coder as build_coder
from fleet.coders.base import Coder
from fleet.coders.settings import settings_from_env
from fleet.core.effective import effective_coder_model
from fleet.core.retry_policy import Action
from fleet.core.task import Task, TaskOutcome
from fleet.orchestrator.state import RunningWorker
from fleet.state import attempts
from fleet.state.paths import attempt_dir, task_dir
from fleet.workers import select_worker
from fleet.workers.base import StepContext, WorkerRun

from . import worktree

if TYPE_CHECKING:
    from fleet.orchestrator.state import RunningWorker, SupervisorState


def _repo_excluded(repo_root: Path, exclude: str) -> bool:
    """True when *repo_root* matches an entry of the comma-separated *exclude* list."""
    root = repo_root.expanduser().resolve()
    for entry in exclude.split(","):
        raw = entry.strip()
        if raw and Path(raw).expanduser().resolve() == root:
            return True
    return False


def resolve_coder(st: SupervisorState, task: Task) -> tuple[Coder, str, str | None]:
    """Pick (coder, coder_name, model) for a task.

    If the state carries a pinned `coder_pin` instance (used in unit
    tests), reuse it as-is. Otherwise build a fresh coder using
    task.coder / task.model, falling back to config defaults.
    """
    if st.coder_pin is not None:
        pin = st.coder_pin
        spec = getattr(pin, "spec", None)
        name = spec.name if spec is not None else getattr(pin, "name", "")
        return pin, name, getattr(pin, "model", None)
    coder_name, model = effective_coder_model(
        task.coder, task.model, st.config.coder, st.config.model
    )
    kwargs = coder_kwargs(
        coder_name,
        model=model,
        fleet_home=st.fleet_home,
        config=st.config,
        env=settings_from_env(os.environ),
    )
    return build_coder(coder_name, **kwargs), coder_name, model


def block_terminal(st: SupervisorState, task: Task, reason: str) -> None:
    """Record a TERMINAL attempt (no retry possible) and block the bead.

    Terminal setup errors (unknown coder/model, missing cwd, cwd not a
    directory) can never succeed on retry, so the policy blocks at once.
    The attempt is journaled so rounds history shows what happened.
    """
    task_dir = st.task_dir_for(task.id)
    with contextlib.suppress(OSError):
        attempts.record_start(task_dir, coder=task.coder, model=task.model, worker=None)
    with contextlib.suppress(OSError):
        attempts.record_end(
            task_dir,
            outcome=TaskOutcome.TERMINAL,
            exit_code=None,
            reason=reason,
            action=Action.BLOCK,
        )
    st.log.error("task_terminal", task_id=task.id, reason=reason)
    st.queue.set_blocked(task.id, reason)
    st.queue.comment(task.id, f"[fleet] {reason}.")


def should_isolate(st: SupervisorState, task: Task, repo_root: Path | None) -> bool:
    """True when a git task should run in an isolated worktree.

    Non-git tasks (repo_root None) never isolate. A task without a cwd
    never isolates either: it only fell back to fleet's fleet_home, and a
    worktree of fleet's fleet_home is never the repo the task works on.
    Isolation also stays off when the global `isolation` config is
    "none", when the repo root is listed in `isolation_exclude` (a
    comma-separated list of repo paths, for repos that auto-commit and
    make a worktree pointless), or the bead opted out via
    `fleet_isolation: "none"` metadata.
    """
    if repo_root is None or task.cwd is None:
        return False
    if getattr(st.config, "isolation", "worktree") == "none":
        return False
    if _repo_excluded(repo_root, getattr(st.config, "isolation_exclude", "")):
        return False
    return (task.isolation or "") != "none"


def _purge_stale_kill_marker(st: SupervisorState, task: Task) -> None:
    """Delete a leftover .kill sentinel before the runner is registered."""
    (task_dir(st.fleet_home, task.id) / ".kill").unlink(missing_ok=True)


class Workdir(NamedTuple):
    """Where a worker runs: the task cwd plus its repo root (None outside git)."""

    base_cwd: Path
    repo_root: Path | None


def resolve_workdir(st: SupervisorState, task: Task) -> Workdir | None:
    """Resolve the task cwd and its repo root, or block when terminal."""
    base_cwd = Path(task.cwd) if task.cwd else st.fleet_home
    if task.cwd is not None and not Path(task.cwd).is_dir():
        block_terminal(st, task, f"terminal: cwd is not a directory: {task.cwd}")
        return None
    if task.cwd is None:
        st.log.warning("task_cwd_missing", task_id=task.id, fallback_root=str(base_cwd))
    return Workdir(base_cwd=base_cwd, repo_root=worktree.detect_repo_root(base_cwd))


def _resolve_coder_or_block(
    st: SupervisorState, task: Task
) -> tuple[Coder, str, str | None] | None:
    """Resolve the coder, blocking the task when the name is unknown."""
    try:
        return resolve_coder(st, task)
    except ValueError as exc:
        block_terminal(st, task, f"terminal: invalid coder: {exc}")
        return None


def _ensure_isolation(
    st: SupervisorState, task: Task, base_cwd: Path, repo_root: Path | None
) -> Path | None:
    """Create the worktree for git tasks; return the dir the worker runs in."""
    if not should_isolate(st, task, repo_root):
        return base_cwd
    assert repo_root is not None
    base_ref = worktree.resolve_base_ref(repo_root)
    try:
        task_root = worktree.create_worktree(
            repo_root, task.id, base_ref=base_ref, fleet_home=st.fleet_home
        )
    except Exception as exc:
        block_terminal(st, task, f"terminal: worktree setup failed: {exc}")
        return None
    try:
        st.queue.set_isolation_info(task.id, str(repo_root), base_ref, str(task_root))
    except Exception as exc:
        st.log.warning("isolation_info_write_failed", task_id=task.id, error=str(exc))
    return task_root


def _build_step_context(
    st: SupervisorState,
    task: Task,
    coder: Coder,
    coder_name: str,
    model: str | None,
    task_root: Path,
) -> StepContext:
    """Journal the attempt start and build the worker step context."""
    task_dir = st.task_dir_for(task.id)
    attempt_n = attempts.record_start(task_dir, coder=coder_name, model=model, worker=None)
    adir = attempt_dir(task_dir, attempt_n)
    adir.mkdir(parents=True, exist_ok=True)
    return StepContext(
        task=task,
        task_dir=task_dir,
        workdir=task_root,
        fleet_home=st.fleet_home,
        coder=coder,
        config=st.config,
        rate_gauge=st.rate_gauge,
        log=st.log.bind(task_id=task.id),
        attempt_dir=adir,
        attempt_n=attempt_n,
        question_store=st.question_store,
    )


def _start_worker_run(st: SupervisorState, task: Task, ctx: StepContext) -> RunningWorker | None:
    """Build the worker, start its asyncio task, and return the record."""

    try:
        worker = select_worker(task, ctx)
    except ValueError as exc:
        block_terminal(st, task, f"terminal: invalid worker: {exc}")
        return None
    with contextlib.suppress(OSError):
        attempts.set_worker(st.task_dir_for(task.id), ctx.attempt_n, worker.name)
    run = WorkerRun(worker, ctx)
    future = asyncio.create_task(run.run(), name=f"worker:{task.id}")
    return RunningWorker(
        task=task,
        run=run,
        future=future,
        attempt_n=ctx.attempt_n,
        started_at=datetime.now(tz=UTC),
    )


def spawn_worker(st: SupervisorState, task: Task) -> RunningWorker | None:
    """Start the worker for *task* and return its record (None when terminal).

    Terminal setup errors block the bead and return None so the caller
    registers nothing. The record is NOT added to `st.running`; the
    caller (Claim) owns that write. Unexpected exceptions propagate so
    the caller can release the bead back to the queue.
    """
    _purge_stale_kill_marker(st, task)
    resolved = resolve_workdir(st, task)
    if resolved is None:
        return None
    base_cwd, repo_root = resolved.base_cwd, resolved.repo_root
    coder_triple = _resolve_coder_or_block(st, task)
    if coder_triple is None:
        return None
    coder, coder_name, model = coder_triple
    if st.coder_pin is None:
        st.queue.freeze_coder_model(task.id, coder_name, model)
    st.log.info("task_coder_selected", task_id=task.id, coder=coder_name, model=model)
    task_root = _ensure_isolation(st, task, base_cwd, repo_root)
    if task_root is None:
        return None
    ctx = _build_step_context(st, task, coder, coder_name, model, task_root)
    return _start_worker_run(st, task, ctx)
