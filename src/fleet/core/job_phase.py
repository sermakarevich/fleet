"""Job worker phase policy. Pure: no I/O.

A ``job`` epic decomposes itself: research the repo, design a task list,
pass a human gate, spawn child beads, then observe them. ``plan_job``
(workers/job.py) reads the task directory into a ``JobSnapshot`` and calls
``phase()`` — the decision table lives here so it is testable without
files or beads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

JobPhase = Literal["research", "design", "gate", "spawn", "observe"]


@dataclass(frozen=True)
class JobSnapshot:
    """Everything ``phase()`` needs, read from files by the caller.

    - *has_research*: artifacts/RESEARCH.md exists.
    - *has_tasks*: artifacts/tasks.json exists and parses.
    - *gate_enabled*: cfg.job_gate and bead metadata fleet_job_gate != "off".
    - *approved*: artifacts/APPROVED exists.
    - *has_children*: the epic already has child beads.
    """

    has_research: bool = False
    has_tasks: bool = False
    gate_enabled: bool = True
    approved: bool = False
    has_children: bool = False


def phase(snapshot: JobSnapshot) -> JobPhase:
    """Pick the job phase for *snapshot* (decision table, deterministic).

    | Snapshot | Phase |
    |---|---|
    | no RESEARCH.md | research |
    | RESEARCH.md, no tasks.json | design |
    | tasks.json, gate on, no approval | gate |
    | tasks.json, approved (or gate off), no children | spawn |
    | children exist | observe |
    """
    if not snapshot.has_research:
        return "research"
    if not snapshot.has_tasks:
        return "design"
    if snapshot.has_children:
        return "observe"
    if snapshot.gate_enabled and not snapshot.approved:
        return "gate"
    return "spawn"


def phase_attempts(history: list[dict], phase_name: str) -> int:
    """Count attempts in *history* that ran the ``job.<phase>`` worker.

    Used for observability (the Attempts timeline shows one row per phase
    attempt). WAITING rows never count (the gate woke early, it did not
    run anything); compact rows never count.
    """
    want = f"job.{phase_name}"
    count = 0
    for entry in history:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == "compact":
            continue
        if entry.get("outcome") == "waiting":
            continue
        if entry.get("worker") == want:
            count += 1
    return count


def phase_failures(history: list[dict], phase_name: str) -> int:
    """Count failed ``job.<phase>`` attempts (outcome failure or stall/timeout kill).

    The per-phase cap (cfg.job_max_phase_attempts) counts failures only: a
    research/design attempt that ends PARTIAL succeeded and must move the
    job forward, never toward a block.
    """
    want = f"job.{phase_name}"
    count = 0
    for entry in history:
        if not isinstance(entry, dict):
            continue
        if entry.get("worker") != want:
            continue
        if entry.get("outcome") == "failure":
            count += 1
        elif entry.get("outcome") == "killed" and entry.get("reason") in (
            "stalled",
            "timeout",
        ):
            count += 1
    return count
