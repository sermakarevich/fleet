from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from fleet.core.limits import LEASE_RECONCILE_INTERVAL_SEC, STATUS_LOG_INTERVAL_SEC
from fleet.state.attempts import latest_attempt_dir
from fleet.state.paths import task_dir as _task_dir


class StallMixin:
    async def _status_log_loop(self) -> None:
        """Periodically emit a heartbeat with in-flight count and rate-limit usage.

        Every LEASE_RECONCILE_INTERVAL_SEC the same tick also runs
        reconcile_leases(), so beads orphaned by a runner that died
        without reaping are re-queued while the supervisor keeps running.
        """
        while not self._shutting_down:
            await asyncio.sleep(STATUS_LOG_INTERVAL_SEC)
            if self._shutting_down:
                break
            self._log_status_snapshot()
            now = time.monotonic()
            last = getattr(self, "_last_lease_reconcile", None)
            if last is None or now - last >= LEASE_RECONCILE_INTERVAL_SEC:
                self._last_lease_reconcile = now
                try:
                    self.reconcile_leases()
                except Exception as exc:  # noqa: BLE001 - lease sweep must not kill the loop
                    self._log.warning("lease_reconcile_failed", error=str(exc))
            # Triage is scheduled from this same status loop (ADR 0003: a
            # loop over all blocked beads, not a per-bead worker). The mixin
            # no-ops when the queue lacks list_blocked or the interval is 0.
            tick = getattr(self, "triage_tick_if_due", None)
            if tick is not None:
                try:
                    tick()
                except Exception as exc:  # noqa: BLE001 - triage must not kill the loop
                    self._log.warning("triage_tick_failed", error=str(exc))

    def _log_status_snapshot(self) -> None:
        self._log.info("supervisor_status", **self._fleet_log_context())
        if self.config.stall_warning_minutes <= 0:
            return
        now = datetime.now(tz=UTC).timestamp()
        for task_id in list(self.in_flight):
            task_dir = _task_dir(self._project_root, task_id)
            attempt_dir = latest_attempt_dir(task_dir)
            if attempt_dir is None:
                continue
            events_path = attempt_dir / "events.jsonl"
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
