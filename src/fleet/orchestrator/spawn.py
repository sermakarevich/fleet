from __future__ import annotations

import asyncio
from pathlib import Path

from fleet.coders import get_coder
from fleet.core.task import Task
from fleet.state import attempts
from fleet.state.paths import task_dir as _task_dir
from fleet.workers import select_worker
from fleet.workers.base import StepContext, WorkerRun

from . import worktree


class SpawnMixin:
    def _resolve_coder(self, task: Task):
        """Pick (coder, coder_name, model) for a task.

        If the Supervisor was constructed with a pinned `coder=` instance (used
        in unit tests), reuse it as-is. Otherwise build a fresh coder using
        task.coder / task.model, falling back to config defaults.
        """
        if self._coder_pin is not None:
            return (
                self._coder_pin,
                self._coder_pin.name,
                getattr(self._coder_pin, "model", None),
            )
        coder_name = task.coder or self.config.coder
        model = task.model or self.config.model
        coder_cls = get_coder(coder_name)
        kwargs: dict = {}
        if coder_name in ("opencode", "pi"):
            kwargs["ollama_url"] = self.config.opencode_ollama_url
            kwargs["context_limit"] = self.config.opencode_context_limit
            kwargs["default_model"] = self.config.opencode_default_model
            kwargs["bedrock_region"] = self.config.opencode_bedrock_region
            kwargs["bedrock_profile"] = self.config.opencode_bedrock_profile
            kwargs["bedrock_context_limit"] = self.config.opencode_bedrock_context_limit
        return coder_cls(model=model, **kwargs), coder_name, model

    def _spawn_worker(self, task: Task) -> None:
        # Purge any stale .kill sentinel from a previous run before registering
        # the runner — the kill_poll_loop only checks self._runners, so clearing
        # the file here (before the runner is added) is race-free.
        (_task_dir(self._project_root, task.id) / ".kill").unlink(missing_ok=True)

        base_cwd = Path(task.cwd) if task.cwd else self._project_root
        use_worktree = worktree.worktree_isolation_enabled() and self._is_fleet_repo(
            base_cwd
        )
        if use_worktree:
            task_root = worktree.create_worktree(
                self._project_root, task.id, base_ref="main"
            )
            task_dir = self._task_dir_for(task)
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / ".worktree").write_text(str(task_root))
        else:
            task_root = base_cwd
        if task.cwd is None:
            # Coding agents almost never mean to run in fleet's home; a
            # missing cwd usually means task.json lost the field.
            self._log.warning(
                "task_cwd_missing",
                task_id=task.id,
                fallback_root=str(task_root),
            )
        try:
            coder, coder_name, model = self._resolve_coder(task)
        except ValueError as exc:
            # Effective coder name is unknown — typo in config.coder, typo in
            # task.coder override, or runtime.toml hand-edited to an invalid
            # value mid-run. claim_next has already flipped the task to
            # in_progress, so block it explicitly to stop the supervisor
            # from re-claiming it on every poll.
            self._log.error(
                "task_coder_invalid",
                task_id=task.id,
                task_coder=task.coder,
                default_coder=self.config.coder,
                error=str(exc),
            )
            self._queue.set_blocked(task.id, reason=f"invalid coder: {exc}")
            self._queue.comment(
                task.id,
                f"[fleet] {exc}. Fix `coder` in runtime.toml or set --coder on this task.",
            )
            return
        if self._coder_pin is None:
            # Freeze the resolved coder/model into task.json so that config
            # changes after first spawn don't affect retries or reclaims.
            self._queue.freeze_coder_model(task.id, coder_name, model)
        self._log.info(
            "task_coder_selected",
            task_id=task.id,
            coder=coder_name,
            model=model,
        )

        task_dir = self._task_dir_for(task)
        attempt_n = attempts.record_start(task_dir, coder=coder_name, model=model, worker=None)
        attempt_dir = attempts.attempt_dir(task_dir, attempt_n)
        attempt_dir.mkdir(parents=True, exist_ok=True)

        ctx = StepContext(
            task=task,
            task_dir=task_dir,
            project_root=task_root,
            fleet_home=self._project_root,
            coder=coder,
            config=self.config,
            rate_gauge=self.rate_gauge,
            log=self._log.bind(task_id=task.id),
            attempt_dir=attempt_dir,
            attempt_n=attempt_n,
        )
        try:
            worker = select_worker(task, ctx)
        except ValueError as exc:
            # Unknown worker family — a typo in fleet_worker metadata or an
            # unroutable bead type. claim_next has already flipped the task
            # to in_progress, so block it explicitly so the supervisor
            # doesn't re-claim it on every poll.
            self._log.error(
                "task_worker_invalid",
                task_id=task.id,
                task_worker=task.worker,
                task_type=task.type,
                error=str(exc),
            )
            self._queue.set_blocked(task.id, reason=f"invalid worker: {exc}")
            self._queue.comment(
                task.id,
                f"[fleet] {exc}. Fix `fleet_worker` metadata or the bead type.",
            )
            return

        run = WorkerRun(worker, ctx)
        async_task = asyncio.create_task(run.run(), name=f"worker:{task.id}")
        self.in_flight[task.id] = async_task
        self.in_flight_tasks[task.id] = task
        self._runners[task.id] = run
