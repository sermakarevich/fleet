"""The one fleet_home for task artifact paths.

Called by ``cli/tasks.py`` (task/tail/log reads) and
``serve/api/tasks_artifacts.py``. Attempt-scoped artifacts resolve through
:mod:`fleet.state.attempt_journal` (never a hardcoded ``attempts/1``):
an explicit attempt wins, otherwise the latest started attempt, otherwise
the next slot (``max_n + 1``, which is 1 when the journal is empty) so
``--follow`` has a path to wait on. ``locate`` never raises for a missing
file — callers decide between "not yet" and "not found".
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fleet.state.attempt_journal import AttemptJournal
from fleet.state.paths import RESULT_JSON, STATE_MD, attempt_dir
from fleet.state.paths import task_dir as _task_dir

ArtifactKind = Literal["log", "state", "result", "events", "stderr", "prompt"]

_ATTEMPT_FILES: dict[str, str] = {
    "log": "log.jsonl",
    "events": "events.jsonl",
    "stderr": "log.stderr",
    "prompt": "prompt.md",
}

_TASK_FILES: dict[str, str] = {
    "state": STATE_MD,
}


def _attempt_n(task_dir: Path, attempt: int | None) -> int:
    """Explicit attempt, else the latest start, else the next journal slot."""
    if attempt is not None:
        return attempt
    journal = AttemptJournal.load(task_dir)
    if journal.current_n:
        return journal.current_n
    return journal.max_n + 1


def _locate_result(task_dir: Path) -> Path:
    """Live RESULT.json, else the latest attempt snapshot, else the legacy path."""
    live = task_dir / RESULT_JSON
    if live.exists():
        return live
    journal = AttemptJournal.load(task_dir)
    if journal.current_n:
        snapshot = attempt_dir(task_dir, journal.current_n) / RESULT_JSON
        if snapshot.exists():
            return snapshot
    return task_dir / "artifacts" / RESULT_JSON


def locate(fleet_home: Path, task_id: str, what: ArtifactKind, attempt: int | None = None) -> Path:
    """Filesystem path of one task artifact (may not exist yet)."""
    task_dir = _task_dir(fleet_home, task_id)
    if what in _ATTEMPT_FILES:
        return attempt_dir(task_dir, _attempt_n(task_dir, attempt)) / _ATTEMPT_FILES[what]
    if what in _TASK_FILES:
        return task_dir / _TASK_FILES[what]
    return _locate_result(task_dir)
