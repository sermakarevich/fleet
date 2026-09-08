"""Ordered services for the supervisor runner: hooks, ticks, adapters, emit."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from enum import IntEnum
from typing import TYPE_CHECKING

from fleet.core.task import TaskOutcomeRecord

if TYPE_CHECKING:
    from fleet.core.config import RuntimeConfig
    from fleet.orchestrator.state import RunningWorker, SupervisorState


class ServiceOrder(IntEnum):
    """Order of on_start/on_stop/event hooks. Ticks still interleave freely."""

    Config = 0
    Leases = 10
    Claim = 20
    Reap = 30
    Stall = 40
    Triage = 50
    Gc = 60
    Logging = 100


class Service:
    """One supervisor concern with lifecycle hooks and an optional body."""

    order: ServiceOrder = ServiceOrder.Logging
    name: str = "service"

    async def on_start(self, st: SupervisorState) -> None:
        """Run once before services start serving."""

    async def on_stop(self, st: SupervisorState) -> None:
        """Run once after serving stops."""

    async def on_worker_started(self, st: SupervisorState, worker: RunningWorker) -> None:
        """React to a newly spawned worker."""

    async def on_worker_finished(
        self, st: SupervisorState, worker: RunningWorker, outcome: TaskOutcomeRecord
    ) -> None:
        """React to a finished worker and its outcome."""

    async def on_config_reloaded(
        self, st: SupervisorState, old: RuntimeConfig, new: RuntimeConfig
    ) -> None:
        """React to a config reload."""

    async def serve(self, st: SupervisorState) -> None:
        """Long-running body. Default: return immediately (hook-only service)."""


class PeriodicService(Service):
    """A service that ticks on a fixed interval until shutdown."""

    def __init__(self, interval_sec: float) -> None:
        self.interval_sec = interval_sec

    async def tick(self, st: SupervisorState) -> None:
        """Do one unit of periodic work."""
        raise NotImplementedError

    async def serve(self, st: SupervisorState) -> None:
        """Sleep, tick, and log tick failures until shutdown."""
        while not st.shutting_down:
            await asyncio.sleep(self.interval_sec)
            if st.shutting_down:
                break
            try:
                await self.tick(st)
            except Exception as exc:  # noqa: BLE001 - a bad tick must not kill the loop
                st.log.warning(f"{self.name}_tick_failed", error=str(exc))


class LegacyLoop(Service):
    """Adapter for a not-yet-migrated mixin loop coroutine (deleted in bead 4)."""

    def __init__(
        self,
        name: str,
        order: ServiceOrder,
        loop_factory: Callable[[], Awaitable[None]],
    ) -> None:
        self.name = name
        self.order = order
        self._loop_factory = loop_factory

    async def serve(self, st: SupervisorState) -> None:
        """Run the wrapped legacy loop coroutine."""
        await self._loop_factory()


async def emit(services: Sequence[Service], event: str, st: SupervisorState, *args) -> None:
    """Call `event` on every service in order; log and continue on error."""
    for svc in sorted(services, key=lambda s: s.order):
        try:
            await getattr(svc, event)(st, *args)
        except Exception as exc:  # noqa: BLE001 - one bad service must not stop the rest
            st.log.warning(f"{svc.name}_{event}_failed", error=str(exc))
