"""Scheduler service: periodic tick that opens beads for due schedules.

Called by ``orchestrator/`` ``default_services`` (wiring). The work is one
``scheduler_tick`` function; ``make_scheduler`` wraps it in a
``PeriodicService`` with the schedule cadence. Its only writes are the run
files under ``$FLEET_HOME/schedules/`` and the beads it opens; it never
touches ``st.running`` or any other service's field.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fleet.core.limits import SCHEDULER_TICK_SEC
from fleet.orchestrator.pause import is_paused
from fleet.orchestrator.service import PeriodicService, ServiceOrder
from fleet.schedules.firing import fire_due
from fleet.schedules.store import ScheduleStore
from fleet.state.paths import workflows_db_path
from fleet.workflows.store import WorkflowStore

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


async def scheduler_tick(st: SupervisorState) -> None:
    """Fire every schedule due at now; skip the tick while paused."""
    if is_paused(st):
        return
    store = ScheduleStore(st.fleet_home)
    workflow_store = WorkflowStore(workflows_db_path(st.fleet_home))
    now = st.clock.now()
    # bd calls are blocking; run them in a worker thread
    # so the event loop keeps tailing runner output.
    await asyncio.to_thread(
        fire_due,
        store=store,
        queue=st.queue,
        now=now,
        log=st.log,
        workflow_store=workflow_store,
    )


def make_scheduler(interval_sec: float = SCHEDULER_TICK_SEC) -> PeriodicService:
    """Build the scheduler periodic service (startup catch-up + fixed cadence)."""
    return PeriodicService(
        name="scheduler",
        order=ServiceOrder.Schedule,
        interval_sec=interval_sec,
        tick=scheduler_tick,
        on_start=scheduler_tick,
    )
