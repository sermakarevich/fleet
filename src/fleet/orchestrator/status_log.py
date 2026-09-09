"""Periodic supervisor heartbeat: log in-flight count and rate-limit usage.

Called by ``orchestrator/`` ``default_services`` (wiring) and
``orchestrator/reap.py`` (``fleet_log_context`` for outcome lines). The
work is one ``status_log_tick`` function; ``make_status_log`` wraps it in
a ``PeriodicService`` with the heartbeat cadence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fleet.core.limits import STATUS_LOG_INTERVAL_SEC
from fleet.orchestrator.service import PeriodicService, ServiceOrder
from fleet.state.events import event_stats
from fleet.state.paths import workflows_db_path
from fleet.workflows.model import RunStatus
from fleet.workflows.store import WorkflowStore

if TYPE_CHECKING:
    from fleet.core.task import Task
    from fleet.orchestrator.state import SupervisorState


def task_log_fields(task: Task) -> dict:
    """Per-task log context bound once per reap (replaces threaded fleet_ctx)."""
    return {"task_id": task.id}


def open_workflow_runs(fleet_home) -> int:
    """Count of workflow runs still running (0 when the store is unreadable)."""
    try:
        store = WorkflowStore(workflows_db_path(fleet_home))
        return sum(1 for run in store.list_runs(limit=10_000) if run.status is RunStatus.running)
    except Exception:  # noqa: BLE001 - a heartbeat line must never fail
        return 0


def fleet_log_context(st: SupervisorState) -> dict:
    """Snapshot of live fleet stats — in-flight count, rate-limit usage."""
    usage_pct = st.rate_gauge.current_pct()  # may trigger auto-reset
    return {
        "in_flight": len(st.running),
        "cap": st.config.max_concurrent,
        "usage_pct": usage_pct,
        "paused_until": (st.paused_until.isoformat() if st.paused_until is not None else None),
        "rate_limit_resets_at": st.rate_gauge.resets_at,
        "task_ids": sorted(st.running.keys()),
        "workflow_runs": open_workflow_runs(st.fleet_home),
        "context_tokens": {
            tid: (event_stats(st.task_dir_for(tid)).peak_context_tokens or 0) for tid in st.running
        },
    }


async def status_log_tick(st: SupervisorState) -> None:
    """Log one supervisor_status heartbeat line."""
    st.log.info("supervisor_status", **fleet_log_context(st))


def make_status_log(interval_sec: float = STATUS_LOG_INTERVAL_SEC) -> PeriodicService:
    """Build the status-log periodic service (default: the status cadence)."""
    return PeriodicService(
        name="status_log",
        order=ServiceOrder.Logging,
        interval_sec=interval_sec,
        tick=status_log_tick,
    )
