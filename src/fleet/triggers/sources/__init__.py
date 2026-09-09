"""Registry of event-source kinds: every `Source` lives in exactly one table.

`SOURCES` maps a source kind (for example `blocked_task`) to its
`EventSource` implementation. `source_for` builds one by kind. Follow-up
beads add rows; call sites never hand-pick a source class.
"""

from __future__ import annotations

from fleet.core.errors import FleetError
from fleet.triggers.sources.base import EventSource
from fleet.triggers.sources.blocked_task import BlockedTaskSource


class UnknownSource(FleetError, KeyError):
    """No event source with this kind in the `SOURCES` registry."""

    def __init__(self, kind: str) -> None:
        """Remember the unknown source kind."""
        super().__init__(kind)
        self.kind = kind


SOURCES: dict[str, type[EventSource]] = {BlockedTaskSource.kind: BlockedTaskSource}


def source_params(kind: str) -> dict[str, str]:
    """Help text per source param name ({} when the class defines none)."""
    cls = SOURCES.get(kind)
    if cls is None:
        return {}
    return dict(getattr(cls, "PARAMS", {}))


def source_for(kind: str) -> EventSource:
    """Build the event source for a kind, or raise `UnknownSource`."""
    try:
        factory = SOURCES[kind]
    except KeyError:
        raise UnknownSource(kind) from None
    return factory()
