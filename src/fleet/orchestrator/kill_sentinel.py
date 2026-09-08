"""Kill sentinel: poll for .kill files and terminate the matching runner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fleet.orchestrator.service import PeriodicService, ServiceOrder

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


class KillSentinel(PeriodicService):
    """Delete .kill sentinels and kill the matching in-flight runner."""

    order = ServiceOrder.Stall
    name = "kill_sentinel"

    def __init__(self, interval_sec: float = 1.0) -> None:
        super().__init__(interval_sec)

    async def tick(self, st: SupervisorState) -> None:
        """Unlink present .kill files and kill the matching runner once."""
        for task_id, worker in list(st.running.items()):
            kill_file = st.task_dir_for(task_id) / ".kill"
            if kill_file.exists():
                kill_file.unlink(missing_ok=True)
                st.log.info("task_kill_requested", task_id=task_id)
                await worker.run.kill()
