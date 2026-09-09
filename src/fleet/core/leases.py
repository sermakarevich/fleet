"""Pure lease policy: values in, verdict out, no disk, no processes.

Called by ``orchestrator/leases.py``, which reads run.json + the attempts
journal and acts on the verdict. ``LeaseVerdict`` names the four outcomes;
``classify_lease`` picks one from plain values (never a ``RunRecord``, so
this core module imports nothing from ``state``); ``orphan_dirs`` picks
dead worktree dirs from a directory listing plus the live set.
"""

from __future__ import annotations

from enum import Enum


class LeaseVerdict(Enum):
    """What a claim lease means: keep it, watch it, or take it back."""

    LIVE = "live"
    STALE_PID_ALIVE = "stale_pid_alive"
    RECLAIM = "reclaim"
    NOT_OURS = "not_ours"


def classify_lease(
    *,
    has_attempt_dir: bool,
    has_run: bool,
    lease_stale: bool,
    pid_valid: bool,
    pid_dead: bool,
    attempt_ended: bool,
) -> LeaseVerdict:
    """Pick the verdict for one lease from pre-read facts.

    No attempt dir (human-claimed bead) or no run.json / no heartbeat
    means NOT_OURS: without heartbeat keys nothing can be proven. A fresh
    lease is LIVE. A stale lease on a live pid is STALE_PID_ALIVE (warn
    only, never kill). A stale lease on a dead pid reclaims — unless the
    attempt already journaled its end, in which case the queue path owns
    the bead and there is nothing to take back.
    """
    if not has_attempt_dir or not has_run or not lease_stale:
        if not has_attempt_dir or not has_run:
            return LeaseVerdict.NOT_OURS
        return LeaseVerdict.LIVE
    if not pid_valid:
        return LeaseVerdict.NOT_OURS
    if not pid_dead:
        return LeaseVerdict.STALE_PID_ALIVE
    if attempt_ended:
        return LeaseVerdict.NOT_OURS
    return LeaseVerdict.RECLAIM


def is_orphan_dir(name: str, resolved: str, live_paths: set[str], live_ids: set[str]) -> bool:
    """True when one worktree dir has no live task behind it.

    Live means: its resolved path is still referenced by a task.json
    ``worktree_path``, its name is a live task id, or it is a
    ``<repo>-<task_id>`` dir whose task suffix is live.
    """
    if resolved in live_paths or name in live_ids:
        return False
    return not any(name == tid or name.endswith(f"-{tid}") for tid in live_ids)


def orphan_dirs(
    resolved_dirs: list[tuple[str, str]], live_paths: set[str], live_ids: set[str]
) -> list[str]:
    """Names of worktree dirs with no live task behind them.

    *resolved_dirs* is ``(name, resolved_path)`` pairs (the caller
    resolves); *live_paths* the resolved ``worktree_path`` values still
    referenced by task.json files; *live_ids* live task ids (in flight
    or awaiting validation).
    """
    return [
        name
        for name, resolved in resolved_dirs
        if is_orphan_dir(name, resolved, live_paths, live_ids)
    ]
