"""The .needs_validation marker: set when an isolated task needs a merge check."""

from __future__ import annotations

from pathlib import Path

from fleet.state.atomic import write_text_atomic


def _needs_validation_path(task_dir: Path) -> Path:
    return task_dir / ".needs_validation"


def set_needs_validation(task_dir: Path) -> None:
    write_text_atomic(_needs_validation_path(task_dir), "1")


def needs_validation(task_dir: Path) -> bool:
    return _needs_validation_path(task_dir).exists()


def clear_needs_validation(task_dir: Path) -> None:
    _needs_validation_path(task_dir).unlink(missing_ok=True)
