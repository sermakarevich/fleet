"""Read-only fallback for pre-STATE.md (ADR 0004) task directories.

Old task dirs keep worker memory in ``artifacts/{PLAN,HANDOFF,KNOWLEDGE}.md``
and the declared outcome in ``artifacts/RESULT.json``. Nothing ever writes
this layout anymore (see ``workers/task.py::_ensure_state``); these helpers
only let ``state/artifacts.py`` (launch planning) and
``state/task_summary.py`` (UI) read old dirs. There is no migration command.
"""

from __future__ import annotations

import json
from pathlib import Path

_LEGACY_DIR = "artifacts"
_LEGACY_PLAN = "PLAN.md"
_LEGACY_HANDOFF = "HANDOFF.md"
_LEGACY_KNOWLEDGE = "KNOWLEDGE.md"
_LEGACY_RESULT = "RESULT.json"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def legacy_state_text(task_dir: Path) -> str | None:
    """Render old PLAN/HANDOFF/KNOWLEDGE.md as STATE.md text, or None.

    Returns None when none of the three legacy files exists (or all are
    blank). Otherwise maps them onto the five STATE headings: Plan from
    PLAN.md, the whole HANDOFF.md verbatim under Done (In flight/Next point
    at it), Facts from KNOWLEDGE.md.
    """
    legacy = task_dir / _LEGACY_DIR
    plan = _read(legacy / _LEGACY_PLAN).strip()
    handoff = _read(legacy / _LEGACY_HANDOFF).strip()
    knowledge = _read(legacy / _LEGACY_KNOWLEDGE).strip()
    if not plan and not handoff and not knowledge:
        return None
    task_id = task_dir.name
    return (
        f"# {task_id} — STATE (legacy view)\n"
        "\n"
        "> Rendered from the pre-STATE.md artifacts/ layout; nothing writes this.\n"
        "\n"
        "## Plan\n"
        f"{plan or '(none recorded)'}\n"
        "\n"
        "## Done\n"
        f"{handoff or '(none recorded)'}\n"
        "\n"
        "## In flight\n"
        "(none recorded separately — see Done)\n"
        "\n"
        "## Next\n"
        "(none recorded separately — see Done)\n"
        "\n"
        "## Facts\n"
        f"{knowledge or '(none recorded)'}\n"
    )


def legacy_result(task_dir: Path) -> dict | None:
    """Parse the old ``artifacts/RESULT.json``, or None when missing/invalid."""
    try:
        text = (task_dir / _LEGACY_DIR / _LEGACY_RESULT).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def attempt_state_snapshot(attempt_dir: Path) -> Path | None:
    """The attempt's worker-memory snapshot: STATE.md, else the pre-STATE.md
    snapshot file under its old name, else None."""
    state = attempt_dir / "STATE.md"
    if state.exists():
        return state
    old = attempt_dir / _LEGACY_HANDOFF
    return old if old.exists() else None
