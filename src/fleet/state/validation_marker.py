"""The .needs_validation marker: set when an isolated task needs a merge check."""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

from fleet.state.atomic import write_text_atomic

#: Per-task merge-validation lock: held (O_EXCL file) for one validate_one
#: run so two supervisors never merge the same marker concurrently.
#: A lock older than this is a crashed validator's leftover and may be
#: cleared; a fresher lock means another validator is inside validate_one.
VALIDATING_STALE_SEC: float = 600.0

_VALIDATING_NAME = ".validating"


def _needs_validation_path(task_dir: Path) -> Path:
    return task_dir / ".needs_validation"


def validation_lock_path(task_dir: Path) -> Path:
    """Path of the exclusivity lock for one task's merge validation."""
    return task_dir / _VALIDATING_NAME


def try_acquire_validation_lock(task_dir: Path) -> int | None:
    """Create the lock file exclusively; fd when won, None when held elsewhere.

    A stale lock (older than VALIDATING_STALE_SEC, left by a crashed
    validator that never reached release) is cleared and retried once.
    """
    try:
        return os.open(validation_lock_path(task_dir), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        pass
    except OSError:
        return None
    if not _validation_lock_is_stale(task_dir):
        return None
    with contextlib.suppress(OSError):
        validation_lock_path(task_dir).unlink()
    try:
        return os.open(validation_lock_path(task_dir), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return None


def _validation_lock_is_stale(task_dir: Path) -> bool:
    """True when the lock predates any validation that could still run."""
    try:
        age = time.time() - validation_lock_path(task_dir).stat().st_mtime
    except OSError:
        return False
    return age > VALIDATING_STALE_SEC


def release_validation_lock(fd: int | None, task_dir: Path) -> None:
    """Close and remove a lock acquired by try_acquire_validation_lock."""
    if fd is None:
        return
    with contextlib.suppress(OSError):
        os.close(fd)
    with contextlib.suppress(OSError):
        validation_lock_path(task_dir).unlink()


def set_needs_validation(task_dir: Path) -> None:
    write_text_atomic(_needs_validation_path(task_dir), "1")


def needs_validation(task_dir: Path) -> bool:
    return _needs_validation_path(task_dir).exists()


def clear_needs_validation(task_dir: Path) -> None:
    _needs_validation_path(task_dir).unlink(missing_ok=True)
