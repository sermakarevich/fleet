"""The job worker's phase snapshot. Pure: no I/O.

``JobSnapshot`` is everything ``core/job_phase.phase()`` needs to pick one
of research/design/gate/spawn/observe. Callers do the file reads (three
``artifacts/`` existence checks plus the child list) and build this type;
there is exactly one such type, owned here. Readers are ``workers/job.py``
(``_snapshot_for``) and ``cli/tasks.py`` (``job`` command) — both import
from this module, so there is no second parser and no second definition.
The snapshot is in-memory only; it is never written under ``~/.fleet``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JobSnapshot:
    """Presence flags one phase decision needs.

    - *has_research*: artifacts/RESEARCH.md exists.
    - *has_tasks*: artifacts/tasks.json exists.
    - *gate_enabled*: cfg.job_gate and bead metadata fleet_job_gate != "off".
    - *approved*: artifacts/APPROVED exists.
    - *has_children*: the epic already has child beads.
    """

    has_research: bool = False
    has_tasks: bool = False
    gate_enabled: bool = True
    approved: bool = False
    has_children: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Render to plain booleans for logging or debugging."""
        return {
            "has_research": self.has_research,
            "has_tasks": self.has_tasks,
            "gate_enabled": self.gate_enabled,
            "approved": self.approved,
            "has_children": self.has_children,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobSnapshot:
        """Rebuild from a ``to_dict`` dict; missing keys are False/True defaults."""
        return cls(
            has_research=bool(data.get("has_research", False)),
            has_tasks=bool(data.get("has_tasks", False)),
            gate_enabled=bool(data.get("gate_enabled", True)),
            approved=bool(data.get("approved", False)),
            has_children=bool(data.get("has_children", False)),
        )
