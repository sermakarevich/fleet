"""The one rule for merging bd status into a task's on-disk metadata.

Beads is the authoritative source of truth for task status. A task whose
id is absent from the beads DB is treated as closed (it finished before
the current DB, or the DB was reset). ``created_at`` is never nulled out:
when the bead has no created_at, the task's own value is kept.
Called by serve/api/tasks.py and serve/analytics/summary.py.

The rule itself lives in :mod:`fleet.core.status` (pure, no I/O) so
``state`` can use it without importing ``beads`` (layer rule). This
module re-exports it for backwards compatibility.
"""

from __future__ import annotations

from fleet.core.status import merge_status

__all__ = ["merge_status"]
