"""The owners of ``STATE.md`` and ``RESULT.json``.

:class:`StateFile` is the only writer/reader of the task-level worker-memory
file; :class:`ResultFile` is the only reader of the completion contract
(the coder subprocess writes the live file; reap snapshots it). Filenames
come from :mod:`fleet.state.paths`. Callers are ``workers/task.py``,
``workers/compact.py``, ``orchestrator/reap.py``,
``state/task_summary.py`` and ``cli/tasks.py``. :func:`read_artifacts` is a
thin composition of the two for launch planning. Task dirs written before
ADR 0004 (no STATE.md) are read through the read-only ``state/legacy.py``
fallback; nothing writes the old layout.
"""

from __future__ import annotations

import json
from pathlib import Path

from fleet.core.launch import ArtifactSnapshot
from fleet.state.atomic import write_text_atomic
from fleet.state.attempts import latest_attempt_dir
from fleet.state.legacy import legacy_result, legacy_state_text
from fleet.state.paths import RESULT_JSON, STATE_MD, outputs_dir

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class StateFile:
    """Reader and writer of the task-level ``STATE.md`` worker memory."""

    @staticmethod
    def path(task_dir: Path) -> Path:
        """The live worker-memory file for *task_dir*."""
        return task_dir / STATE_MD

    @classmethod
    def read(cls, task_dir: Path) -> str:
        """Live STATE.md text, or "" when missing or unreadable."""
        try:
            return cls.path(task_dir).read_text(encoding="utf-8")
        except OSError:
            return ""

    @classmethod
    def write(cls, task_dir: Path, text: str) -> None:
        """Overwrite the live STATE.md through the atomic writer."""
        write_text_atomic(cls.path(task_dir), text)

    @staticmethod
    def stub_text(task_id: str) -> str:
        """Fresh-task STATE.md seeded from the template (never overwrites)."""
        tmpl = (_TEMPLATES_DIR / "STATE.md.tmpl").read_text(encoding="utf-8")
        return tmpl.format(task_id=task_id)

    @classmethod
    def ensure_stub(cls, task_dir: Path, task_id: str) -> None:
        """Seed the STATE.md stub and outputs/ when missing; never overwrite."""
        task_dir.mkdir(parents=True, exist_ok=True)
        outputs_dir(task_dir).mkdir(parents=True, exist_ok=True)
        target = cls.path(task_dir)
        if not target.exists():
            cls.write(task_dir, cls.stub_text(task_id))

    @staticmethod
    def is_stub(content: str, task_id: str) -> bool:
        """True when *content* is missing, blank, or matches the seeded stub."""
        if not content.strip():
            return True
        try:
            stub = (
                (_TEMPLATES_DIR / "STATE.md.tmpl")
                .read_text(encoding="utf-8")
                .format(task_id=task_id)
            )
        except OSError:
            return False
        return content.strip() == stub.strip()

    @classmethod
    def snapshot(cls, task_dir: Path, attempt_dir: Path) -> bool:
        """Copy live STATE.md into *attempt_dir*; False when nothing to copy."""
        src = cls.path(task_dir)
        if not src.exists():
            return False
        attempt_dir.mkdir(parents=True, exist_ok=True)
        write_text_atomic(attempt_dir / STATE_MD, src.read_text(encoding="utf-8"))
        return True


class ResultFile:
    """Reader of the ``RESULT.json`` completion contract plus its snapshots."""

    @staticmethod
    def path(task_dir: Path) -> Path:
        """The live completion contract for *task_dir*."""
        return task_dir / RESULT_JSON

    @staticmethod
    def snapshot_path(attempt_dir: Path) -> Path:
        """The reaped RESULT.json snapshot inside one attempt dir."""
        return attempt_dir / RESULT_JSON

    @classmethod
    def read(cls, task_dir: Path) -> dict | None:
        """Parsed live RESULT.json, or None when missing or unparseable."""
        try:
            parsed = json.loads(cls.path(task_dir).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @classmethod
    def snapshot_from(cls, prev_dir: Path | None) -> tuple[dict | None, bool]:
        """Latest RESULT snapshot from the previous attempt dir.

        Returns (result, is_missing): *is_missing* is False when there is no
        previous attempt at all, True when one exists but holds no parseable
        RESULT.json.
        """
        if prev_dir is None:
            return None, False
        result_path = cls.snapshot_path(prev_dir)
        if not result_path.exists():
            return None, True
        try:
            parsed = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, True
        if isinstance(parsed, dict):
            return parsed, False
        return None, True

    @classmethod
    def snapshot(cls, task_dir: Path, attempt_dir: Path) -> bool:
        """Move live RESULT.json into *attempt_dir*; False when nothing to move."""
        src = cls.path(task_dir)
        if not src.exists():
            return False
        attempt_dir.mkdir(parents=True, exist_ok=True)
        write_text_atomic(cls.snapshot_path(attempt_dir), src.read_text(encoding="utf-8"))
        src.unlink(missing_ok=True)
        return True


def read_artifacts(task_dir: Path, task_id: str, before_n: int | None = None) -> ArtifactSnapshot:
    """Build the `ArtifactSnapshot` for planning the next attempt.

    *before_n*, when given, is the attempt number about to be planned; the
    "latest attempt" consulted for RESULT.json is the highest completed
    attempt strictly before it (see `state.attempts.latest_attempt_dir`).
    """
    state_path = StateFile.path(task_dir)
    state_text = StateFile.read(task_dir)
    if state_path.exists():
        state_is_stub = StateFile.is_stub(state_text, task_id)
    else:
        legacy = legacy_state_text(task_dir)
        if legacy is not None:
            state_text, state_is_stub = legacy, False
        else:
            state_text, state_is_stub = "", True

    prev_dir = latest_attempt_dir(task_dir, before_n=before_n)
    latest_result, latest_result_is_missing = ResultFile.snapshot_from(prev_dir)
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
