"""Stall watchdog: warn about quiet workers and kill them when configured.

A worker is stalled when its latest attempt has written no events for
longer than `stall_warning_minutes`. The first quiet tick logs
`task_stalled` once; with `stall_action="kill"` the runner is killed once
as well. Both scratch sets are cleared in `on_worker_finished`, so no id
ever outlives its worker.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fleet.core.limits import STATUS_LOG_INTERVAL_SEC
from fleet.core.task import TaskOutcomeRecord
from fleet.state.attempts import latest_attempt_dir

from .service import ServiceOrder, run_periodic

if TYPE_CHECKING:
    from .state import RunningWorker, SupervisorState


class StallWatch:
    """Watch event silence per worker; warn once, kill once when configured."""

    order = ServiceOrder.Stall
    name = "stall_watch"

    def __init__(self, interval_sec: float | None = None) -> None:
        self.interval_sec = interval_sec if interval_sec is not None else STATUS_LOG_INTERVAL_SEC
        self._warned: set[str] = set()
        self._killed: set[str] = set()

    async def on_worker_finished(
        self, st: SupervisorState, worker: RunningWorker, outcome: TaskOutcomeRecord
    ) -> None:
        """Forget a finished worker so no id outlives its attempt."""
        _ = (st, outcome)
        self._warned.discard(worker.task.id)
        self._killed.discard(worker.task.id)

    async def serve(self, st: SupervisorState) -> None:
        """Tick on the stall cadence until shutdown (shared periodic loop)."""
        await run_periodic(self.name, self.interval_sec, self.tick, st)

    async def tick(self, st: SupervisorState) -> None:
        """Warn about (and maybe kill) workers quiet past the stall threshold."""
        if st.config.stall_warning_minutes <= 0:
            return
        now = datetime.now(tz=UTC).timestamp()
        for task_id in list(st.running):
            attempt_dir = latest_attempt_dir(st.task_dir_for(task_id))
            if attempt_dir is None:
                continue
            try:
                mtime = (attempt_dir / "events.jsonl").stat().st_mtime
            except FileNotFoundError:
                continue
            idle = now - mtime
            if idle > st.config.stall_warning_minutes * 60:
                self._warn_once(st, task_id, idle)
            else:
                self._warned.discard(task_id)

    def _warn_once(self, st: SupervisorState, task_id: str, idle: float) -> None:
        """Log the first quiet sighting of a task and kill it when configured."""
        if task_id in self._warned:
            return
        st.log.warning(
            "task_stalled",
            task_id=task_id,
            idle_seconds=int(idle),
            stall_warning_minutes=st.config.stall_warning_minutes,
        )
        self._warned.add(task_id)
        if st.config.stall_action == "kill" and task_id not in self._killed:
            self._kill_once(st, task_id, idle)

    def _kill_once(self, st: SupervisorState, task_id: str, idle: float) -> None:
        """Schedule one runner kill for a stalled task that is still in flight."""
        worker = st.running.get(task_id)
        runner = worker.run if worker is not None else None
        if runner is None:
            return
        self._killed.add(task_id)
        st.log.warning("task_stall_kill", task_id=task_id, idle_seconds=int(idle))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(runner.kill(reason="stalled"))
