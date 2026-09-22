"""The one `WorkflowRunnerLike` implementation (ADR 0015 §2).

Starts a saved workflow as a run and hands the job worker back plain ids
(`RunHandle`), never workflow types — `workers/job.py` must not import
`fleet.workflows` (layering, ADR 0006 rule 4). Only the orchestrator layer
may import both `fleet.workers` and `fleet.workflows`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from fleet.beads.queue import Queue
from fleet.workers.base import RunHandle
from fleet.workflows import runs as workflow_runs
from fleet.workflows.model import Trigger
from fleet.workflows.store import WorkflowStore


class WorkflowRunner:
    """Starts a workflow run for a job's workflow-run child."""

    def __init__(self, store: WorkflowStore, queue: Queue, now: Callable[[], datetime]) -> None:
        self._store = store
        self._queue = queue
        self._now = now

    def _resolve(self, ref: str):
        """One workflow by id (wf- prefix) or name; raises ValueError when unknown."""
        found = self._store.get(ref) if ref.startswith("wf-") else self._store.get_by_name(ref)
        if found is None and not ref.startswith("wf-"):
            found = self._store.get(ref)
        if found is None:
            raise ValueError(f"workflow {ref!r} not found")
        return found

    def start(self, workflow_ref: str, inputs: Mapping[str, str]) -> RunHandle:
        """Start *workflow_ref* with *inputs*; return its ids as a RunHandle."""
        workflow = self._resolve(workflow_ref)
        run = workflow_runs.start_run(
            workflow,
            store=self._store,
            queue=self._queue,
            now=self._now(),
            trigger=Trigger.manual,
            inputs=inputs,
        )
        steps = self._store.step_runs(run.id)
        last_stage = len(run.spec.stages) - 1
        return RunHandle(
            run_id=run.id,
            task_ids=tuple(step.task_id for step in steps),
            final_task_ids=tuple(step.task_id for step in steps if step.stage_index == last_stage),
        )
