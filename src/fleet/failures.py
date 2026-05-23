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
