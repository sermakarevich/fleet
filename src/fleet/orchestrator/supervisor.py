from __future__ import annotations

import asyncio
import shutil
import signal
from datetime import datetime
from pathlib import Path

import structlog

from fleet.beads.queue import Queue
from fleet.coders.base import Coder
from fleet.core.config import RuntimeConfig, load, reload_if_changed
from fleet.core.limits import (
    CONFIG_POLL_INTERVAL_SEC,
    GC_INTERVAL_SEC,
    SHUTDOWN_GRACE_SEC,
)
from fleet.core.task import Task
from fleet.serve.stats import task_runtime_stats
from fleet.state.archive import find_stale_worktrees, gc_tasks, purge_archive
from fleet.state.paths import task_dir as _task_dir
from fleet.workers.base import WorkerRun

from . import worktree as worktree_mod
from .claim import ClaimMixin
from .leases import LeasesMixin
from .rate_gauge import RateGauge
from .reap import ReapMixin
from .spawn import SpawnMixin
from .stall import StallMixin
from .triage import TriageMixin


def check_ask_human_server(log) -> bool:
    """Warn at startup when the bundled ask_human MCP server is unimportable.

    Every worker prompt names the ``ask_human`` MCP tool, and each coder is
    handed the server explicitly — but if the module itself cannot be
    imported the spawned server would crash on launch. Returns True when the
    server module resolves, False (after logging a warning) otherwise.
    """
    import importlib.util

    if importlib.util.find_spec("fleet.integrations.ask_human.server") is None:
        log.warning(
            "ask_human_unavailable",
            reason="fleet.integrations.ask_human.server cannot be imported; "
            "workers told to call the ask_human MCP tool will fail",
        )
        return False
    return True


class Supervisor(ClaimMixin, SpawnMixin, ReapMixin, StallMixin, LeasesMixin, TriageMixin):
    def __init__(
        self,
        queue: Queue,
        runtime_toml_path: Path,
        project_root: Path,
        log: structlog.BoundLogger,
        coder: Coder | None = None,
    ) -> None:
        # Tests inject a single Coder instance via `coder=`; production callers
        # leave it None so the supervisor resolves (coder, model) per task
        # from task.coder / task.model, falling back to config defaults.
        self._coder_pin = coder
        self._queue = queue
        self._runtime_toml_path = Path(runtime_toml_path)
        self._project_root = Path(project_root)
        self._log = log

        self.config: RuntimeConfig = load(runtime_toml_path)
        self._config_mtime: float | None = None

        self.in_flight: dict[str, asyncio.Task] = {}
        self.in_flight_tasks: dict[str, Task] = {}
        self._runners: dict[str, WorkerRun] = {}
        # Outer work-attempt number per in-flight task, recorded at spawn.
        # Reap closes exactly this attempt: a compaction step journals its own
        # newer kind="compact" row mid-run, so "latest attempt" would otherwise
        # misattribute the outer attempt's end line and artifact snapshot.
        self._attempt_n: dict[str, int] = {}

        self.rate_gauge = RateGauge(log=log)

        self._paused_until: datetime | None = None
        self._shutting_down: bool = False
        self._done: asyncio.Event | None = None
        self._stall_warned: set[str] = set()
        self._stall_killed: set[str] = set()
        # Dedupe keys for recurring lease notices ("event:task_id") and the
        # last periodic reconcile_leases() run (epoch seconds, monotonic).
        self._lease_logged: set[str] = set()
        self._last_lease_reconcile: float | None = None

    async def run(self) -> int:
        self._done = asyncio.Event()
        loop = asyncio.get_running_loop()
        self._install_signal_handlers(loop)

        check_ask_human_server(self._log)
        self._sweep_orphan_worktrees()
        self.reconcile_leases()
        self._run_retention_gc()

        bg = [
            asyncio.create_task(self._claim_and_spawn_loop(), name="claim_and_spawn"),
            asyncio.create_task(self._reap_loop(), name="reap"),
            asyncio.create_task(self._config_poll_loop(), name="config_poll"),
            asyncio.create_task(self._status_log_loop(), name="status_log"),
            asyncio.create_task(self._kill_poll_loop(), name="kill_poll"),
            asyncio.create_task(self._gc_loop(), name="retention_gc"),
        ]

        await self._done.wait()

        for t in bg:
            t.cancel()
        await asyncio.gather(*bg, return_exceptions=True)

        return 0

    async def _gc_loop(self) -> None:
        """Run the retention pass on a daily cadence (startup ran it once)."""
        while not self._shutting_down:
            await asyncio.sleep(GC_INTERVAL_SEC)
            if self._shutting_down:
                break
            try:
                self._run_retention_gc()
            except Exception as exc:  # noqa: BLE001 - gc must not kill the loop
                self._log.warning("retention_gc_failed", error=str(exc))

    def _run_retention_gc(self) -> None:
        """Archive old closed tasks, purge old archives, drop stale worktrees.

        Retention windows come from the live config; 0 disables that step.
        Never raises: per-step handling is guarded so one bad directory
        cannot break the pass.
        """
        home = self._project_root
        try:
            stale = find_stale_worktrees(home, days=self.config.gc_retention_days)
        except Exception as exc:  # noqa: BLE001 - selection failed, skip step
            self._log.warning("retention_worktrees_failed", error=str(exc))
            stale = []
        try:
            gc = gc_tasks(home, days=self.config.gc_retention_days)
            self._log.info(
                "retention_gc_tasks",
                archived=len(gc.archived),
                skipped=gc.skipped,
                bytes_moved=gc.bytes_moved,
            )
        except Exception as exc:  # noqa: BLE001 - one bad step, rest continue
            self._log.warning("retention_gc_tasks_failed", error=str(exc))
        try:
            purged = purge_archive(home, days=self.config.gc_archive_days)
            self._log.info(
                "retention_purge_archive",
                deleted=len(purged.deleted),
                skipped=purged.skipped,
                bytes_freed=purged.bytes_freed,
            )
        except Exception as exc:  # noqa: BLE001 - one bad step, rest continue
            self._log.warning("retention_purge_failed", error=str(exc))
        removed = 0
        for item in stale:
            try:
                worktree_mod.cleanup_worktree(
                    item.repo_root or home,
                    item.task_id,
                    worktree_path_arg=item.path,
                    fleet_home=home,
                )
                if item.path.exists():
                    # Not a git-registered worktree (or its repo is gone):
                    # fall back to a plain recursive delete.
                    shutil.rmtree(item.path, ignore_errors=True)
                removed += 1
            except Exception as exc:  # noqa: BLE001 - one bad dir, rest continue
                self._log.warning(
                    "retention_worktree_failed",
                    task_id=item.task_id,
                    error=str(exc),
                )
        if stale:
            self._log.info("retention_worktrees", found=len(stale), removed=removed)

    async def _config_poll_loop(self) -> None:
        while not self._shutting_down:
            await asyncio.sleep(CONFIG_POLL_INTERVAL_SEC)
            if self._shutting_down:
                break

            try:
                result = reload_if_changed(self._runtime_toml_path, self._config_mtime)
            except OSError:
                continue

            if result is not None:
                new_config, new_mtime = result
                self.config = new_config
                self._config_mtime = new_mtime
                self._log.info("config_reloaded", path=str(self._runtime_toml_path))

    async def _kill_poll_loop(self) -> None:
        """Poll for .kill sentinel files and terminate the matching runner."""
        while not self._shutting_down:
            await asyncio.sleep(1.0)
            if self._shutting_down:
                break
            for task_id, runner in list(self._runners.items()):
                kill_file = _task_dir(self._project_root, task_id) / ".kill"
                if kill_file.exists():
                    kill_file.unlink(missing_ok=True)
                    self._log.info("task_kill_requested", task_id=task_id)
                    await runner.kill()

    def _fleet_log_context(self) -> dict:
        """Snapshot of live fleet stats — in-flight count, rate-limit usage."""
        usage_pct = self.rate_gauge.current_pct()  # may trigger auto-reset
        return {
            "in_flight": len(self.in_flight),
            "cap": self.config.max_concurrent,
            "usage_pct": usage_pct,
            "paused_until": (
                self._paused_until.isoformat()
                if self._paused_until is not None
                else None
            ),
            "rate_limit_resets_at": self.rate_gauge.resets_at,
            "task_ids": sorted(self.in_flight.keys()),
            "context_tokens": {
                tid: (task_runtime_stats(tid).context_tokens or 0)
                for tid in self.in_flight
            },
        }

    def _install_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.ensure_future(self._shutdown()),
            )

    async def _shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._log.info("supervisor_shutdown_initiated")

        grace = float(SHUTDOWN_GRACE_SEC)
        loop = asyncio.get_event_loop()
        deadline = loop.time() + grace

        if self._runners:
            await asyncio.gather(
                *[runner.cancel() for runner in self._runners.values()],
                return_exceptions=True,
            )

        if self.in_flight:
            remaining = deadline - loop.time()
            if remaining > 0:
                _, still_running = await asyncio.wait(
                    list(self.in_flight.values()),
                    timeout=remaining,
                )
            else:
                still_running = set(self.in_flight.values())

            for async_task in still_running:
                task_id = next(
                    (tid for tid, t in self.in_flight.items() if t is async_task),
                    None,
                )
                if task_id is not None:
                    try:
                        self._queue.release(
                            task_id,
                            reason="supervisor shutdown: forced release",
                        )
                    except Exception:
                        pass

        self._log.info("supervisor_shutdown_complete")
        if self._done is not None:
            self._done.set()

    def _task_dir_for(self, task: Task) -> Path:
        return _task_dir(self._project_root, task.id)
