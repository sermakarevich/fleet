"""Read a task's STATE.md + previous attempt's RESULT.json into the pure
`core.launch.ArtifactSnapshot` that `core.launch.plan_launch` consumes.

This is the only I/O side of launch planning; `core/launch.py` stays pure.
Task dirs written before ADR 0004 (no STATE.md) are read through the
read-only `state/legacy.py` fallback; nothing writes the old layout.
"""

from __future__ import annotations

import json
from pathlib import Path

from fleet.core.launch import ArtifactSnapshot
from fleet.state.attempts import latest_attempt_dir
from fleet.state.legacy import legacy_result, legacy_state_text
from fleet.state.paths import RESULT_JSON, STATE_MD

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _is_stub(content: str, task_id: str) -> bool:
    """True when *content* is missing, whitespace-only, or matches the seeded stub."""
    if not content.strip():
        return True
    try:
        stub = (
            (_TEMPLATES_DIR / "STATE.md.tmpl").read_text(encoding="utf-8").format(task_id=task_id)
        )
    except OSError:
        return False
    return content.strip() == stub.strip()


def _read_result_snapshot(prev_dir: Path | None) -> tuple[dict | None, bool]:
    """Return (latest_result, is_missing) for the previous attempt dir.

    *is_missing* is False when there is no previous attempt at all; True
    when a previous attempt exists but holds no parseable RESULT.json.
    """
    if prev_dir is None:
        return None, False
    result_path = prev_dir / RESULT_JSON
    if not result_path.exists():
        return None, True
    try:
        parsed = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, True
    if isinstance(parsed, dict):
        return parsed, False
    return None, True


def read_artifacts(task_dir: Path, task_id: str, before_n: int | None = None) -> ArtifactSnapshot:
    """Build the `ArtifactSnapshot` for planning the next attempt.

    *before_n*, when given, is the attempt number about to be planned; the
    "latest attempt" consulted for RESULT.json is the highest completed
    attempt strictly before it (see `state.attempts.latest_attempt_dir`).
    """
    state_path = task_dir / STATE_MD
    state_text = _read_text(state_path)
    if state_path.exists():
        state_is_stub = _is_stub(state_text, task_id)
    else:
        legacy = legacy_state_text(task_dir)
        if legacy is not None:
            state_text, state_is_stub = legacy, False
        else:
            state_text, state_is_stub = "", True

    prev_dir = latest_attempt_dir(task_dir, before_n=before_n)
    latest_result, latest_result_is_missing = _read_result_snapshot(prev_dir)
    if latest_result is None and prev_dir is None:
        # No attempt snapshots at all (e.g. an old dir whose only record is
        # the live file): fall back to the legacy read, which yields None
        # for new-layout dirs.
        legacy_result_data = legacy_result(task_dir)
        if legacy_result_data is not None:
            latest_result = legacy_result_data

    return ArtifactSnapshot(
        state_text=state_text,
        state_is_stub=state_is_stub,
        latest_result=latest_result,
        latest_result_is_missing=latest_result_is_missing,
    )
