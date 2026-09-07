from __future__ import annotations

import asyncio
import json
import os
import subprocess
import signal
from datetime import datetime, timezone
from pathlib import Path

import structlog

from fleet.coders.base import Coder
from fleet.coders import get_coder
from fleet.config import load, reload_if_changed
from fleet.concurrency import cap_for_coder, running_by_coder
from fleet.failures import (
    increment_failure,
    increment_noclose,
    needs_validation,
    reset_failure,
    reset_noclose,
    set_needs_validation,
    clear_needs_validation,
)
from fleet.queue import Queue
from fleet.rate_gauge import RateGauge
from fleet.runner import TaskRunner
from fleet.schemas import (
    CLAIM_POLL_INTERVAL_SEC,
    CONFIG_POLL_INTERVAL_SEC,
    RATE_LIMIT_DEFAULT_SLEEP_SEC,
    RETRY_LIMIT,
    NOCLOSE_LIMIT,
    SHUTDOWN_GRACE_SEC,
    STATUS_LOG_INTERVAL_SEC,
    LOG_ROOT,
    RuntimeConfig,
    Task,
    TaskOutcome,
    TaskOutcomeRecord,
)
from fleet.supervisor_spawn import SpawnController, SpawnDecision
from fleet.serve.stats import task_runtime_stats
from fleet import worktree
from fleet.worktree import remove_worktree, worktree_path


class Supervisor:
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
        self._runners: dict[str, TaskRunner] = {}

        self.rate_gauge = RateGauge(log=log)
        self.spawn_controller = SpawnController(log=log)

        self._paused_until: datetime | None = None
        self._shutting_down: bool = False
        self._done: asyncio.Event | None = None
        self._stall_warned: set[str] = set()

    async def run(self) -> int:
        self._done = asyncio.Event()
        loop = asyncio.get_running_loop()
        self._install_signal_handlers(loop)

        self._sweep_orphan_worktrees()
        self._reconcile_orphans()

        bg = [
            asyncio.create_task(self._claim_and_spawn_loop(), name="claim_and_spawn"),
            asyncio.create_task(self._reap_loop(), name="reap"),
            asyncio.create_task(self._config_poll_loop(), name="config_poll"),
            asyncio.create_task(self._status_log_loop(), name="status_log"),
            asyncio.create_task(self._kill_poll_loop(), name="kill_poll"),
        ]

        await self._done.wait()

        for t in bg:
            t.cancel()
        await asyncio.gather(*bg, return_exceptions=True)

        return 0

    def _sweep_orphan_worktrees(self) -> None:
        """Remove worktrees with no corresponding active task (startup sweep)."""
        worktrees_dir = worktree_path("")
        if not worktrees_dir.is_dir():
            return

        fleet_home = worktrees_dir.parent

        for worktree_dir in worktrees_dir.iterdir():
            if not worktree_dir.is_dir():
                continue

            task_id = worktree_dir.name

            if task_id in self.in_flight:
                continue

            task_dir = fleet_home / "tasks" / task_id
            if needs_validation(task_dir):
                continue

            self._log.info("worktree.sweep.removed", task_id=task_id)
            remove_worktree(self._project_root, task_id)

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

    async def _claim_and_spawn_loop(self) -> None:
        while not self._shutting_down:
            await asyncio.sleep(CLAIM_POLL_INTERVAL_SEC)
            if self._shutting_down:
                break

            now = datetime.now(tz=timezone.utc)
            if self._paused_until is not None:
                if now < self._paused_until:
                    continue
                self._paused_until = None

            if (self._project_root / ".pause").exists():
                continue

            decision = self.spawn_controller.decide(
                in_flight=len(self.in_flight),
                max_concurrent=self.config.max_concurrent,
                enforce_full_cap=False,
            )

            if decision == SpawnDecision.SPAWN:

                def _can_claim(coder: str | None) -> bool:
                    running = running_by_coder(
                        self.in_flight_tasks.values(), self.config.coder
                    )
                    effective = coder or self.config.coder
                    cap = cap_for_coder(
                        effective,
                        self.config.max_concurrent,
                        self.config.max_concurrent_overrides,
                    )
                    return running.get(effective, 0) < cap

                # bd is a subprocess; run it in a worker thread
                # so the event loop keeps tailing runner output.
                task = await asyncio.to_thread(
                    self._queue.claim_next, "supervisor", can_claim=_can_claim
                )
                if task is not None:
                    if task.id in self.in_flight:
                        # The task was flipped back to claimable externally
                        # (UI unblock, `bd update`) while our runner is still
                        # alive. Spawning again would orphan the live runner
                        # and put two agents on the same working tree.
                        self._log.warning(
                            "task_already_in_flight",
                            task_id=task.id,
                            in_flight=len(self.in_flight),
                        )
                        continue
                    self._log.info(
                        "task_claimed",
                        task_id=task.id,
                        title=task.title[:80],
                        in_flight=len(self.in_flight) + 1,
                        cap=self.config.max_concurrent,
                        usage_pct=self.rate_gauge.current_pct(),
                    )
                    self._spawn_runner(task)

            await self._run_pending_validations()

    async def _run_pending_validations(self) -> None:
        tasks_root = self._project_root / "tasks"
        if not tasks_root.exists():
            return
        for task_dir in sorted(tasks_root.iterdir()):
            task_id = task_dir.name
            if task_id in self.in_flight:
                continue
            if not needs_validation(task_dir):
                continue
            result = worktree.merge_to_base(
                self._project_root, task_id, base_ref="main"
            )
            if result.ok:
                await asyncio.to_thread(
                    self._queue.close,
                    task_id,
                    reason=f"validated: merged fleet/{task_id} into main",
                )
                self._log.info("task.validated", task_id=task_id)

                # the merge just landed on main; rebuild the UI only if UI files changed
                diff = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self._project_root),
                        "diff",
                        "--name-only",
                        "HEAD~1",
                        "HEAD",
                    ],
                    capture_output=True,
                    text=True,
                )
                if any(
                    line.startswith("src/fleet/ui/")
                    for line in diff.stdout.splitlines()
                ):
                    proc = await asyncio.create_subprocess_exec(
                        "make",
                        "ui-build",
                        cwd=str(self._project_root),
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    rc = await proc.wait()
                    if rc == 0:
                        self._log.info("ui.rebuilt", task_id=task_id)
                    else:
                        self._log.error("ui.rebuild_failed", task_id=task_id)
            else:
                reason = (
                    f"merge conflict into main; resolve on branch fleet/{task_id} then close"
                    if result.conflict
                    else f"validation merge failed: {result.message}"
                )
                await asyncio.to_thread(self._queue.set_blocked, task_id, reason)
                self._log.warning(
                    "task.validation_failed",
                    task_id=task_id,
                    conflict=result.conflict,
                )
            worktree.remove_worktree(self._project_root, task_id)
            clear_needs_validation(task_dir)
            (task_dir / ".worktree").unlink(missing_ok=True)
            return  # ONE per tick

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

    def _spawn_runner(self, task: Task) -> None:
        # Purge any stale .kill sentinel from a previous run before registering
        # the runner — the kill_poll_loop only checks self._runners, so clearing
        # the file here (before the runner is added) is race-free.
        (self._project_root / "tasks" / task.id / ".kill").unlink(missing_ok=True)

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
        runner = TaskRunner(
            task=task,
            coder=coder,
            queue=self._queue,
            config=self.config,
            rate_gauge=self.rate_gauge,
            project_root=task_root,
            fleet_home=self._project_root,
            log=self._log.bind(task_id=task.id),
        )
        async_task = asyncio.create_task(runner.run(), name=f"runner:{task.id}")
        self.in_flight[task.id] = async_task
        self.in_flight_tasks[task.id] = task
        self._runners[task.id] = runner

    async def _reap_loop(self) -> None:
        while not self._shutting_down or self.in_flight:
            if not self.in_flight:
                await asyncio.sleep(0.1)
                continue

            try:
                done, _ = await asyncio.wait(
                    list(self.in_flight.values()),
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=1.0,
                )
            except (asyncio.CancelledError, ValueError):
                break

            for async_task in done:
                task_id = next(
                    (tid for tid, t in self.in_flight.items() if t is async_task),
                    None,
                )
                if task_id is None:
                    continue

                bead_task = self.in_flight_tasks.pop(task_id)
                self.in_flight.pop(task_id)
                self._runners.pop(task_id, None)
                self._stall_warned.discard(task_id)

                try:
                    outcome: TaskOutcomeRecord = async_task.result()
                except Exception as exc:
                    self._log.error(
                        "runner_unexpected_exception",
                        task_id=task_id,
                        error=str(exc),
                    )
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.FAILURE,
                        reason=f"unexpected exception: {exc}",
                    )

                self._handle_outcome(bead_task, outcome)

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

    async def _status_log_loop(self) -> None:
        """Periodically emit a heartbeat with in-flight count and rate-limit usage."""
        while not self._shutting_down:
            await asyncio.sleep(STATUS_LOG_INTERVAL_SEC)
            if self._shutting_down:
                break
            self._log_status_snapshot()

    async def _kill_poll_loop(self) -> None:
        """Poll for .kill sentinel files and terminate the matching runner."""
        while not self._shutting_down:
            await asyncio.sleep(1.0)
            if self._shutting_down:
                break
            for task_id, runner in list(self._runners.items()):
                kill_file = self._project_root / "tasks" / task_id / ".kill"
                if kill_file.exists():
                    kill_file.unlink(missing_ok=True)
                    self._log.info("task_kill_requested", task_id=task_id)
                    await runner.kill()

    def _log_status_snapshot(self) -> None:
        self._log.info("supervisor_status", **self._fleet_log_context())
        if self.config.stall_warning_minutes <= 0:
            return
        now = datetime.now(tz=timezone.utc).timestamp()
        for task_id in list(self.in_flight):
            events_path = self._project_root / "tasks" / task_id / "events.jsonl"
            try:
                mtime = events_path.stat().st_mtime
            except FileNotFoundError:
                continue
            idle = now - mtime
            if idle > self.config.stall_warning_minutes * 60:
                if task_id not in self._stall_warned:
                    self._log.warning(
                        "task_stalled",
                        task_id=task_id,
                        idle_seconds=int(idle),
                        stall_warning_minutes=self.config.stall_warning_minutes,
                    )
                    self._stall_warned.add(task_id)
            else:
                self._stall_warned.discard(task_id)

    def _bead_in_progress(self, task_id: str) -> bool:
        try:
            return self._queue.get(task_id).status == "in_progress"
        except Exception:
            return False

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

    def _handle_outcome(self, task: Task, outcome: TaskOutcomeRecord) -> None:
        fleet_ctx = self._fleet_log_context()
        match outcome.outcome:
            case TaskOutcome.SUCCESS:
                if self._bead_in_progress(task.id):
                    task_dir = self._task_dir_for(task)
                    wt_marker = task_dir / ".worktree"
                    if wt_marker.exists():
                        # ISOLATED task: implementer is not expected to close.
                        wt_path = Path(wt_marker.read_text().strip())
                        if worktree.is_committed_clean(wt_path, base_ref="main"):
                            set_needs_validation(task_dir)
                            self._log.info("task.needs_validation", task_id=task.id)
                            return
                        else:
                            count = increment_noclose(task_dir)
                            reason = f"isolated task exited without a clean commit ({count}x)"
                            if count >= NOCLOSE_LIMIT:
                                self._queue.set_blocked(task.id, reason)
                            else:
                                self._queue.release(task.id)
                            return
                    # Non-isolated: fall through to existing no-close logic
                    count = increment_noclose(task_dir)
                    if count >= NOCLOSE_LIMIT:
                        reason = (
                            f"no-close limit exhausted ({count}/{NOCLOSE_LIMIT}); "
                            "needs human review"
                        )
                        self._queue.set_blocked(task.id, reason)
                        self._queue.comment(
                            task.id,
                            f"[fleet] no-close limit exhausted: {count} successful exits "
                            f"without `fleet bd close`. Blocked for human review.",
                        )
                        self._log.warning(
                            "task_noclose_exhausted", task_id=task.id, count=count, limit=NOCLOSE_LIMIT
                        )
                        return
                    reason = f"re-queueing (success without close; #{count}/{NOCLOSE_LIMIT})"
                    self._queue.release(task.id, reason=reason)
                    self._queue.comment(
                        task.id,
                        f"[fleet] success #{count}/{NOCLOSE_LIMIT}: rc=0 with the bead still open. "
                        f"At {NOCLOSE_LIMIT} the task will be blocked for human review.",
                    )
                    self._log.warning(
                        "task_success_noclose",
                        task_id=task.id,
                        count=count,
                        limit=NOCLOSE_LIMIT,
                    )
                    return
                else:
                    reset_noclose(self._task_dir_for(task))
                    self._log.info(
                        "task_completed_success", task_id=task.id, **fleet_ctx
                    )

            case TaskOutcome.CONTEXT_PRESSURE:
                if not self._bead_in_progress(task.id):
                    reset_failure(self._task_dir_for(task))
                    self._log.info(
                        "task_already_closed_on_exit",
                        task_id=task.id,
                        outcome="CONTEXT_PRESSURE",
                        **fleet_ctx,
                    )
                    return
                self._queue.release(
                    task.id, reason="context_pressure; resume on next claim"
                )
                self._log.info(
                    "task_context_pressure_release", task_id=task.id, **fleet_ctx
                )

            case TaskOutcome.RATE_LIMIT:
                now_ts = datetime.now(tz=timezone.utc).timestamp()
                resets_at = outcome.resets_at
                sleep_until_ts = max(
                    float(resets_at) if resets_at is not None else 0.0,
                    now_ts + RATE_LIMIT_DEFAULT_SLEEP_SEC,
                )
                sleep_until = datetime.fromtimestamp(sleep_until_ts, tz=timezone.utc)
                if self._paused_until is None or sleep_until > self._paused_until:
                    self._paused_until = sleep_until
                rate_ctx = {k: v for k, v in fleet_ctx.items() if k != "paused_until"}
                self._log.warning(
                    "task_rate_limit_release",
                    task_id=task.id,
                    resets_at=resets_at,
                    paused_until=str(self._paused_until),
                    **rate_ctx,
                )

            case TaskOutcome.BLOCKED_BY_AGENT:
                self._log.info("task_blocked_by_agent", task_id=task.id, **fleet_ctx)

            case TaskOutcome.KILLED:
                if not self._bead_in_progress(task.id):
                    reset_failure(self._task_dir_for(task))
                    self._log.info(
                        "task_already_closed_on_exit",
                        task_id=task.id,
                        outcome="KILLED",
                        **fleet_ctx,
                    )
                    return
                self._queue.set_blocked(
                    task.id,
                    reason="manually interrupted",
                )
                self._queue.comment(
                    task.id,
                    "[fleet] task was manually interrupted.",
                )
                self._log.info("task_killed", task_id=task.id, **fleet_ctx)

            case TaskOutcome.FAILURE:
                if not self._bead_in_progress(task.id):
                    reset_failure(self._task_dir_for(task))
                    self._log.info(
                        "task_already_closed_on_exit",
                        task_id=task.id,
                        outcome="FAILURE",
                        **fleet_ctx,
                    )
                    return
                new_count = increment_failure(self._task_dir_for(task))
                if new_count >= RETRY_LIMIT:
                    self._queue.set_blocked(
                        task.id,
                        reason=(
                            f"retry limit ({RETRY_LIMIT}) exhausted; "
                            f"last failure: {outcome.reason}"
                        ),
                    )
                    self._queue.comment(
                        task.id,
                        (
                            f"[fleet] retry limit exhausted after {new_count} failures. "
                            f"Last exit code={outcome.exit_code}. "
                            f"stderr_tail: {outcome.stderr_tail}"
                        ),
                    )
                    self._log.error(
                        "task_retry_exhausted",
                        task_id=task.id,
                        failures=new_count,
                        retry_limit=RETRY_LIMIT,
                        **fleet_ctx,
                    )
                else:
                    self._queue.release(
                        task.id,
                        reason=f"subprocess failure rc={outcome.exit_code}; will retry",
                    )
                    self._queue.comment(
                        task.id,
                        (
                            f"[fleet] failure {new_count} (rc={outcome.exit_code}). "
                            f"Releasing for retry."
                        ),
                    )
                    self._log.warning(
                        "task_failure_release",
                        task_id=task.id,
                        failures=new_count,
                        retry_limit=RETRY_LIMIT,
                        **fleet_ctx,
                    )

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

    def _resolve_log_root(self) -> Path:
        log_root = Path(LOG_ROOT)
        if not log_root.is_absolute():
            log_root = self._project_root / log_root
        return log_root

    def _task_dir_for(self, task: Task) -> Path:
        return self._project_root / "tasks" / task.id

    def _is_fleet_repo(self, path: Path) -> bool:
        return path.resolve() == self._project_root.resolve()
