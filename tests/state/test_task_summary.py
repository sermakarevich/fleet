from __future__ import annotations

import json
from pathlib import Path

from fleet.coders import context_limit_for
from fleet.state.task_summary import (
    build_task_summary,
    context_overrides_for_home,
)
from tests.helpers.task_dir import make_attempt


def _task_dir(tmp_path: Path, task_id: str = "t-001") -> Path:
    task_dir = tmp_path / "tasks" / task_id
    task_dir.mkdir(parents=True)
    return task_dir


def _data(task_id: str = "t-001") -> dict:
    return {"id": task_id, "title": "T", "description": None, "status": "in_progress"}


def test_result_is_none_when_no_result_json(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert summary["result"] is None


def test_result_parses_result_json(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    (task_dir / "RESULT.json").write_text(
        json.dumps({"schema": 1, "status": "done", "summary": "shipped"})
    )
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert summary["result"]["status"] == "done"
    assert summary["result"]["summary"] == "shipped"


def test_result_is_none_when_result_json_invalid(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    (task_dir / "RESULT.json").write_text("not json")
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert summary["result"] is None


def test_result_falls_back_to_attempt_snapshot(tmp_path: Path) -> None:
    """Post-reap the live file is gone; the snapshot still reports."""

    task_dir = _task_dir(tmp_path)
    attempt_dir = make_attempt(task_dir, 1, outcome="done", reason="ok")
    (attempt_dir / "RESULT.json").write_text(
        json.dumps({"schema": 1, "status": "done", "summary": "from snapshot"})
    )
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert summary["result"]["summary"] == "from snapshot"


def test_state_excerpt_is_none_when_missing(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert summary["state_excerpt"] is None


def test_state_excerpt_reads_state_md(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    (task_dir / "STATE.md").write_text("## Next\ndo the thing")
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert summary["state_excerpt"] == "## Next\ndo the thing"


def test_state_excerpt_truncated_to_cap(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    (task_dir / "STATE.md").write_text("x" * 7000)
    summary = build_task_summary(task_dir, _data(), tmp_path)
    assert len(summary["state_excerpt"]) == 6144


def _task_dir_with_usage(tmp_path: Path, input_tokens: int) -> Path:
    task_dir = _task_dir(tmp_path)
    attempt_dir = task_dir / "attempts" / "1"
    attempt_dir.mkdir(parents=True)
    row = {
        "kind": "assistant_text",
        "ts": "2026-01-01T00:00:00+00:00",
        "usage": {"input_tokens": input_tokens},
    }
    (attempt_dir / "events.jsonl").write_text(json.dumps(row) + "\n")
    return task_dir


def test_context_pct_uses_resolved_per_model_window(tmp_path: Path) -> None:
    """142k tokens on muse-spark must be ~13.5%, never 102-110%."""
    task_dir = _task_dir_with_usage(tmp_path, 142_000)
    data = {
        **_data(),
        "coder": "opencode",
        "model": "muse-spark-1.3-contributor",
    }
    summary = _summary(task_dir, data, tmp_path)
    assert summary["context_tokens"] == 142_000
    assert summary["context_limit"] == 1_048_576
    assert summary["context_pct"] == 142_000 / 1_048_576 * 100
    assert summary["context_pct"] < 100


def test_context_pct_local_qwen_uses_65k_window(tmp_path: Path) -> None:
    task_dir = _task_dir_with_usage(tmp_path, 48_750)
    data = {**_data(), "coder": "pi", "model": "qwen3.6:latest"}
    summary = _summary(task_dir, data, tmp_path)
    assert summary["context_limit"] == 65_000
    assert summary["context_pct"] == 48_750 / 65_000 * 100


def test_context_windows_override_from_runtime_toml(tmp_path: Path) -> None:
    (tmp_path / "runtime.toml").write_text(
        'context_windows = "qwen3.6:latest:100000"\n', encoding="utf-8"
    )
    assert context_overrides_for_home(tmp_path) == {"qwen3.6:latest": 100_000}
    task_dir = _task_dir_with_usage(tmp_path, 50_000)
    data = {**_data(), "coder": "pi", "model": "qwen3.6:latest"}
    summary = _summary(task_dir, data, tmp_path)
    assert summary["context_limit"] == 100_000
    assert summary["context_pct"] == 50.0


def test_context_overrides_missing_file_is_empty(tmp_path: Path) -> None:
    assert context_overrides_for_home(tmp_path) == {}


def test_attempt_row_reads_launch_from_run_json(tmp_path: Path) -> None:
    """Attempt rows take kind/mode from run.json["launch"], not launch.json."""

    task_dir = _task_dir(tmp_path)
    attempt_dir = make_attempt(task_dir, 1, outcome="partial", reason="x")
    (attempt_dir / "run.json").write_text(
        json.dumps({"launch": {"mode": "continue", "pack_bytes": 10, "kind": "work"}})
    )
    (attempt_dir / "prompt.md").write_text("the prompt", encoding="utf-8")
    (attempt_dir / "RESULT.json").write_text(
        json.dumps({"schema": 1, "status": "partial", "summary": "wip"})
    )
    summary = build_task_summary(task_dir, _data(), tmp_path)
    (row,) = summary["attempts"]
    assert row["mode"] == "continue"
    assert row["kind"] == "work"
    assert row["has_summary"] is True
    assert row["has_prompt"] is True
    assert row["result"]["summary"] == "wip"


def _summary(task_dir: Path, data: dict, fleet_home: Path) -> dict:
    """Build a summary with the caller-resolved context limit (as serve/cli do)."""
    return build_task_summary(
        task_dir,
        data,
        fleet_home,
        context_limit=context_limit_for(
            data.get("coder"), data.get("model"), context_overrides_for_home(fleet_home)
        ),
    )


def test_blocked_notes_fallback_is_used_when_no_reason(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    data = {**_data(), "status": "blocked"}
    summary = build_task_summary(task_dir, data, tmp_path, blocked_notes="a bead note")
    assert summary["blocked_reason"] == "a bead note"


def test_blocked_without_notes_stays_none(tmp_path: Path) -> None:
    task_dir = _task_dir(tmp_path)
    data = {**_data(), "status": "blocked"}
    summary = build_task_summary(task_dir, data, tmp_path)
    assert summary["blocked_reason"] is None
