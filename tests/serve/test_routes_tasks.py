"""Tests for the task list/detail/unblock routes (unit under test: serve/api/tasks.py)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from fleet.beads import status_cache as beads_info
from fleet.serve.app import create_app
from fleet.state import events as events_mod
from fleet.state import runtime_stats as stats_mod
from tests.serve.conftest import _make_task_dir


def test_tasks_list_returns_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks returns task list with correct shape (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    _make_task_dir(tasks_root, "task-abc", "in_progress")

    monkeypatch.setattr(
        "fleet.serve.api.tasks_list.get_beads_status_map", MagicMock(return_value=None)
    )

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert len(data["tasks"]) == 1
    t = data["tasks"][0]
    assert t["id"] == "task-abc"
    assert t["title"] == "Task task-abc"
    assert t["status"] == "in_progress"
    assert "elapsed_sec" in t
    assert "events" in t


def test_task_summary_includes_priority_and_depends_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/tasks includes priority and depends_on in each summary (FR-10, FR-11)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    monkeypatch.setattr(
        "fleet.serve.api.tasks_list.get_beads_status_map", MagicMock(return_value=None)
    )
    _make_task_dir(
        tasks_root,
        "task-bd1",
        "open",
        priority=5,
        depends_on=["task-x", "task-y"],
    )
    _make_task_dir(tasks_root, "task-bd2", "in_progress")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    tasks = {t["id"]: t for t in resp.json()["tasks"]}

    assert tasks["task-bd1"]["priority"] == 5
    assert tasks["task-bd1"]["depends_on"] == ["task-x", "task-y"]
    assert tasks["task-bd2"]["priority"] is None
    assert tasks["task-bd2"]["depends_on"] == []


def test_tasks_list_cache_hit_skips_rescan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second GET /api/tasks poll does not re-scan unchanged events.jsonl."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setattr(
        "fleet.serve.api.tasks_list.get_beads_status_map", MagicMock(return_value=None)
    )
    task_dir = _make_task_dir(tmp_path / "tasks", "task-cachecheck")
    event = {"kind": "tool_use", "ts": "2024-01-01T00:00:00Z", "tool_name": "Read"}
    (task_dir / "events.jsonl").write_text(json.dumps(event) + "\n")

    stats_mod._events_cache.clear()

    scan_count = 0
    _orig = events_mod.event_stats

    def _counting(task_dir: Path):
        nonlocal scan_count
        scan_count += 1
        return _orig(task_dir)

    monkeypatch.setattr(events_mod, "event_stats", _counting)

    app = create_app()

    async def _run() -> tuple[httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r1 = await client.get("/api/tasks")
            r2 = await client.get("/api/tasks")
            return r1, r2

    r1, r2 = asyncio.run(_run())
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert scan_count == 1  # only one scan despite two polls


def test_tasks_list_cache_invalidated_on_events_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache is invalidated when events.jsonl changes; events count reflects the update."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setattr(
        "fleet.serve.api.tasks_list.get_beads_status_map", MagicMock(return_value=None)
    )
    task_dir = _make_task_dir(tmp_path / "tasks", "task-cacheinv")
    ev1 = {"kind": "tool_use", "ts": "2024-01-01T00:00:00Z", "tool_name": "Read"}
    attempt_dir = task_dir / "attempts" / "1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "events.jsonl").write_text(json.dumps(ev1) + "\n")

    stats_mod._events_cache.clear()

    app = create_app()

    async def _get() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks")

    r1 = asyncio.run(_get())
    assert r1.status_code == 200
    tasks1 = {t["id"]: t for t in r1.json()["tasks"]}
    assert tasks1["task-cacheinv"]["events"] == 1

    ev2 = {"kind": "tool_use", "ts": "2024-01-01T00:00:01Z", "tool_name": "Edit"}
    with (attempt_dir / "events.jsonl").open("a") as fh:
        fh.write(json.dumps(ev2) + "\n")

    r2 = asyncio.run(_get())
    assert r2.status_code == 200
    tasks2 = {t["id"]: t for t in r2.json()["tasks"]}
    assert tasks2["task-cacheinv"]["events"] == 2


def test_beads_status_map_cache_prevents_duplicate_subprocesses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rapid successive GET /api/tasks polls reuse the bd list cache (TASKS 5.3).

    Two back-to-back polls must call the subprocess exactly once — the second
    poll returns the cached map without shelling out again.
    """
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-bdcache")

    # Reset module-level cache and counter so this test is isolated.
    monkeypatch.setattr("fleet.beads.status_cache._beads_map_cache", {})
    monkeypatch.setattr("fleet.beads.status_cache._beads_list_call_count", 0)

    app = create_app()

    async def _run() -> tuple[httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r1 = await client.get("/api/tasks")
            r2 = await client.get("/api/tasks")
            return r1, r2

    r1, r2 = asyncio.run(_run())
    assert r1.status_code == 200
    assert r2.status_code == 200

    assert beads_info._beads_list_call_count == 1, (
        "Expected exactly one bd-list subprocess call for two rapid polls; "
        f"got {beads_info._beads_list_call_count}"
    )


def test_files_returns_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/files returns per-file read/edit/write counts (FR-20)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-files")
    events = [
        {
            "kind": "tool_use",
            "tool_name": "Read",
            "raw": {"input": {"file_path": "/foo.py"}},
        },
        {
            "kind": "tool_use",
            "tool_name": "Edit",
            "raw": {"input": {"file_path": "/foo.py"}},
        },
        {
            "kind": "tool_use",
            "tool_name": "Write",
            "raw": {"input": {"file_path": "/bar.py"}},
        },
        {
            "kind": "tool_use",
            "tool_name": "Read",
            "raw": {"input": {"file_path": "/foo.py"}},
        },
        {"kind": "tool_result", "tool_name": None, "raw": {}},  # non-tool_use, ignored
    ]
    attempt_dir = task_dir / "attempts" / "1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-files/files")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data
    files_map = {f["path"]: f for f in data["files"]}
    assert "/foo.py" in files_map
    assert files_map["/foo.py"]["read"] == 2
    assert files_map["/foo.py"]["edit"] == 1
    assert "/bar.py" in files_map
    assert files_map["/bar.py"]["write"] == 1


def test_list_tasks_fills_missing_title_from_beads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A task.json without title (written by `fleet bd create` before claim)
    gets its title/description from the beads map so pending rows aren't blank."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = tmp_path / "tasks" / "task-notitle"
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(
        json.dumps({"id": "task-notitle", "cwd": "/repo", "coder": "claude"})
    )
    monkeypatch.setattr(
        "fleet.serve.api.tasks_list.get_beads_status_map",
        MagicMock(
            return_value={
                "task-notitle": {
                    "status": "open",
                    "created_at": None,
                    "priority": 2,
                    "title": "From beads",
                    "description": "Beads body",
                }
            }
        ),
    )
    app = create_app()

    async def _get() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks")

    r = asyncio.run(_get())
    assert r.status_code == 200
    tasks = {t["id"]: t for t in r.json()["tasks"]}
    assert tasks["task-notitle"]["title"] == "From beads"
    assert tasks["task-notitle"]["description"] == "Beads body"
    assert tasks["task-notitle"]["status"] == "open"


def test_list_tasks_includes_block_and_retry_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/tasks includes blocked_reason, restarts, rounds for a task."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task_dir(tasks_root, "task-blocked", "blocked", blocked_reason="x")
    # Two consecutive failure attempts journaled in attempts.jsonl.
    (task_dir / "attempts.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event": "start", "n": 1, "ts": "2026-01-01T00:00:00+00:00"}),
                json.dumps(
                    {
                        "event": "end",
                        "n": 1,
                        "ts": "2026-01-01T00:01:00+00:00",
                        "outcome": "failure",
                        "exit_code": 1,
                        "reason": "boom",
                        "action": "release",
                    }
                ),
                json.dumps({"event": "start", "n": 2, "ts": "2026-01-01T01:00:00+00:00"}),
                json.dumps(
                    {
                        "event": "end",
                        "n": 2,
                        "ts": "2026-01-01T01:01:00+00:00",
                        "outcome": "failure",
                        "exit_code": 1,
                        "reason": "boom again",
                        "action": "release",
                    }
                ),
            ]
        )
        + "\n"
    )

    monkeypatch.setattr(
        "fleet.serve.api.tasks_list.get_beads_status_map", MagicMock(return_value=None)
    )

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    t = {t["id"]: t for t in resp.json()["tasks"]}["task-blocked"]
    assert t["blocked_reason"] == "x"
    assert t["restarts"] == 1
    assert t["rounds"]["failure"] == 2


def test_task_detail_includes_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id} includes an attempts list built from attempts.jsonl."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task_dir(tasks_root, "task-attempts", "closed")
    lines = [
        json.dumps(
            {
                "event": "start",
                "n": 1,
                "ts": "2026-01-01T00:00:00+00:00",
                "coder": "claude",
                "model": "sonnet",
            }
        ),
        json.dumps(
            {
                "event": "end",
                "n": 1,
                "ts": "2026-01-01T00:01:00+00:00",
                "outcome": "success",
                "exit_code": 0,
                "reason": "done",
                "action": "close",
            }
        ),
    ]
    (task_dir / "attempts.jsonl").write_text("\n".join(lines) + "\n")

    monkeypatch.setattr("fleet.serve.api.tasks_detail.fetch_beads_info", lambda *a, **k: None)

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-attempts")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["attempts"]) == 1
    assert data["attempts"][0]["outcome"] == "success"
    assert data["attempts"][0]["n"] == 1


def test_unblock_task_releases_and_clears_retry_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/tasks/{id}/unblock releases the task and clears retry_after."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task_dir(tasks_root, "task-unblock", "blocked")
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                **json.loads((task_dir / "task.json").read_text()),
                "retry_after": "2099-01-01T00:00:00+00:00",
            }
        )
    )
    (task_dir / ".needs_validation").write_text("1")

    mock_queue = MagicMock()
    app = create_app(queue=mock_queue)

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/task-unblock/unblock", json={"note": "looks fine"})

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert mock_queue.release.call_count == 1
    args = mock_queue.release.call_args.args
    assert args[0] == "task-unblock"
    assert "unblocked" in args[1]
    assert "looks fine" in args[1]
    assert "retry_after" not in (task_dir / "task.json").read_text()
    assert not (task_dir / ".needs_validation").exists()
    rows = (task_dir / "attempts.jsonl").read_text().splitlines()
    assert json.loads(rows[-1])["event"] == "unblock"
    assert "looks fine" in rows[-1]


def test_unblock_task_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/tasks/{id}/unblock returns 404 for unknown task."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/nonexistent/unblock")

    resp = asyncio.run(_run())
    assert resp.status_code == 404
