"""The one rule for merging bd status into a task's on-disk metadata.

Beads is the authoritative source of truth for task status. A task whose
id is absent from the beads DB is treated as closed (it finished before
the current DB, or the DB was reset). ``created_at`` is never nulled out:
when the bead has no created_at, the task's own value is kept.
"""

from __future__ import annotations


def merge_status(task_meta: dict, bead: dict | None) -> dict:
    """Return task_meta with status/title/description/created_at/priority
    reconciled against `bead` (a dict from beads/client.py or beads_info.py,
    or None if the task is missing from an otherwise-available beads DB).
    """
    if bead is None:
        return {**task_meta, "status": "closed"}

    merged = dict(task_meta)
    merged["status"] = bead.get("status") or task_meta.get("status")
    priority = bead.get("priority")
    merged["priority"] = priority if priority is not None else task_meta.get("priority")
    merged["created_at"] = bead.get("created_at") or task_meta.get("created_at")
    for key in ("title", "description"):
        if not merged.get(key) and bead.get(key):
            merged[key] = bead[key]
    return merged
