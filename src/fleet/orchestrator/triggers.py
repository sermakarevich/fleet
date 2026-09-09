"""Trigger service: periodic tick that fires enabled triggers on their sources.

Called by ``orchestrator/`` ``default_services`` (wiring). The work is one
``trigger_tick`` function; ``make_trigger_service`` wraps it in a
``PeriodicService`` with the trigger cadence. Its only writes are the firing
files under ``$FLEET_HOME/triggers/`` and the beads it opens; it never
touches ``st.running`` or any other service's field.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fleet.core.limits import TRIGGER_TICK_SEC
from fleet.orchestrator.pause import is_paused
from fleet.orchestrator.service import PeriodicService, ServiceOrder
from fleet.triggers.firing import fire_due
from fleet.triggers.store import TriggerStore

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


async def trigger_tick(st: SupervisorState) -> None:
    """Fire every enabled trigger due at now; skip the tick while paused."""
    if is_paused(st):
        return
    store = TriggerStore(st.fleet_home)
    # bd calls are blocking; run them in a worker thread
    # so the event loop keeps tailing runner output.
    await asyncio.to_thread(
        fire_due,
        store=store,
        queue=st.queue,
        fleet_home=st.fleet_home,
        now=st.clock.now(),
        log=st.log,
    )


def make_trigger_service(interval_sec: float = TRIGGER_TICK_SEC) -> PeriodicService:
    """Build the trigger periodic service (startup catch-up + fixed cadence)."""
    return PeriodicService(
        name="triggers",
        order=ServiceOrder.Trigger,
        interval_sec=interval_sec,
        tick=trigger_tick,
        on_start=trigger_tick,
    )
