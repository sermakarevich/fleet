"""Find the bead a blocked-task trigger opened for one blocked task.

The `blocked_task` source keys its events `"<task_id>@<blocked_at>"` and
`firing.py` records that key with the bead it opened, so one firing lookup
turns a blocked task into its investigation bead. Used by the supervisor's
triage loop to show the operator WHY a task blocked.
"""

from __future__ import annotations

from fleet.triggers.model import Firing
from fleet.triggers.store import TriggerStore

#: Source kind whose events are keyed by blocked task (sources/blocked_task.py).
BLOCKED_TASK_SOURCE = "blocked_task"


def event_key(task_id: str, blocked_at: str | None) -> str:
    """The `blocked_task` event key for one block (must match the source)."""
    return f"{task_id}@{blocked_at or 'unknown'}"


def investigation_task_id(store: TriggerStore, task_id: str, blocked_at: str | None) -> str | None:
    """Bead a blocked_task trigger opened for this block, or None."""
    key = event_key(task_id, blocked_at)
    try:
        triggers = store.list()
    except Exception:
        return None
    for trigger in triggers:
        if trigger.source != BLOCKED_TASK_SOURCE:
            continue
        try:
            firing: Firing | None = store.firing_for_event(trigger.id, key)
        except Exception:
            continue
        if firing is not None and isinstance(firing.task_id, str) and firing.task_id:
            return firing.task_id
    return None
