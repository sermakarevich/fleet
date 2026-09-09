"""Kill sentinel: poll for .kill files and terminate the matching runner.

Called by ``orchestrator/`` ``default_services`` (wiring). The work is one
``kill_sentinel_tick`` function; ``make_kill_sentinel`` wraps it in a
``PeriodicService`` with the polling cadence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fleet.orchestrator.service import PeriodicService, ServiceOrder

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


async def kill_sentinel_tick(st: SupervisorState) -> None:
    """Unlink present .kill files and kill the matching runner once."""
    for task_id, worker in list(st.running.items()):
        kill_file = st.task_dir_for(task_id) / ".kill"
        if kill_file.exists():
            kill_file.unlink(missing_ok=True)
            st.log.info("task_kill_requested", task_id=task_id)
            await worker.run.kill()


def make_kill_sentinel(interval_sec: float = 1.0) -> PeriodicService:
    """Build the kill-sentinel periodic service (default: poll every second)."""
    return PeriodicService(
        name="kill_sentinel",
        order=ServiceOrder.Stall,
        interval_sec=interval_sec,
        tick=kill_sentinel_tick,
    )
