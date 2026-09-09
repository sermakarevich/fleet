"""Periodic workflow refresh: fold bead statuses into open workflow runs.

Called by ``orchestrator/`` ``default_services`` (wiring). The work is one
``workflow_refresh_pass`` function over every run still `running` or
`attention`; ``make_workflow_refresh`` wraps it in a ``PeriodicService``.
Without this, run history would go stale whenever nobody opens the UI.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fleet.core.limits import WORKFLOW_REFRESH_SEC
from fleet.orchestrator.service import PeriodicService, ServiceOrder
from fleet.state.paths import workflows_db_path
from fleet.workflows.model import RunStatus
from fleet.workflows.runs import refresh_run
from fleet.workflows.store import WorkflowStore

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState

_OPEN_STATUSES = (RunStatus.running, RunStatus.attention)
"""Runs worth refreshing: finished runs are never touched."""


def workflow_refresh_pass(fleet_home: Path, queue: Any, now: datetime, log: Any) -> int:
    """Refresh every open workflow run; return how many were refreshed."""
    store = WorkflowStore(workflows_db_path(fleet_home))
    refreshed = 0
    for run in store.list_runs(limit=10_000):
        if run.status not in _OPEN_STATUSES:
            continue
        try:
            refresh_run(run, store=store, queue=queue, now=now)
            refreshed += 1
        except Exception as exc:  # noqa: BLE001 - one bad run must not stop the rest
            log.warning("workflow_refresh_failed", run_id=run.id, error=str(exc))
    if refreshed:
        log.info("workflow_refresh", refreshed=refreshed)
    return refreshed


async def workflow_refresh_tick(st: SupervisorState) -> None:
    """Refresh every open workflow run in a worker thread (bd calls block)."""
    await asyncio.to_thread(workflow_refresh_pass, st.fleet_home, st.queue, st.clock.now(), st.log)


def make_workflow_refresh(interval_sec: float = WORKFLOW_REFRESH_SEC) -> PeriodicService:
    """Build the workflow-refresh periodic service (default: the refresh cadence)."""
    return PeriodicService(
        name="workflow_refresh",
        order=ServiceOrder.WorkflowRefresh,
        interval_sec=interval_sec,
        tick=workflow_refresh_tick,
    )
