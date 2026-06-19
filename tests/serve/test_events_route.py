"""Tests for GET /api/tasks/{id}/events (FR-?? - events.jsonl history viewer)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app


def _make_task(tasks_root: Path, task_id: str) -> Path:
    task_dir = tasks_root / task_id
    task_dir.mkdir(parents=True)
    data = {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": "in_progress",
        "cwd": "/repo",
        "coder": "opencode",
        "model": "gpt-oss:20b",
    }
    (task_dir / "task.json").write_text(json.dumps(data))
    return task_dir


def _write_events(task_dir: Path, lines: list[str]) -> None:
    (task_dir / "events.jsonl").write_text("\n".join(lines))


# ---- helper events for the fixture ------------------------------


def _mixed_events() -> list[str]:
    return [
        json.dumps(
            {
                "ts": "2024-01-01T00:00:00Z",
                "kind": "session_started",
                "sessionID": "abc-1111",
                "raw": {"sessionID": "abc-1111"},
            }
        ),
        json.dumps(
            {
                "ts": "2024-01-01T00:00:01Z",
                "kind": "assistant_text",
                "sessionID": "abc-1111",
                "raw": {"type": "text", "part": {"text": "Hello world"}},
            }
        ),
        json.dumps(
            {
                "ts": "2024-01-01T00:00:02Z",
                "kind": "tool_use",
                "tool_name": "Read",
                "sessionID": "abc-1111",
                "raw": {
                    "type": "tool_use",
                    "part": {
                        "type": "tool",
                        "state": {"input": {"file_path": "/foo.py"}},
                    },
                },
            }
        ),
        "THIS IS MALFORMED LINE",
        json.dumps(
            {
                "ts": "2024-01-01T00:00:03Z",
                "kind": "tool_result",
                "tool_name": "Read",
                "sessionID": "abc-1111",
                "raw": {
                    "type": "tool_use",
                    "part": {"state": {"output": "file contents"}},
                },
            }
        ),
        json.dumps(
            {
                "ts": "2024-01-01T00:00:04Z",
                "kind": "error",
                "tool_name": "Edit",
                "sessionID": "abc-1111",
                "raw": {
                    "type": "error",
                    "part": {"state": {"error": "permission denied"}},
                },
            }
        ),
        json.dumps(
            {
                "ts": "2024-01-01T00:00:05Z",
                "kind": "session_started",
                "sessionID": "xyz-2222",
                "raw": {"sessionID": "xyz-2222"},
            }
        ),
        json.dumps(
            {
                "ts": "2024-01-01T00:00:06Z",
                "kind": "assistant_text",
                "sessionID": "xyz-2222",
                "raw": {"type": "text", "part": {"text": "Second session"}},
            }
        ),
    ]


def test_default_returns_tail_in_file_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default call returns the tail (all events, no offset), malformed line skipped, total correct."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task(tasks_root, "task-ev1")
    events = _mixed_events()
    _write_events(task_dir, events)

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-ev1/events")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 7  # 8 lines minus 1 malformed
    assert data["offset"] == 0  # default = full list returned, starts at index 0
    assert len(data["events"]) == 7

    # file order preserved
    for idx, evt in enumerate(data["events"]):
        assert evt["i"] == idx
    assert data["events"][0]["kind"] == "session_started"
    assert data["events"][-1]["kind"] == "assistant_text"


def test_offset_and_limit_paging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """offset+limit paging returns the expected slice."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task(tasks_root, "task-ev2")
    events = _mixed_events()
    _write_events(task_dir, events)

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-ev2/events?offset=2&limit=3")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 7
    assert data["offset"] == 2
    assert len(data["events"]) == 3
    assert data["events"][0]["i"] == 2
    assert data["events"][1]["i"] == 3
    assert data["events"][2]["i"] == 4

    # limit clamp to 500
    async def _big_limit() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-ev2/events?limit=9999")

    resp2 = asyncio.run(_big_limit())
    assert resp2.status_code == 200
    # limit is clamped to 500, so all 7 events fit
    assert len(resp2.json()["events"]) <= 7


def test_kind_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """kind=error filters to only error events."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task(tasks_root, "task-ev3")
    events = _mixed_events()
    _write_events(task_dir, events)

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-ev3/events?kind=error")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["events"][0]["kind"] == "error"
    assert data["events"][0]["summary"].startswith("Edit")


def test_events_have_summary_and_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each event has summary and raw fields populated."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task(tasks_root, "task-ev4")
    events = [
        json.dumps(
            {
                "ts": "2024-01-01T00:00:00Z",
                "kind": "assistant_text",
                "sessionID": "abc",
                "raw": {"type": "text", "part": {"text": "Hello"}},
            }
        ),
        json.dumps(
            {
                "ts": "2024-01-01T00:00:01Z",
                "kind": "tool_use",
                "tool_name": "Read",
                "sessionID": "abc",
                "raw": {
                    "type": "tool_use",
                    "part": {"type": "tool", "state": {"input": {"path": "/x"}}},
                },
            }
        ),
        json.dumps(
            {
                "ts": "2024-01-01T00:00:02Z",
                "kind": "error",
                "tool_name": "Edit",
                "sessionID": "abc",
                "raw": {"type": "error", "part": {"state": {"error": "oops"}}},
            }
        ),
    ]
    _write_events(task_dir, events)

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-ev4/events")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    for evt in data["events"]:
        assert "summary" in evt
        assert "raw" in evt
        assert isinstance(evt["summary"], str)
        assert isinstance(evt["raw"], dict)
    # Check specific summaries
    assert "Hello" in data["events"][0]["summary"]
    assert "Read" in data["events"][1]["summary"]
    assert "Edit" in data["events"][2]["summary"]
    assert "oops" in data["events"][2]["summary"]


def test_unknown_task_id_returns_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown task id → 404."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/nonexistent/events")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_kind_filter_multi_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kind=tool_use,tool_result filters to both kinds."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task(tasks_root, "task-ev5")
    events = [
        json.dumps(
            {
                "ts": "2024-01-01T00:00:00Z",
                "kind": "tool_use",
                "tool_name": "Read",
                "raw": {},
            }
        ),
        json.dumps(
            {
                "ts": "2024-01-01T00:00:01Z",
                "kind": "tool_result",
                "tool_name": "Read",
                "raw": {},
            }
        ),
        json.dumps({"ts": "2024-01-01T00:00:02Z", "kind": "assistant_text", "raw": {}}),
    ]
    _write_events(task_dir, events)

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(
                "/api/tasks/task-ev5/events?kind=tool_use,tool_result"
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["events"][0]["kind"] == "tool_use"
    assert data["events"][1]["kind"] == "tool_result"


def test_no_events_jsonl_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing events.jsonl returns empty list."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    _make_task(tasks_root, "task-ev6")
    # No events.jsonl

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-ev6/events")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["events"] == []


def test_session_id_separator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two different session_ids produce events with session_id field."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task(tasks_root, "task-ev7")
    events = [
        json.dumps(
            {
                "ts": "2024-01-01T00:00:00Z",
                "kind": "session_started",
                "sessionID": "sess-aaaa",
                "raw": {"sessionID": "sess-aaaa"},
            }
        ),
        json.dumps(
            {
                "ts": "2024-01-01T00:00:01Z",
                "kind": "assistant_text",
                "sessionID": "sess-aaaa",
                "raw": {"type": "text", "part": {"text": "hi"}},
            }
        ),
        json.dumps(
            {
                "ts": "2024-01-01T00:00:02Z",
                "kind": "session_started",
                "sessionID": "sess-bbbb",
                "raw": {"sessionID": "sess-bbbb"},
            }
        ),
    ]
    _write_events(task_dir, events)

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-ev7/events")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["events"]) == 3
    assert data["events"][0]["session_id"] == "sess-aaaa"
    assert data["events"][2]["session_id"] == "sess-bbbb"
