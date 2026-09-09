"""Pause gate: one owner for "is the supervisor paused right now".

Called by ``orchestrator/claim.py`` and ``orchestrator/scheduler.py`` (both
skip their tick while paused). Two inputs: the rate-limit pause (``paused_until``,
set by Reap, cleared here once it passes) and the ``.pause`` file on disk.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


def is_paused(st: SupervisorState) -> bool:
    """True while the rate-limit pause holds or the .pause file exists."""
    if st.paused_until is not None:
        if st.clock.now() < st.paused_until:
            return True
        st.paused_until = None
    return (st.fleet_home / ".pause").exists()
