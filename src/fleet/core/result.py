"""RESULT.json contract: the worker's machine-readable declaration of outcome.

Pure parsing only — no file I/O here. Callers read the task-level
``RESULT.json`` and pass its text to ``parse_result``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

SCHEMA_VERSION = 1

_VALID_STATUSES = {"done", "partial", "blocked"}


@dataclass
class Result:
    schema: int
    status: str
    summary: str = ""
    commits: list[str] = field(default_factory=list)
    tests: dict | None = None
    open_questions: list[str] = field(default_factory=list)
    next_step: str = ""
    blocked_reason: str = ""
    # Observer-declared follow-up beads (status=partial only):
    # [{title, body, cwd, depends_on}] — validated by core/job_plan.
    followups: list[dict] = field(default_factory=list)


def parse_result(text: str) -> Result | None:
    """Parse RESULT.json content.

    Returns ``None`` when the text is not valid JSON, is not an object, or
    has an unrecognized ``status``. Callers treat ``None`` the same as a
    missing file.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    status = data.get("status")
    if status not in _VALID_STATUSES:
        return None
    commits = data.get("commits") or []
    open_questions = data.get("open_questions") or []
    tests = data.get("tests")
    followups = data.get("followups") or []
    return Result(
        schema=data.get("schema", SCHEMA_VERSION),
        status=status,
        summary=str(data.get("summary") or ""),
        commits=[str(c) for c in commits] if isinstance(commits, list) else [],
        tests=tests if isinstance(tests, dict) else None,
        open_questions=[str(q) for q in open_questions] if isinstance(open_questions, list) else [],
        next_step=str(data.get("next_step") or ""),
        blocked_reason=str(data.get("blocked_reason") or ""),
        followups=list(followups) if isinstance(followups, list) else [],
    )
