from pathlib import Path


def _counter_path(task_dir: Path) -> Path:
    return task_dir / ".failures"


def failure_count(task_dir: Path) -> int:
    """Return the number of FAILURE outcomes recorded for this task."""
    path = _counter_path(task_dir)
    if not path.exists():
        return 0
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return 0


def increment_failure(task_dir: Path) -> int:
    """Increment the failure counter for this task and return the new count."""
    task_dir.mkdir(parents=True, exist_ok=True)
    new_count = failure_count(task_dir) + 1
    _counter_path(task_dir).write_text(str(new_count))
    return new_count


# ---- .noclose counter helpers ----


def _noclose_path(task_dir: Path) -> Path:
    return task_dir / ".noclose"


def noclose_count(task_dir: Path) -> int:
    """Return the number of no-close (rc=0 without terminal close) outcomes for this task."""
    path = _noclose_path(task_dir)
    if not path.exists():
        return 0
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return 0


def increment_noclose(task_dir: Path) -> int:
    """Increment the no-close counter for this task and return the new count."""
    task_dir.mkdir(parents=True, exist_ok=True)
    new_count = noclose_count(task_dir) + 1
    _noclose_path(task_dir).write_text(str(new_count))
    return new_count


def reset_noclose(task_dir: Path) -> None:
    """Remove the no-close counter file so a later reopen starts fresh."""
    _noclose_path(task_dir).unlink(missing_ok=True)


def reset_failure(task_dir: Path) -> None:
    """Remove the failure counter file so a later reopen starts fresh."""
    _counter_path(task_dir).unlink(missing_ok=True)


# ---- .needs_validation marker helpers ----


def _needs_validation_path(task_dir: Path) -> Path:
    return task_dir / ".needs_validation"


def set_needs_validation(task_dir: Path) -> None:
    _needs_validation_path(task_dir).write_text("1")


def needs_validation(task_dir: Path) -> bool:
    return _needs_validation_path(task_dir).exists()


def clear_needs_validation(task_dir: Path) -> None:
    _needs_validation_path(task_dir).unlink(missing_ok=True)
