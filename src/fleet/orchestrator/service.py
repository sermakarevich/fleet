"""Ordered services for the supervisor runner: hooks, ticks, emit.

Called by ``orchestrator/supervisor.py`` (lifecycle), ``orchestrator/``
``default_services`` (wiring), and the claim/reap/config_reload services
(cross-service events). A ``Service`` is any object with a ``name``, an
``order``, and a ``serve`` body; lifecycle hooks (``on_start``, ...) are
optional and collected once by ``build_hooks``. Periodic work is data: a
``PeriodicService`` holds ``interval_sec`` plus a ``tick`` function instead
of subclassing a loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


class ServiceOrder(IntEnum):
    """Order of on_start/on_stop/event hooks. Ticks still interleave freely."""

    Config = 0
    Leases = 10
    Schedule = 15
    Claim = 20
    Reap = 30
    Stall = 40
    Triage = 50
    Gc = 60
    Logging = 100


class Service(Protocol):
    """One supervisor concern: a name, an order, and a long-running body.

    Lifecycle hooks (``on_start``, ``on_stop``, ``on_worker_started``,
    ``on_worker_finished``, ``on_config_reloaded``) are optional: a service
    defines only the hooks it needs, and ``build_hooks`` skips the rest.
    """

    @property
    def name(self) -> str:
        """Service name used for task names and tick-failure logs."""
        ...

    @property
    def order(self) -> ServiceOrder:
        """Hook order (see ServiceOrder)."""
        ...

    async def serve(self, st: SupervisorState) -> None:
        """Long-running body; returns immediately for hook-only services."""
        ...


#: Lifecycle hooks build_hooks collects; everything else on a service is ignored.
HOOK_NAMES: tuple[str, ...] = (
    "on_start",
    "on_stop",
    "on_worker_started",
    "on_worker_finished",
    "on_config_reloaded",
)

#: One collected hook: called as ``await fn(st, *args)`` in service order.
HookFn = Callable[..., Awaitable[None]]


def build_hooks(services: Sequence[Service]) -> dict[str, list[tuple[str, HookFn]]]:
    """Collect each service's hooks once, in order; services lacking a hook are skipped.

    Each entry keeps its owner's name so failure logs stay
    ``<service>_<event>_failed``.
    """
    hooks: dict[str, list[tuple[str, HookFn]]] = {name: [] for name in HOOK_NAMES}
    for svc in sorted(services, key=lambda s: s.order):
        for name in HOOK_NAMES:
            fn = getattr(svc, name, None)
            if fn is not None:
                hooks[name].append((svc.name, fn))
    return hooks


async def emit_hooks(
    hooks: dict[str, list[tuple[str, HookFn]]], event: str, st: SupervisorState, *args
) -> None:
    """Call every collected *event* hook; log and continue on error."""
    for svc_name, fn in hooks.get(event, []):
        try:
            await fn(st, *args)
        except Exception as exc:  # noqa: BLE001 - one bad service must not stop the rest
            st.log.warning(f"{svc_name}_{event}_failed", error=str(exc))


async def emit(services: Sequence[Service], event: str, st: SupervisorState, *args) -> None:
    """Call *event* on every service that defines it, in order.

    Kept for rare cross-service events (worker started/finished, config
    reloaded) fired from inside services via ``st.services``. The
    supervisor lifecycle (on_start/on_stop) prebuilds its hooks once with
    ``build_hooks`` and calls ``emit_hooks`` directly.
    """
    await emit_hooks(build_hooks(services), event, st, *args)


async def run_periodic(
    name: str,
    interval_sec: float,
    tick: Callable[[SupervisorState], Awaitable[None]],
    st: SupervisorState,
) -> None:
    """Sleep, tick, and log tick failures until shutdown (the one periodic loop)."""
    while not st.shutting_down:
        await asyncio.sleep(interval_sec)
        if st.shutting_down:
            break
        try:
            await tick(st)
        except Exception as exc:  # noqa: BLE001 - a bad tick must not kill the loop
            st.log.warning(f"{name}_tick_failed", error=str(exc))


@dataclass(frozen=True)
class PeriodicService:
    """A service that ticks on a fixed interval until shutdown (data, not a base class)."""

    name: str
    order: ServiceOrder
    interval_sec: float
    tick: Callable[[SupervisorState], Awaitable[None]]
    on_start: Callable[[SupervisorState], Awaitable[None]] | None = None

    async def serve(self, st: SupervisorState) -> None:
        """Sleep, tick, and log tick failures until shutdown."""
        await run_periodic(self.name, self.interval_sec, self.tick, st)
