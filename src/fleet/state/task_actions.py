"""File edits behind task moderation endpoints, one owner.

Called by serve/api/tasks_actions.py (and serve/api/beads.py for
remove_assignee). Every task.json write goes through TaskMeta and every
journal write through AttemptJournal (via state.attempts) — handlers never
touch the files directly. Queue (beads layer) is taken as a structural
``TaskQueue`` so this state module never imports a higher layer; beads
errors propagate to the serve caller, which maps them to HTTP codes.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from fleet.core.task import TaskStatus
from fleet.state.attempts import record_unblock
from fleet.state.paths import KILL_MARKER
from fleet.state.paths import task_dir as task_dir_for
from fleet.state.task_meta import TaskMeta
from fleet.state.validation_marker import clear_needs_validation

UNBLOCK_REASON = "[fleet] unblocked from UI"

#: Outcomes of kill(); kept as plain strings for the JSON contract.
KILLING = "killing"
KILL_NO_SUPERVISOR = "supervisor-not-running"
KILL_CLOSED = "closed"
KILL_NOOP = "no-op"

#: Statuses a close() call can finish (queue-side kill of a waiting task).
_CLOSEABLE = frozenset({"open", "ready", "blocked"})


class TaskNotFound(Exception):
    """Raised when *task_id* has no task.json; handlers map it to 404."""

    def __init__(self, task_id: str) -> None:
        super().__init__(f"task not found: {task_id}")
        self.task_id = task_id


class TaskQueue(Protocol):
    """Structural queue surface this module needs (beads satisfies it)."""

    def release(self, task_id: str, reason: str = "", wait_sec: int = 0) -> None:
        """Release a task back to the queue with *reason*."""
        ...

    def close(self, task_id: str, reason: str = "completed") -> None:
        """Close a task with *reason*."""
        ...


def _require_task_dir(fleet_home: Path, task_id: str) -> Path:
    task_dir = task_dir_for(fleet_home, task_id)
    if TaskMeta.load(task_dir) is None:
        raise TaskNotFound(task_id)
    return task_dir


def unblock(fleet_home: Path, queue: TaskQueue, task_id: str, note: str | None = None) -> None:
    """Release a blocked task and clear its retry state; journal the note."""
    task_dir = _require_task_dir(fleet_home, task_id)
    reason = UNBLOCK_REASON if not note else f"{UNBLOCK_REASON}: {note}"
    queue.release(task_id, reason)
    TaskMeta.clear(task_dir, "retry_after")
    clear_needs_validation(task_dir)
    record_unblock(task_dir, note)


def kill(
    fleet_home: Path,
    queue: TaskQueue,
    task_id: str,
    *,
    status: str,
    supervisor_running: bool,
) -> str:
    """Stop or close *task_id*; returns one of the KILL_* outcome strings."""
    task_dir = _require_task_dir(fleet_home, task_id)
    if status == TaskStatus.IN_PROGRESS.value:
        (task_dir / KILL_MARKER).touch()
        return KILLING if supervisor_running else KILL_NO_SUPERVISOR
    if status in _CLOSEABLE:
        queue.close(task_id, "killed")
        return KILL_CLOSED
    return KILL_NOOP


def remove_assignee(
    fleet_home: Path, task_id: str, *, clear_assignee: Callable[[str], None]
) -> None:
    """Clear the beads assignee and the task.json coder mirror."""
    task_dir = _require_task_dir(fleet_home, task_id)
    clear_assignee(task_id)
    TaskMeta.update(task_dir, coder=None)
