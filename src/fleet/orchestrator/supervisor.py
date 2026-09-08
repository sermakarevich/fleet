from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from pathlib import Path

import structlog

from fleet.beads.queue import Queue
from fleet.coders.base import Coder
from fleet.core.config import RuntimeConfig, load
from fleet.core.limits import (
    SHUTDOWN_GRACE_SEC,
)
from fleet.core.task import Task
from fleet.state.paths import task_dir as _task_dir
from fleet.workers.base import WorkerRun

from .checks import DEFAULT_CHECKS, StartupCheck, run_startup_checks
from .claim import ClaimMixin
from .config_reload import ConfigReload
from .kill_sentinel import KillSentinel
from .leases import LeasesMixin
from .rate_gauge import RateGauge
from .reap import ReapMixin
from .retention_gc import RetentionGc
from .service import LegacyLoop, Service, ServiceOrder, emit
from .spawn import SpawnMixin
from .stall import StallMixin
from .state import SupervisorState
from .status_log import StatusLog
from .triage import TriageMixin


class StartupSweeps(Service):
    """Run the startup state sweeps once in on_start (owns no loop)."""

    order = ServiceOrder.Leases
    name = "startup_sweeps"

    def __init__(self, supervisor: Supervisor) -> None:
        self._supervisor = supervisor

    async def on_start(self, st: SupervisorState) -> None:
        """Sweep orphan worktrees and reconcile leases once."""
        sup = self._supervisor
        sup._sweep_orphan_worktrees()
        sup.reconcile_leases()


class Supervisor(ClaimMixin, SpawnMixin, ReapMixin, StallMixin, LeasesMixin, TriageMixin):
    def __init__(
        self,
        queue: Queue,
        runtime_toml_path: Path,
        project_root: Path,
        log: structlog.BoundLogger,
        coder: Coder | None = None,
        *,
        services: list[Service] | None = None,
        checks: list[StartupCheck] | None = None,
    ) -> None:
        # Tests inject a single Coder instance via `coder=`; production callers
        # leave it None so the supervisor resolves (coder, model) per task
        # from task.coder / task.model, falling back to config defaults.
        self.state = SupervisorState(
            config=load(runtime_toml_path),
            project_root=Path(project_root),
            runtime_toml_path=Path(runtime_toml_path),
            queue=queue,
            log=log,
            rate_gauge=RateGauge(log=log),
            coder_pin=coder,
        )
        self._services: list[Service] = services if services is not None else self.default_services()
        self._checks: Sequence[StartupCheck] = checks if checks is not None else list(DEFAULT_CHECKS)
        self.state.services = self._services

        self._done: asyncio.Event | None = None
        self._stall_warned: set[str] = set()
        self._stall_killed: set[str] = set()
        # Dedupe keys for recurring lease notices ("event:task_id") and the
        # last periodic reconcile_leases() run (epoch seconds, monotonic).
        self._lease_logged: set[str] = set()
        self._last_lease_reconcile: float | None = None

    @property
    def config(self) -> RuntimeConfig:
        """Live runtime config (delegates to state)."""
        return self.state.config

    @config.setter
    def config(self, value: RuntimeConfig) -> None:
        self.state.config = value

    @property
    def rate_gauge(self) -> RateGauge:
        """Rate-limit gauge (delegates to state)."""
        return self.state.rate_gauge

    @rate_gauge.setter
    def rate_gauge(self, value: RateGauge) -> None:
        self.state.rate_gauge = value

    @property
    def _queue(self) -> Queue:
        return self.state.queue

    @_queue.setter
    def _queue(self, value: Queue) -> None:
        self.state.queue = value

    @property
    def _log(self):  # type: ignore[no-untyped-def]
        return self.state.log

    @_log.setter
    def _log(self, value) -> None:  # type: ignore[no-untyped-def]
        self.state.log = value

    @property
    def _project_root(self) -> Path:
        return self.state.project_root

    @_project_root.setter
    def _project_root(self, value: Path) -> None:
        self.state.project_root = Path(value)

    @property
    def _runtime_toml_path(self) -> Path:
        return self.state.runtime_toml_path

    @_runtime_toml_path.setter
    def _runtime_toml_path(self, value: Path) -> None:
        self.state.runtime_toml_path = Path(value)

    @property
    def _coder_pin(self) -> Coder | None:
        return self.state.coder_pin

    @_coder_pin.setter
    def _coder_pin(self, value: Coder | None) -> None:
        self.state.coder_pin = value

    @property
    def _paused_until(self) -> datetime | None:
        return self.state.paused_until

    @_paused_until.setter
    def _paused_until(self, value: datetime | None) -> None:
        self.state.paused_until = value

    @property
    def _shutting_down(self) -> bool:
        return self.state.shutting_down

    @_shutting_down.setter
    def _shutting_down(self, value: bool) -> None:
        self.state.shutting_down = value

    @property
    def in_flight(self) -> dict[str, asyncio.Task]:
        """In-flight asyncio tasks by task id (delegates to state)."""
        return self.state.in_flight

    @in_flight.setter
    def in_flight(self, value: dict[str, asyncio.Task]) -> None:
        self.state.in_flight = value

    @property
    def in_flight_tasks(self) -> dict[str, Task]:
        """In-flight tasks by task id (delegates to state)."""
        return self.state.in_flight_tasks

    @in_flight_tasks.setter
    def in_flight_tasks(self, value: dict[str, Task]) -> None:
        self.state.in_flight_tasks = value

    @property
    def _runners(self) -> dict[str, WorkerRun]:
        return self.state.runners

    @_runners.setter
    def _runners(self, value: dict[str, WorkerRun]) -> None:
        self.state.runners = value

    @property
    def _attempt_n(self) -> dict[str, int]:
        return self.state.attempt_n

    @_attempt_n.setter
    def _attempt_n(self, value: dict[str, int]) -> None:
        self.state.attempt_n = value

    def default_services(self) -> list[Service]:
        """Build the production service list (legacy loops behind adapters)."""
        return [
            ConfigReload(),
            StartupSweeps(self),
            LegacyLoop("claim_and_spawn", ServiceOrder.Claim, lambda: self._claim_and_spawn_loop()),
            LegacyLoop("reap", ServiceOrder.Reap, lambda: self._reap_loop()),
            LegacyLoop(
                "legacy_stall_leases_triage",
                ServiceOrder.Stall,
                lambda: self._status_log_loop(),
            ),
            KillSentinel(),
            RetentionGc(),
            StatusLog(),
        ]

    async def run(self) -> int:
        async with self._signals_to_shutdown():
            run_startup_checks(self.state, self._checks)
            self.state.services = self._services
            await emit(self._services, "on_start", self.state)
            await self._serve_until_shutdown()
            await emit(self._services, "on_stop", self.state)
        return 0

    @contextlib.asynccontextmanager
    async def _signals_to_shutdown(self) -> AsyncIterator[None]:
        """Create the done event, wire SIGINT/SIGTERM to shutdown, then clean up."""
        self._done = asyncio.Event()
        loop = asyncio.get_running_loop()
        self._install_signal_handlers(loop)
        try:
            yield
        finally:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sig)

    async def _serve_until_shutdown(self) -> None:
        """Serve every service until _shutdown fires, then cancel them."""
        assert self._done is not None
        bg = [asyncio.create_task(svc.serve(self.state), name=svc.name) for svc in self._services]
        await self._done.wait()
        for t in bg:
            t.cancel()
        await asyncio.gather(*bg, return_exceptions=True)

    def _install_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.ensure_future(self._shutdown()),
            )

    async def _shutdown(self) -> None:
        if self.state.shutting_down:
            return
        self.state.shutting_down = True
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
