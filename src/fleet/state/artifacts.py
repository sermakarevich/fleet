"""Read a task's artifacts (PLAN/HANDOFF/KNOWLEDGE + latest attempt's SUMMARY/RESULT)
into the pure `core.launch.ArtifactSnapshot` that `core.launch.plan_launch` consumes.

This is the only I/O side of launch planning; `core/launch.py` stays pure.
"""

from __future__ import annotations

import json
from pathlib import Path

from fleet.core.launch import ArtifactSnapshot
from fleet.state.attempts import latest_attempt_dir

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_STUB_NAMES = {
    "HANDOFF.md": "HANDOFF.md.tmpl",
    "KNOWLEDGE.md": "KNOWLEDGE.md.tmpl",
    "PLAN.md": "PLAN.md.tmpl",
}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _is_stub(content: str, name: str, task_id: str) -> bool:
    """True when *content* is missing, whitespace-only, or matches the seeded stub."""
    if not content.strip():
        return True
    tmpl_path = _TEMPLATES_DIR / _STUB_NAMES[name]
    try:
        stub = tmpl_path.read_text(encoding="utf-8").format(task_id=task_id)
    except OSError:
        return False
    return content.strip() == stub.strip()


def _read_artifact(artifacts_dir: Path, name: str, task_id: str) -> tuple[str, bool]:
    content = _read_text(artifacts_dir / name)
    return content, _is_stub(content, name, task_id)


def read_artifacts(
    task_dir: Path, task_id: str, before_n: int | None = None
) -> ArtifactSnapshot:
    """Build the `ArtifactSnapshot` for planning the next attempt.

    *before_n*, when given, is the attempt number about to be planned; the
    "latest attempt" consulted for SUMMARY.md/RESULT.json is the highest
    completed attempt strictly before it (see `state.attempts.latest_attempt_dir`).
    """
    artifacts_dir = task_dir / "artifacts"
    handoff_text, handoff_is_stub = _read_artifact(artifacts_dir, "HANDOFF.md", task_id)
    knowledge_text, knowledge_is_stub = _read_artifact(artifacts_dir, "KNOWLEDGE.md", task_id)
    plan_text, plan_is_stub = _read_artifact(artifacts_dir, "PLAN.md", task_id)

    prev_dir = latest_attempt_dir(task_dir, before_n=before_n)

    latest_summary_text: str | None = None
    latest_result: dict | None = None
    latest_result_is_missing = False

    if prev_dir is not None:
        summary_path = prev_dir / "SUMMARY.md"
        if summary_path.exists():
            latest_summary_text = _read_text(summary_path)

        result_path = prev_dir / "RESULT.json"
        latest_result_is_missing = True
        if result_path.exists():
            try:
                parsed = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    latest_result = parsed
                    latest_result_is_missing = False
            except (OSError, ValueError):
                latest_result = None

    return ArtifactSnapshot(
        handoff_text=handoff_text,
        handoff_is_stub=handoff_is_stub,
        knowledge_text=knowledge_text,
        knowledge_is_stub=knowledge_is_stub,
        plan_text=plan_text,
        plan_is_stub=plan_is_stub,
        latest_summary_text=latest_summary_text,
        latest_result=latest_result,
        latest_result_is_missing=latest_result_is_missing,
    )
