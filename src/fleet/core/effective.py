"""Effective coder/model resolution: the one rule for what a task runs with.

Pure function, no I/O: a task's own coder/model override wins, otherwise the
configured defaults apply. Called by ``orchestrator/spawn.py``
(``resolve_coder``), ``cli/tasks.py`` and ``cli/render.py`` (the tasks table,
``show``, and the ``task --help`` epilog), and
``serve/api/task_summary.py`` (context-limit lookup for task summaries).
"""

from __future__ import annotations

from typing import overload


@overload
def effective_coder_model(
    task_coder: str | None,
    task_model: str | None,
    default_coder: str,
    default_model: str,
) -> tuple[str, str]: ...


@overload
def effective_coder_model(
    task_coder: str | None,
    task_model: str | None,
    default_coder: str | None = None,
    default_model: str | None = None,
) -> tuple[str | None, str | None]: ...


def effective_coder_model(
    task_coder: str | None,
    task_model: str | None,
    default_coder: str | None = None,
    default_model: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve (coder, model) for a task from its overrides and the defaults."""
    return (task_coder or default_coder, task_model or default_model)
