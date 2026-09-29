"""Tests for GET /api/tasks/{id}/activity (ADR 0017 U1 activity feed)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app
from tests.serve.conftest import _make_task_dir


def _event(ts: str, kind: str, text: str = "") -> str:
    """One events.jsonl line with a text raw payload."""
    return json.dumps({"ts": ts, "kind": kind, "raw": {"type": "text", "part": {"text": text}}})


def _log_row(ts: str, level: str, message: str) -> str:
    """One log.jsonl line."""
    return json.dumps({"timestamp": ts, "level": level, "event": message})


def _make_feed_task(tasks_root: Path) -> Path:
    """Two-attempt task: 3 events + info/warning logs, then 2 events + stderr."""
    task_dir = _make_task_dir(tasks_root, "task-activity")
    attempt1 = task_dir / "attempts" / "1"
    attempt1.mkdir(parents=True)
    (attempt1 / "events.jsonl").write_text(
        "\n".join(
            [
                _event("2024-01-01T00:00:00Z", "assistant_text", "hello"),
                _event("2024-01-01T00:00:01Z", "tool_use", "read it"),
                _event("2024-01-01T00:00:02Z", "tool_result", "file contents"),
            ]
        )
    )
    (attempt1 / "log.jsonl").write_text(
        "\n".join(
            [
                _log_row("2024-01-01T00:00:01Z", "info", "started"),
                _log_row("2024-01-01T00:00:03Z", "warning", "slow"),
            ]
        )
    )
    attempt2 = task_dir / "attempts" / "2"
    attempt2.mkdir(parents=True)
    (attempt2 / "events.jsonl").write_text(
        "\n".join(
            [
                _event("2024-01-01T00:00:04Z", "assistant_text", "second"),
                _event("2024-01-01T00:00:05Z", "tool_result", "done"),
            ]
        )
    )
    (attempt2 / "log.stderr").write_text("\n".join(f"line {n}" for n in range(1, 51)))
    return task_dir


def _get(app, path: str) -> httpx.Response:
    """GET *path* against the serve app (sync wrapper for the async client)."""

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(path)

    return asyncio.run(_run())


def test_tail_merges_attempts_and_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default tail: 6 items in ts order with attempt/seq, stderr last 40 lines."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_feed_task(tmp_path / "tasks")
    data = _get(create_app(), "/api/tasks/task-activity/activity").json()
    assert data["total"] == 6
    assert data["latest_attempt"] == 2
    assert data["has_earlier"] is False
    items = data["items"]
    assert [row["seq"] for row in items] == [0, 1, 2, 3, 4, 5]
    assert [row["attempt"] for row in items] == [1, 1, 1, 1, 2, 2]
    assert [row["source"] for row in items] == ["event"] * 3 + ["log"] + ["event"] * 2
    assert items[3]["kind"] == "warning"
    assert items[3]["summary"] == "slow"
    assert items[0]["summary"] == "hello"
    assert data["stderr"]["attempt"] == 2
    assert data["stderr"]["lines"] == [f"line {n}" for n in range(11, 51)]


def test_min_level_info_includes_info_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """min_level=info keeps the info log row (7 items); default drops it."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_feed_task(tmp_path / "tasks")
    data = _get(create_app(), "/api/tasks/task-activity/activity?min_level=info").json()
    assert data["total"] == 7
    assert len(data["items"]) == 7
    info_rows = [row for row in data["items"] if row["source"] == "log"]
    assert [row["kind"] for row in info_rows] == ["info", "warning"]


def test_after_paging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """after=3 returns seq 4 and 5 with has_earlier set."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_feed_task(tmp_path / "tasks")
    data = _get(create_app(), "/api/tasks/task-activity/activity?after=3").json()
    assert [row["seq"] for row in data["items"]] == [4, 5]
    assert data["total"] == 6
    assert data["has_earlier"] is True


def test_before_paging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """before=2&limit=1 returns seq 1 with has_earlier set."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_feed_task(tmp_path / "tasks")
    data = _get(create_app(), "/api/tasks/task-activity/activity?before=2&limit=1").json()
    assert [row["seq"] for row in data["items"]] == [1]
    assert data["has_earlier"] is True


def test_after_and_before_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """after together with before is a 422."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_feed_task(tmp_path / "tasks")
    resp = _get(create_app(), "/api/tasks/task-activity/activity?after=1&before=5")
    assert resp.status_code == 422


def test_unknown_min_level_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown min_level value is a 422."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_feed_task(tmp_path / "tasks")
    resp = _get(create_app(), "/api/tasks/task-activity/activity?min_level=verbose")
    assert resp.status_code == 422


def test_missing_task_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown task id is a 404."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    resp = _get(create_app(), "/api/tasks/no-such-task/activity")
    assert resp.status_code == 404


def test_cache_invalidates_on_append(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Appending an event line grows total on the next call (fingerprint bust)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_feed_task(tmp_path / "tasks")
    app = create_app()
    assert _get(app, "/api/tasks/task-activity/activity").json()["total"] == 6
    assert _get(app, "/api/tasks/task-activity/activity").json()["total"] == 6
    with (task_dir / "attempts" / "2" / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("\n" + _event("2024-01-01T00:00:06Z", "assistant_text", "late"))
    assert _get(app, "/api/tasks/task-activity/activity").json()["total"] == 7
