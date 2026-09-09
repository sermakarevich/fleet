"""Event-source contract: what a watched signal looks like to the tick loop.

An `EventSource` is stateless: each `poll` returns the events that are true
right now. The tick loop (`fire_due`, a follow-up bead) calls `poll` for
every enabled trigger and decides what to open.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Protocol

from fleet.beads.queue import Queue
from fleet.triggers.model import TriggerEvent


@dataclass(frozen=True, slots=True)
class SourceContext:
    """Everything a source may read while polling for events."""

    fleet_home: Path
    queue: Queue
    now: datetime
    params: dict[str, str] = field(default_factory=dict)


class EventSource(Protocol):
    """One kind of event fleet can watch; implementations live one per file."""

    kind: ClassVar[str]

    def poll(self, ctx: SourceContext) -> list[TriggerEvent]:
        """Return the events that are true right now."""
        ...
