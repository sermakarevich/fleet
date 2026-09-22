"""The `research` family: discover, design, gate, spawn, then observe.

A bead of type ``epic`` with ``fleet_worker=research`` (``fleet bd create
"<topic>" -t epic --worker research``) runs the same phase machine as the
``job`` family (ADR 0015): the same ``core/job_phase.phase_of`` table over
the same ``artifacts/RESEARCH.md`` / ``artifacts/tasks.json`` /
``artifacts/APPROVED`` snapshot, the same ``AskApproval`` /
``SpawnChildren`` / observe steps. Only the first two phases differ: the
discover and design prompts are research-specific (``ai show
research/get``), so they get their own launch modes and worker names
(``research.discover``, ``research.design``) while the gate/spawn/observe
arms keep their ``job.*`` names so ``core/job_plan.observer_rounds`` still
counts rounds and the Attempts timeline stays consistent across families.
"""

from __future__ import annotations

from fleet.beads.queue import Queue
from fleet.core.job_phase import phase_failures, phase_of
from fleet.core.plan_input import PlanInput
from fleet.state import attempts as state_attempts

from .base import QuestionStoreLike, Worker
from .job import AskApproval, BlockJob, JobPrepare, SpawnChildren, snapshot_for
from .llm_session import LlmSession
from .observe import CollectChildren, SpawnFollowups, WaitChildren


def plan_research(
    plan: PlanInput,
    queue: Queue,
    store: QuestionStoreLike | None = None,
) -> Worker:
    """Pick the research worker for this attempt: discover/design/gate/spawn/observe.

    Same snapshot and phase table as ``workers/job.py::plan_job``; only the
    discover and design arms use research-specific prompts and worker names.
    """
    snapshot = snapshot_for(plan, queue)
    current_phase = phase_of(snapshot)
    if current_phase in ("research", "design"):
        history = [
            a
            for a in state_attempts.load_attempts(plan.task_dir)
            if isinstance(a, dict) and a.get("n", 0) < plan.attempt_n
        ]
        max_attempts = plan.config.job_max_phase_attempts
        if phase_failures(history, current_phase) >= max_attempts:
            return Worker("job.blocked", (BlockJob(),))
    if current_phase == "research":
        return Worker("research.discover", (JobPrepare("research_discover"), LlmSession()))
    if current_phase == "design":
        return Worker("research.design", (JobPrepare("research_design"), LlmSession()))
    if current_phase == "gate":
        return Worker("job.gate", (AskApproval(store, research=True),))
    if current_phase == "spawn":
        return Worker("job.spawn", (SpawnChildren(queue),))
    return Worker(
        "job.observe",
        (WaitChildren(queue), CollectChildren(queue), LlmSession(), SpawnFollowups(queue)),
    )
