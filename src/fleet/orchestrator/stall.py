from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fleet.core.limits import STATUS_LOG_INTERVAL_SEC
from fleet.state.paths import task_dir as _task_dir


class StallMixin:
    async def _status_log_loop(self) -> None:
        """Periodically emit a heartbeat with in-flight count and rate-limit usage."""
        while not self._shutting_down:
            await asyncio.sleep(STATUS_LOG_INTERVAL_SEC)
            if self._shutting_down:
                break
            self._log_status_snapshot()

    def _log_status_snapshot(self) -> None:
        self._log.info("supervisor_status", **self._fleet_log_context())
        if self.config.stall_warning_minutes <= 0:
            return
        now = datetime.now(tz=timezone.utc).timestamp()
        for task_id in list(self.in_flight):
            events_path = _task_dir(self._project_root, task_id) / "events.jsonl"
            try:
                mtime = events_path.stat().st_mtime
            except FileNotFoundError:
                continue
            idle = now - mtime
            if idle > self.config.stall_warning_minutes * 60:
                if task_id not in self._stall_warned:
                    self._log.warning(
                        "task_stalled",
                        task_id=task_id,
                        idle_seconds=int(idle),
                        stall_warning_minutes=self.config.stall_warning_minutes,
                    )
                    self._stall_warned.add(task_id)
                    if self.config.stall_action == "kill" and task_id not in self._stall_killed:
                        runner = self._runners.get(task_id)
                        if runner is not None:
                            self._stall_killed.add(task_id)
                            self._log.warning("task_stall_kill", task_id=task_id, idle_seconds=int(idle))
                            try:
                                loop = asyncio.get_running_loop()
                            except RuntimeError:
                                loop = None
                            if loop is not None:
                                loop.create_task(runner.kill(reason="stalled"))
            else:
                self._stall_warned.discard(task_id)
