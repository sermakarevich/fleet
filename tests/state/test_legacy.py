"""Tests for `state.legacy`: the read-only fallback for pre-STATE.md dirs.

Nothing ever writes the old layout — these tests only read it.
"""

from __future__ import annotations

from pathlib import Path

from fleet.state.legacy import (
    attempt_state_snapshot,
    legacy_result,
    legacy_state_text,
)
from tests.helpers.task_dir import make_task_dir


def _seed_legacy(task_dir: Path) -> None:
    artifacts = task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "PLAN.md").write_text("# plan\n- step one\n", encoding="utf-8")
    (artifacts / "HANDOFF.md").write_text("## Done\n- did a\n", encoding="utf-8")
    (artifacts / "KNOWLEDGE.md").write_text("## Facts\n- durable fact\n", encoding="utf-8")


def test_no_legacy_files_returns_none(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-1")
    assert legacy_state_text(task_dir) is None
    assert legacy_result(task_dir) is None


def test_state_text_maps_files_onto_five_headings(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-2")
    _seed_legacy(task_dir)

    text = legacy_state_text(task_dir)

    assert text is not None
    for heading in ("## Plan", "## Done", "## In flight", "## Next", "## Facts"):
        assert heading in text
    assert "step one" in text  # Plan <- PLAN.md
    assert "did a" in text  # Done <- HANDOFF.md verbatim
    assert "durable fact" in text  # Facts <- KNOWLEDGE.md


def test_state_text_needs_only_one_file(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-3")
    artifacts = task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "KNOWLEDGE.md").write_text("just a fact\n", encoding="utf-8")

    text = legacy_state_text(task_dir)

    assert text is not None
    assert "just a fact" in text


def test_legacy_result_reads_old_layout(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-4")
    _seed_legacy(task_dir)
    (task_dir / "artifacts" / "RESULT.json").write_text(
        '{"schema": 1, "status": "done", "summary": "all good"}', encoding="utf-8"
    )

    assert legacy_result(task_dir) == {
        "schema": 1,
        "status": "done",
        "summary": "all good",
    }


def test_legacy_result_invalid_is_none(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-5")
    _seed_legacy(task_dir)
    (task_dir / "artifacts" / "RESULT.json").write_text("not json", encoding="utf-8")

    assert legacy_result(task_dir) is None


def test_attempt_state_snapshot_prefers_state_md(tmp_path: Path) -> None:
    from tests.helpers.task_dir import make_attempt

    task_dir = make_task_dir(tmp_path, "t-6")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    (attempt_dir / "STATE.md").write_text("new state\n", encoding="utf-8")
    (attempt_dir / "HANDOFF.md").write_text("old handoff\n", encoding="utf-8")

    assert attempt_state_snapshot(attempt_dir) == attempt_dir / "STATE.md"


def test_attempt_state_snapshot_falls_back_to_old_name(tmp_path: Path) -> None:
    from tests.helpers.task_dir import make_attempt

    task_dir = make_task_dir(tmp_path, "t-7")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    (attempt_dir / "HANDOFF.md").write_text("old handoff\n", encoding="utf-8")

    assert attempt_state_snapshot(attempt_dir) == attempt_dir / "HANDOFF.md"


def test_attempt_state_snapshot_none_when_missing(tmp_path: Path) -> None:
    from tests.helpers.task_dir import make_attempt

    task_dir = make_task_dir(tmp_path, "t-8")
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")

    assert attempt_state_snapshot(attempt_dir) is None
