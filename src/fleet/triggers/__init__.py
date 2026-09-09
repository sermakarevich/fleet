"""Event triggers: open a task when a watched signal fires (ADR 0011).

A Source polls for events that are true right now, a Trigger is a saved
definition saying which source to watch and what task to open, and a Firing
is one trigger reacting to one event by opening one bead.
"""

from __future__ import annotations

from fleet.triggers.model import Firing, Trigger, TriggerEvent, new_id
from fleet.triggers.store import TriggerStore

__all__ = [
    "Firing",
    "Trigger",
    "TriggerEvent",
    "TriggerStore",
    "new_id",
]
