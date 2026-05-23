from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone
from pathlib import Path

import structlog

from fleet.coder import Coder
from fleet.coders import get_coder
from fleet.failures import increment_failure
from fleet.config import load, reload_if_changed
from fleet.queue import Queue
from fleet.rate_gauge import RateGauge
from fleet.runner import TaskRunner
from fleet.schemas import RuntimeConfig, Task, TaskOutcome, TaskOutcomeRecord
from fleet.supervisor_spawn import SpawnController, SpawnDecision


class Supervisor:
    def __init__(
        self,
        queue: Queue,
        runtime_toml_path: Path,
        project_root: Path,
        log: structlog.BoundLogger,
        once: bool = False,
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
        self._once = once

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

    async def run(self) -> int:
        self._done = asyncio.Event()
        loop = asyncio.get_running_loop()
        self._install_signal_handlers(loop)

        bg = [
            asyncio.create_task(self._claim_and_spawn_loop(), name="claim_and_spawn"),
            asyncio.create_task(self._reap_loop(), name="reap"),
            asyncio.create_task(self._config_poll_loop(), name="config_poll"),
            asyncio.create_task(self._status_log_loop(), name="status_log"),
        ]

        await self._done.wait()

        for t in bg:
            t.cancel()
        await asyncio.gather(*bg, return_exceptions=True)

        return 0

    async def _claim_and_spawn_loop(self) -> None:
        _once_claimed = False
        while not self._shutting_down:
            await asyncio.sleep(self.config.claim_poll_interval_sec)
            if self._shutting_down:
                break

            if self._once and _once_claimed:
                # once-mode: don't claim more tasks; idle until reap loop triggers shutdown
                continue

            now = datetime.now(tz=timezone.utc)
            if self._paused_until is not None:
                if now < self._paused_until:
                    continue
                self._paused_until = None

            decision = self.spawn_controller.decide(
                in_flight=len(self.in_flight),
                max_concurrent=self.config.max_concurrent,
                threshold_pct=float(self.config.rate_limit_threshold_pct),
                gauge=self.rate_gauge,
            )

            if decision == SpawnDecision.SPAWN:
                task = self._queue.claim_next(claimer_id="supervisor")
                if task is not None:
                    self._log.info(
                        "task_claimed",
                        task_id=task.id,
                        title=task.title[:80],
                        in_flight=len(self.in_flight) + 1,
                        cap=self.config.max_concurrent,
                        usage_pct=self.rate_gauge.current_pct(),
                    )
                    self._spawn_runner(task)

            if self._once:
                _once_claimed = True

    def _resolve_coder(self, task: Task):
        """Pick (coder, coder_name, model) for a task.

        If the Supervisor was constructed with a pinned `coder=` instance (used
        in unit tests), reuse it as-is. Otherwise build a fresh coder using
        task.coder / task.model, falling back to config defaults.
        """
        if self._coder_pin is not None:
            return self._coder_pin, self._coder_pin.name, getattr(self._coder_pin, "model", None)
        coder_name = task.coder or self.config.coder
        model = task.model or self.config.model
        coder_cls = get_coder(coder_name)
        return coder_cls(model=model), coder_name, model

    def _spawn_runner(self, task: Task) -> None:
        task_root = Path(task.cwd) if task.cwd else self._project_root
        coder, coder_name, model = self._resolve_coder(task)
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
                if self._once and not self._shutting_down:
                    # once-mode: no tasks left → shut down
                    asyncio.ensure_future(self._shutdown())
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
            await asyncio.sleep(self.config.config_poll_interval_sec)
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
            await asyncio.sleep(self.config.status_log_interval_sec)
            if self._shutting_down:
                break
            self._log_status_snapshot()

    def _log_status_snapshot(self) -> None:
        self._log.info("supervisor_status", **self._fleet_log_context())

    def _fleet_log_context(self) -> dict:
        """Snapshot of live fleet stats — in-flight count, rate-limit usage."""
        return {
            "in_flight": len(self.in_flight),
            "cap": self.config.max_concurrent,
            "usage_pct": self.rate_gauge.current_pct(),
            "threshold_pct": self.config.rate_limit_threshold_pct,
            "paused_until": (
                self._paused_until.isoformat() if self._paused_until is not None else None
            ),
            "task_ids": sorted(self.in_flight.keys()),
        }

    def _handle_outcome(self, task: Task, outcome: TaskOutcomeRecord) -> None:
        fleet_ctx = self._fleet_log_context()
        match outcome.outcome:
            case TaskOutcome.SUCCESS:
                still_in_progress = False
                try:
                    current = self._queue.get(task.id)
                    still_in_progress = current.status == "in_progress"
                except Exception:
                    pass
                if still_in_progress:
                    self._queue.release(
                        task.id,
                        reason="agent exited rc=0 without close; re-queueing",
                    )
                    self._log.info(
                        "task_completed_success_re_queued", task_id=task.id, **fleet_ctx
                    )
                else:
                    self._log.info("task_completed_success", task_id=task.id, **fleet_ctx)

            case TaskOutcome.CONTEXT_PRESSURE:
                self._queue.release(task.id, reason="context_pressure; resume on next claim")
                self._log.info(
                    "task_context_pressure_release", task_id=task.id, **fleet_ctx
                )

            case TaskOutcome.RATE_LIMIT:
                now_ts = datetime.now(tz=timezone.utc).timestamp()
                resets_at = outcome.resets_at
                sleep_until_ts = max(
                    float(resets_at) if resets_at is not None else 0.0,
                    now_ts + self.config.rate_limit_default_sleep_sec,
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

            case TaskOutcome.FAILURE:
                new_count = increment_failure(self._task_dir_for(task))
                if new_count >= self.config.retry_limit:
                    self._queue.set_blocked(
                        task.id,
                        reason=(
                            f"retry limit ({self.config.retry_limit}) exhausted; "
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
                        retry_limit=self.config.retry_limit,
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
                        retry_limit=self.config.retry_limit,
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

        grace = float(self.config.shutdown_grace_sec)
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
        log_root = Path(self.config.log_root)
        if not log_root.is_absolute():
            log_root = self._project_root / log_root
        return log_root

    def _task_dir_for(self, task: Task) -> Path:
        return self._project_root / "tasks" / task.id
