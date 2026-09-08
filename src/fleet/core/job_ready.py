"""Epic readiness: is an epic's child set done enough to validate?

Pure: no I/O. The beads layer resolves which beads are the children
(the epic's dependencies — ``bd dep add <epic> <child>`` means the epic
is blocked until the child closes) and hands their statuses here.
"""

from __future__ import annotations

from dataclasses import dataclass

# Children in these beads states are terminal: beads itself only marks an
# issue ready when every dependency is closed, but a child that ends
# `blocked` (waiting on a human) would otherwise leave the epic asleep
# forever, so the observer claims and validates those too.
TERMINAL_CHILD_STATUSES = frozenset({"closed", "blocked"})


@dataclass
class BeadSummary:
    """The only child fields the readiness rule needs."""

    id: str
    status: str


def children_terminal(children: list[BeadSummary]) -> bool:
    """True when every child is `closed` or `blocked` (vacuously true when empty).

    Callers must still require a non-empty child list before claiming:
    an epic with no children is not "ready", it is just childless.
    """
    return all(c.status in TERMINAL_CHILD_STATUSES for c in children)
