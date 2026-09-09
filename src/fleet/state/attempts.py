"""Thin call sites over :mod:`fleet.state.attempt_journal`.

This module keeps the historic function names so existing callers
(``orchestrator/spawn.py``, ``orchestrator/reap.py``,
``orchestrator/leases.py``, workers, serve, tests) keep working; every
function loads one :class:`AttemptJournal` and delegates. No parsing lives
here — the journal is read exactly once per call, inside the owner.
"""

from __future__ import annotations

from pathlib import Path

from fleet.core.retry_policy import Action
from fleet.core.task import AttemptKind, TaskOutcome
from fleet.state.attempt_journal import AttemptJournal
from fleet.state.paths import attempt_dir_path


def current_attempt_n(task_dir: Path) -> int:
    """Highest start N seen so far, or 0 if none."""
    return AttemptJournal.load(task_dir).current_n


def attempt_dir(task_dir: Path, n: int) -> Path:
    """The on-disk directory for attempt *n* of this task."""
    return attempt_dir_path(task_dir, n)


def latest_attempt_dir(task_dir: Path, before_n: int | None = None) -> Path | None:
    """Dir of the most recent attempt (below *before_n* when given)."""
    return AttemptJournal.load(task_dir).latest_attempt_dir(before_n=before_n)


def record_start(
    task_dir: Path,
    *,
    coder: str | None,
    model: str | None,
    worker: str | None = None,
    kind: AttemptKind | str = AttemptKind.WORK,
) -> int:
    """Append a start line and return its attempt number."""
    return AttemptJournal.load(task_dir).append_start(
        coder=coder, model=model, worker=worker, kind=kind
    )


def record_end(
    task_dir: Path,
    *,
    outcome: TaskOutcome | str,
    exit_code: int | None,
    reason: str,
    action: Action | str,
    n: int | None = None,
) -> None:
    """Append an end line for attempt *n* (default: the current one)."""
    outcome_value = outcome.value if isinstance(outcome, TaskOutcome) else outcome
    AttemptJournal.load(task_dir).append_end(
        outcome=outcome_value, exit_code=exit_code, reason=reason, action=action, n=n
    )


def set_worker(task_dir: Path, n: int, worker: str) -> bool:
    """Tag attempt *n*'s start line with its worker name; False when no tag landed."""
    return AttemptJournal.load(task_dir).set_worker(n, worker)


def record_unblock(task_dir: Path, note: str | None = None) -> int:
    """Append an operator-unblock row and return its attempt number."""
    return AttemptJournal.load(task_dir).append_unblock(note)


def load_attempts(task_dir: Path) -> list[dict]:
    """Merged per-attempt dicts sorted by n."""
    return AttemptJournal.load(task_dir).rows


def restart_count(task_dir: Path) -> int:
    """Number of starts minus 1, minimum 0."""
    return AttemptJournal.load(task_dir).restart_count


def last_attempt(task_dir: Path) -> dict | None:
    """Last element of load_attempts or None."""
    return AttemptJournal.load(task_dir).last
