"""Supervisor runner: lifecycle driver for ordered services."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import AsyncIterator, Sequence

from fleet.core.config import RuntimeConfig
from fleet.core.limits import SHUTDOWN_GRACE_SEC

from .checks import DEFAULT_CHECKS, StartupCheck, run_startup_checks
from .service import Service, emit
from .state import SupervisorState


class Supervisor:
    """Run services from on_start to on_stop; owns lifecycle, nothing else."""

    def __init__(
        self,
        state: SupervisorState,
        services: list[Service],
        checks: Sequence[StartupCheck] | None = None,
        shutdown_grace_sec: float | None = None,
    ) -> None:
        self.state = state
        self._services: list[Service] = sorted(services, key=lambda s: s.order)
        self._checks: Sequence[StartupCheck] = list(checks) if checks is not None else list(
            DEFAULT_CHECKS
        )
        self.shutdown_grace_sec = (
            float(shutdown_grace_sec)
            if shutdown_grace_sec is not None
            else float(SHUTDOWN_GRACE_SEC)
        )
        self.state.services = self._services
        self._done: asyncio.Event | None = None

    @property
    def config(self) -> RuntimeConfig:
        """Live runtime config (delegates to state)."""
        return self.state.config

    @config.setter
    def config(self, value: RuntimeConfig) -> None:
        self.state.config = value

    async def run(self) -> int:
        """Check, start, serve until shutdown, stop; always return 0."""
        async with self._signals_to_shutdown():
            run_startup_checks(self.state, self._checks)
            self.state.services = self._services
            await emit(self._services, "on_start", self.state)
            await self._serve_until_shutdown()
            await emit(self._services, "on_stop", self.state)
        return 0

    @contextlib.asynccontextmanager
    async def _signals_to_shutdown(self) -> AsyncIterator[None]:
        """Wire SIGINT/SIGTERM to shutdown for the duration of run()."""
        if self._done is None:
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
        """Point SIGINT/SIGTERM at _shutdown on the running loop."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(self._shutdown()))

    async def _shutdown(self) -> None:
        """Cancel runners, force-release stragglers past grace, then unblock run()."""
        if self.state.shutting_down:
            return
        self.state.shutting_down = True
        self.state.log.info("supervisor_shutdown_initiated")
        if self._done is None:
            self._done = asyncio.Event()
        grace = float(self.shutdown_grace_sec)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + grace

        if self.state.running:
            await asyncio.gather(
                *[rw.run.cancel() for rw in self.state.running.values()],
                return_exceptions=True,
            )

        if self.state.running:
            remaining = deadline - loop.time()
            futures = [rw.future for rw in self.state.running.values()]
            if remaining > 0:
                _, still_running = await asyncio.wait(futures, timeout=remaining)
            else:
                still_running = set(futures)
            for async_task in still_running:
                task_id = next(
                    (tid for tid, rw in self.state.running.items() if rw.future is async_task),
                    None,
                )
                if task_id is not None:
                    try:
                        self.state.queue.release(
                            task_id, reason="supervisor shutdown: forced release"
                        )
                    except Exception:
                        pass

        self.state.log.info("supervisor_shutdown_complete")
        self._done.set()  # created lazily above; always present here
