"""Typed domain errors: one exception per failure meaning.

Raised by pure policy and store layers (``core/config.py``,
``core/job_plan.py``, ``orchestrator/worktree.py``,
``integrations/ask_human``) and caught by their callers. Every error
subclasses both ``FleetError`` and a builtin (``ValueError``,
``RuntimeError``, ``KeyError``) so legacy ``except`` clauses keep working
while new code catches the typed name.
"""

from __future__ import annotations

from pathlib import Path

#: JSON arriving at a parse boundary: decoded bodies, rows, envelopes.
Json = dict[str, "Json"] | list["Json"] | str | int | float | bool | None
"""Unvalidated JSON value at a parse boundary; validators narrow it."""


class FleetError(Exception):
    """Base for every typed fleet domain error."""


class ConfigError(FleetError, ValueError):
    """Bad runtime configuration value (bad bool, isolation, unknown key)."""


class PlanError(FleetError, ValueError):
    """Bad job/observer plan: follow-up specs, dependency cycles, task docs."""


class WorktreeError(FleetError, RuntimeError):
    """Git worktree operation failed."""


class QuestionNotFound(FleetError, KeyError):
    """No question with this id in the ask_human store."""

    def __init__(self, qid: str, db_path: Path | str | None = None) -> None:
        """Remember the missing id (and db path when known)."""
        super().__init__(qid)
        self.qid = qid
        self.db_path = Path(db_path) if db_path is not None else None


class WorkflowInvalid(FleetError, ValueError):
    """A workflow definition breaks one or more validation rules."""

    def __init__(self, problems: list[str] | str) -> None:
        """Remember every human-readable problem found."""
        items = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(items))
        self.problems = items


class WorkflowNotFound(FleetError, KeyError):
    """No workflow with this id in the workflows store."""

    def __init__(self, workflow_id: str) -> None:
        """Remember the missing workflow id."""
        super().__init__(workflow_id)
        self.workflow_id = workflow_id


class WorkflowNameTaken(FleetError, ValueError):
    """Another workflow already uses this name (names are unique)."""

    def __init__(self, name: str) -> None:
        """Remember the colliding name."""
        super().__init__(name)
        self.name = name


class SubprocessTimeout(FleetError, TimeoutError):
    """A child process outlived its timeout; carries the argv behind it."""

    def __init__(self, argv: list[str], timeout_s: float) -> None:
        """Remember which command hung and how long it was allowed."""
        super().__init__(f"{' '.join(argv)} timed out after {timeout_s}s")
        self.argv = argv
        self.timeout_s = timeout_s
