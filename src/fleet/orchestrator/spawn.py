from __future__ import annotations

import asyncio
from pathlib import Path

from fleet.coders import get_coder
from fleet.core.task import Task, TaskOutcome
from fleet.state import attempts
from fleet.state.paths import task_dir as _task_dir
from fleet.workers import select_worker
from fleet.workers.base import StepContext, WorkerRun

from . import worktree


def _repo_excluded(repo_root: Path, exclude: str) -> bool:
    """True when *repo_root* matches an entry of the comma-separated *exclude* list."""
    root = repo_root.expanduser().resolve()
    for raw in exclude.split(","):
        raw = raw.strip()
        if raw and Path(raw).expanduser().resolve() == root:
            return True
    return False


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
            kwargs["default_model"] = self.config.opencode_default_model
            kwargs["bedrock_region"] = self.config.opencode_bedrock_region
            kwargs["bedrock_profile"] = self.config.opencode_bedrock_profile
            # Context windows are per-model now (``context_windows`` +
            # ``core.context_window.resolve_window``); the coder resolves the
            # window for its model itself, so no limit kwargs are passed.
        return coder_cls(model=model, **kwargs), coder_name, model

    def _block_terminal(self, task: Task, reason: str) -> None:
        """Record a TERMINAL attempt (no retry possible) and block the bead.

        Terminal setup errors (unknown coder/model, missing cwd, cwd not a
        directory) can never succeed on retry, so the policy blocks at once.
        The attempt is journaled so rounds history shows what happened.
        """
        task_dir = self._task_dir_for(task)
        try:
            attempts.record_start(task_dir, coder=task.coder, model=task.model, worker=None)
        except OSError:
            pass
        try:
            attempts.record_end(
                task_dir,
                outcome=TaskOutcome.TERMINAL.value,
                exit_code=None,
                reason=reason,
                action="block",
            )
        except OSError:
            pass
        self._log.error("task_terminal", task_id=task.id, reason=reason)
        self._queue.set_blocked(task.id, reason)
        self._queue.comment(task.id, f"[fleet] {reason}.")

    def _should_isolate(self, task: Task, repo_root: Path | None) -> bool:
        """True when a git task should run in an isolated worktree.

        Non-git tasks (repo_root None) never isolate. A task without a cwd
        never isolates either: it only fell back to fleet's home, and a
        worktree of fleet's home is never the repo the task works on.
        Isolation also stays off when the global `isolation` config is
        "none", when the repo root is listed in `isolation_exclude` (a
        comma-separated list of repo paths, for repos that auto-commit and
        make a worktree pointless), or the bead opted out via
        `fleet_isolation: "none"` metadata.
        """
        if repo_root is None or task.cwd is None:
            return False
        if getattr(self.config, "isolation", "worktree") == "none":
            return False
        if _repo_excluded(repo_root, getattr(self.config, "isolation_exclude", "")):
            return False
        if (task.isolation or "") == "none":
            return False
        return True

    def _spawn_worker(self, task: Task) -> None:
        # Purge any stale .kill sentinel from a previous run before registering
        # the runner — the kill_poll_loop only checks self._runners, so clearing
        # the file here (before the runner is added) is race-free.
        (_task_dir(self._project_root, task.id) / ".kill").unlink(missing_ok=True)

        base_cwd = Path(task.cwd) if task.cwd else self._project_root
        if task.cwd is not None and not Path(task.cwd).is_dir():
            self._block_terminal(task, f"terminal: cwd is not a directory: {task.cwd}")
            return
        if task.cwd is None:
            # Coding agents almost never mean to run in fleet's home; a
            # missing cwd usually means task.json lost the field.
            self._log.warning(
                "task_cwd_missing",
                task_id=task.id,
                fallback_root=str(base_cwd),
            )
        try:
            coder, coder_name, model = self._resolve_coder(task)
        except ValueError as exc:
            # Effective coder name is unknown — typo in config.coder, typo in
            # task.coder override, or runtime.toml hand-edited to an invalid
            # value mid-run. claim_next has already flipped the task to
            # in_progress. This is terminal (retry cannot help): journal it
            # and block at once. Resolved FIRST so an invalid coder never
            # leaves a stray worktree behind.
            self._block_terminal(task, f"terminal: invalid coder: {exc}")
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

        # Git-aware isolation: inside a repo -> worktree; outside -> in place.
        repo_root = worktree.detect_repo_root(base_cwd)
        task_root = base_cwd
        if self._should_isolate(task, repo_root):
            assert repo_root is not None
            base_ref = worktree.resolve_base_ref(repo_root)
            try:
                task_root = worktree.create_worktree(
                    repo_root,
                    task.id,
                    base_ref=base_ref,
                    fleet_home=self._project_root,
                )
            except Exception as exc:
                self._block_terminal(task, f"terminal: worktree setup failed: {exc}")
                return
            try:
                self._queue.set_isolation_info(
                    task.id, str(repo_root), base_ref, str(task_root)
                )
            except Exception as exc:
                self._log.warning(
                    "isolation_info_write_failed", task_id=task.id, error=str(exc)
                )

        task_dir = self._task_dir_for(task)
        attempt_n = attempts.record_start(task_dir, coder=coder_name, model=model, worker=None)
        attempt_dir = attempts.attempt_dir(task_dir, attempt_n)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        self._attempt_n[task.id] = attempt_n

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
            # unroutable bead type. Terminal: journal it and block at once.
            self._block_terminal(task, f"terminal: invalid worker: {exc}")
            return
        try:
            attempts.set_worker(task_dir, attempt_n, worker.name)
        except OSError:
            pass

        run = WorkerRun(worker, ctx)
        async_task = asyncio.create_task(run.run(), name=f"worker:{task.id}")
        self.in_flight[task.id] = async_task
        self.in_flight_tasks[task.id] = task
        self._runners[task.id] = run
