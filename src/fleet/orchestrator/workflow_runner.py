"""The one `WorkflowRunnerLike` implementation (ADR 0015 §2).

Starts a saved workflow as a run and hands the job worker back plain ids
(`RunHandle`), never workflow types — `workers/job.py` must not import
`fleet.workflows` (layering, ADR 0006 rule 4). Only the orchestrator layer
may import both `fleet.workers` and `fleet.workflows`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from datetime import datetime

from fleet.beads.queue import Queue
from fleet.workers.base import RunHandle
from fleet.workflows import runs as workflow_runs
from fleet.workflows.model import Trigger, WorkflowRun
from fleet.workflows.store import WorkflowStore


class WorkflowRunner:
    """Starts a workflow run for a job's workflow-run child."""

    def __init__(self, store: WorkflowStore, queue: Queue, now: Callable[[], datetime]) -> None:
        self._store = store
        self._queue = queue
        self._now = now
        self._lock = threading.Lock()

    def _resolve(self, ref: str):
        """One workflow by id (wf- prefix) or name; raises ValueError when unknown."""
        found = self._store.get(ref) if ref.startswith("wf-") else self._store.get_by_name(ref)
        if found is None and not ref.startswith("wf-"):
            found = self._store.get(ref)
        if found is None:
            raise ValueError(f"workflow {ref!r} not found")
        return found

    def start(self, workflow_ref: str, inputs: Mapping[str, str]) -> RunHandle:
        """Start *workflow_ref* with *inputs*; return its ids as a RunHandle.

        When a live or succeeded run with identical inputs already exists
        (e.g. orphaned by a spawn attempt killed before it journaled the
        run), return a handle for THAT run instead of starting a second
        chain. The lock makes the find-or-start atomic within this process
        so concurrent spawn threads cannot double-start the same inputs.
        """
        workflow = self._resolve(workflow_ref)
        resolved = workflow_runs.resolve_inputs(workflow, inputs)
        with self._lock:
            existing = self._store.find_run_by_inputs(workflow.id, resolved)
            if existing is not None and self._store.step_runs(existing.id):
                return self._handle_of(existing)
            run = workflow_runs.start_run(
                workflow,
                store=self._store,
                queue=self._queue,
                now=self._now(),
                trigger=Trigger.manual,
                inputs=resolved,
            )
            return self._handle_of(run)

    def _handle_of(self, run: WorkflowRun) -> RunHandle:
        """A run's ids as a RunHandle (what the job worker wires deps to)."""
        steps = self._store.step_runs(run.id)
        last_stage = len(run.spec.stages) - 1
        return RunHandle(
            run_id=run.id,
            task_ids=tuple(step.task_id for step in steps),
            final_task_ids=tuple(step.task_id for step in steps if step.stage_index == last_stage),
        )
