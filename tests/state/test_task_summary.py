from __future__ import annotations

import json
from pathlib import Path

from fleet.state.task_summary import build_task_summary


def _task_dir(tmp_path: Path, task_id: str = "t-001") -> Path:
    task_dir = tmp_path / "tasks" / task_id
    (task_dir / "artifacts").mkdir(parents=True)
    return task_dir


def _data(task_id: str = "t-001") -> dict:
    return {"id": task_id, "title": "T", "description": None, "status": "in_progress"}


def test_result_is_none_when_no_result_json(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert summary["result"] is None


def test_result_parses_result_json(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    (task_dir / "artifacts" / "RESULT.json").write_text(
        json.dumps({"schema": 1, "status": "done", "summary": "shipped"})
    )
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert summary["result"]["status"] == "done"
    assert summary["result"]["summary"] == "shipped"


def test_result_is_none_when_result_json_invalid(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    (task_dir / "artifacts" / "RESULT.json").write_text("not json")
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert summary["result"] is None


def test_handoff_excerpt_is_none_when_missing(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert summary["handoff_excerpt"] is None


def test_handoff_excerpt_reads_handoff_md(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    (task_dir / "artifacts" / "HANDOFF.md").write_text("## Next\ndo the thing")
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert summary["handoff_excerpt"] == "## Next\ndo the thing"


def test_handoff_excerpt_truncated_to_cap(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    (task_dir / "artifacts" / "HANDOFF.md").write_text("x" * 3000)
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert len(summary["handoff_excerpt"]) == 2048
