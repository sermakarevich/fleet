"""Tests for REST API routes (FR-07, FR-31 through FR-44)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from starlette.testclient import TestClient

import fleet.serve.auth as auth_mod
from fleet.beads import status_cache as beads_info
from fleet.serve.app import create_app
from fleet.state import events as events_mod
from fleet.state import runtime_stats as stats_mod


def _make_task_dir(
    tasks_root: Path,
    task_id: str,
    status: str = "in_progress",
    **kwargs,
) -> Path:
    task_dir = tasks_root / task_id
    task_dir.mkdir(parents=True)
    data: dict = {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": status,
        "cwd": "/repo",
        "coder": "claude",
        "model": "sonnet",
    }
    data.update(kwargs)
    (task_dir / "task.json").write_text(json.dumps(data))
    return task_dir


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


def test_task_kill_killing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/tasks/{id}/kill returns killing when the task is in_progress (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task_dir(tasks_root, "task-kill", "in_progress")
    # Write supervisor PID file pointing at the live test process.
    (tmp_path / ".supervisor.pid").write_text(json.dumps({"pid": os.getpid()}))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/task-kill/kill")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "result": "killing"}
    assert (task_dir / ".kill").exists(), ".kill sentinel should be written"


def test_task_kill_supervisor_not_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/tasks/{id}/kill returns supervisor-not-running when no live supervisor (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task_dir(tasks_root, "task-kill-sv", "in_progress")
    # No .supervisor.pid file — supervisor is not running.
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/task-kill-sv/kill")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "result": "supervisor-not-running"}
    assert (task_dir / ".kill").exists(), ".kill sentinel should still be written"


def test_task_kill_queued_closes_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/tasks/{id}/kill closes queued tasks via queue.close, writes no sentinel (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    task_dir = _make_task_dir(tasks_root, "task-kill-nr", "open")
    (tmp_path / ".supervisor.pid").write_text(json.dumps({"pid": os.getpid()}))
    mock_queue = MagicMock()
    app = create_app(queue=mock_queue)

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/task-kill-nr/kill")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "result": "closed"}
    assert not (task_dir / ".kill").exists(), (
        ".kill sentinel should NOT be written for non-running task"
    )
    mock_queue.close.assert_called_once_with("task-kill-nr", "killed")


def test_task_kill_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/tasks/{id}/kill returns 404 for unknown task (FR-07)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks/nonexistent/kill")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_task_summary_includes_priority_and_depends_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/tasks includes priority and depends_on in each summary (FR-10, FR-11)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
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


def test_config_get_returns_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/config returns all RuntimeConfig fields (FR-43)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/config")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "max_concurrent" in data
    assert "model" in data
    assert "coder" in data


def test_config_put_updates_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT /api/config updates runtime.toml atomically and returns new config (FR-43)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.put("/api/config", json={"max_concurrent": "5"})

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["max_concurrent"] == 5
    assert (tmp_path / "runtime.toml").exists()


def test_config_put_unknown_coder_is_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT /api/config with an unknown coder is rejected (FR-43)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.put("/api/config", json={"coder": "garbage_typo"})

    resp = asyncio.run(_run())
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Artifact endpoints (FR-11..FR-21)
# ---------------------------------------------------------------------------


def test_artifact_state_returns_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/state returns STATE.md content and mtime."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-state")
    (task_dir / "STATE.md").write_text("## Next\ndo the thing")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-state/artifacts/state")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "do the thing" in data["content"]
    assert isinstance(data["mtime"], float)


def test_artifact_state_falls_back_to_legacy_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Old tasks with no STATE.md render the legacy artifacts view."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-old-state")
    artifacts = task_dir / "artifacts"
    artifacts.mkdir()
    (artifacts / "KNOWLEDGE.md").write_text("old fact")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-old-state/artifacts/state")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert "old fact" in resp.json()["content"]


def test_artifact_state_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/state returns 404 when nothing to show."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-nostate")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-nostate/artifacts/state")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_artifact_result_returns_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/result returns RESULT.json content."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-result")
    (task_dir / "RESULT.json").write_text('{"schema": 1, "status": "done", "summary": "ok"}')

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-result/artifacts/result")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert '"status": "done"' in data["content"]


def test_artifact_result_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/result returns 404 when file missing."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-noresult")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-noresult/artifacts/result")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_logs_returns_parsed_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/logs returns parsed log lines (FR-17)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-logs")
    log_lines = [
        json.dumps({"timestamp": "2024-01-01T00:00:00", "level": "info", "event": "started"}),
        json.dumps({"timestamp": "2024-01-01T00:00:01", "level": "error", "event": "failed"}),
        "bad line",  # malformed line should be skipped
    ]
    (task_dir / "log.jsonl").write_text("\n".join(log_lines))

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-logs/logs")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "lines" in data
    assert len(data["lines"]) == 2
    assert data["lines"][0]["level"] == "info"
    assert data["lines"][0]["message"] == "started"
    assert data["lines"][1]["level"] == "error"


def test_logs_level_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/logs?level=error returns only error lines (FR-17)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-logfilter")
    log_lines = [
        json.dumps({"timestamp": "2024-01-01T00:00:00", "level": "info", "event": "ok"}),
        json.dumps({"timestamp": "2024-01-01T00:00:01", "level": "error", "event": "boom"}),
    ]
    (task_dir / "log.jsonl").write_text("\n".join(log_lines))

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-logfilter/logs?level=error")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["lines"]) == 1
    assert data["lines"][0]["level"] == "error"


def test_stderr_returns_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/stderr returns raw stderr content (FR-18)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-stderr")
    (task_dir / "log.stderr").write_text("some error output\nanother line")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-stderr/stderr")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert "some error output" in data["content"]


def test_stderr_empty_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/stderr returns empty content when log.stderr absent (FR-18)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-nostderr")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-nostderr/stderr")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json()["content"] == ""


def test_supervisor_dead_with_stale_tasks_reports_zero_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/supervisor reports active_count=0 for a dead supervisor (FR-42)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    _make_task_dir(tasks_root, "stale-1", "in_progress")
    _make_task_dir(tasks_root, "stale-2", "in_progress")
    # No .supervisor.pid file → supervisor is not running

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/supervisor")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False
    assert data["active_count"] == 0
    assert data["free_slots"] == data["max_concurrent"]


def test_supervisor_running_counts_active_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/supervisor returns active_count from task files when supervisor is alive (FR-42)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    tasks_root = tmp_path / "tasks"
    _make_task_dir(tasks_root, "active-1", "in_progress")
    _make_task_dir(tasks_root, "done-1", "completed")

    pid = os.getpid()
    (tmp_path / ".supervisor.pid").write_text(
        json.dumps(
            {
                "pid": pid,
                "started_at": "2024-01-01T00:00:00",
                "version_fingerprint": "x",
            }
        )
    )

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/supervisor")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is True
    assert data["active_count"] == 1
    assert data["free_slots"] == data["max_concurrent"] - 1


def test_diff_returns_empty_for_non_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/diff returns empty diff when cwd is not a git repo (FR-19)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    work_dir = tmp_path / "workdir"
    work_dir.mkdir()
    _make_task_dir(tmp_path / "tasks", "task-diff", cwd=str(work_dir))

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-diff/diff")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json()["diff"] == ""


def test_tasks_list_cache_hit_skips_rescan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second GET /api/tasks poll does not re-scan unchanged events.jsonl."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
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


# ---------------------------------------------------------------------------
# Attempt endpoints: derived summary, recorded prompt, state snapshot, outputs
# ---------------------------------------------------------------------------


def _make_attempt_dir(tmp_path: Path, task_id: str = "task-attempt") -> Path:
    task_dir = _make_task_dir(tmp_path / "tasks", task_id)
    attempt_dir = task_dir / "attempts" / "1"
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "run.json").write_text(
        json.dumps({"launch": {"mode": "continue", "pack_bytes": 7, "kind": "work"}})
    )
    (attempt_dir / "prompt.md").write_text("the rendered prompt")
    (attempt_dir / "STATE.md").write_text("## Next\ndo the thing")
    (attempt_dir / "RESULT.json").write_text(
        json.dumps({"schema": 1, "status": "partial", "summary": "wip"})
    )
    (task_dir / "attempts.jsonl").write_text(
        json.dumps(
            {
                "event": "start",
                "n": 1,
                "ts": "2026-01-01T00:00:00+00:00",
                "coder": "claude",
                "model": "sonnet",
                "worker": "task.continue",
            }
        )
        + "\n"
    )
    return task_dir


def test_attempt_summary_is_derived(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/attempts/{n}/summary renders on demand (no file)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_attempt_dir(tmp_path)
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-attempt/attempts/1/summary")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert "Attempt 1 summary" in resp.json()["content"]
    assert "launch mode: continue" in resp.json()["content"]


def test_attempt_prompt_returns_recorded_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/tasks/{id}/attempts/{n}/prompt returns prompt.md."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_attempt_dir(tmp_path)
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-attempt/attempts/1/prompt")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json()["content"] == "the rendered prompt"


def test_attempt_prompt_404_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/attempts/{n}/prompt 404s without prompt.md."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_attempt_dir(tmp_path, "task-noprompt")
    (task_dir / "attempts" / "1" / "prompt.md").unlink()
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-noprompt/attempts/1/prompt")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_attempt_state_returns_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/attempts/{n}/state returns the STATE.md snapshot."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_attempt_dir(tmp_path)
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-attempt/attempts/1/state")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert "do the thing" in resp.json()["content"]


def test_artifact_outputs_lists_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/artifacts/outputs lists outputs/ files."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _make_task_dir(tmp_path / "tasks", "task-outputs")
    outputs = task_dir / "outputs"
    outputs.mkdir()
    (outputs / "report.md").write_text("report")
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-outputs/artifacts/outputs")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json() == {"files": ["report.md"]}


def test_artifact_result_falls_back_to_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Post-reap the live RESULT.json is gone; the snapshot still serves."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_attempt_dir(tmp_path)
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-attempt/artifacts/result")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert '"status": "partial"' in resp.json()["content"]


# ---------------------------------------------------------------------------
# Serve hardening (ADR 0006 bead 23): auth covers healthz/ws, bounded queries,
# one error shape, no hand-parsed params
# ---------------------------------------------------------------------------


def test_healthz_requires_token_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """/healthz returns 401 without a token when FLEET_API_TOKEN is set."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_API_TOKEN", "secret")
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/healthz")

    resp = asyncio.run(_run())
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


def test_websocket_rejects_missing_token_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ws without a token closes with 4401 when FLEET_API_TOKEN is set."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    monkeypatch.setenv("FLEET_API_TOKEN", "secret")
    app = create_app()
    client = TestClient(app)
    try:
        with client.websocket_connect("/ws/events"):
            pass
        code = None
    except Exception as exc:  # noqa: BLE001 - close code surfaces via the error
        code = getattr(exc, "code", None)
    assert code == 4401


def test_events_limit_out_of_range_is_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/tasks/{id}/events?limit=999999 returns 422 (bounded query)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _make_task_dir(tmp_path / "tasks", "task-evlimit")

    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/tasks/task-evlimit/events?limit=999999")

    resp = asyncio.run(_run())
    assert resp.status_code == 422


def test_config_put_unknown_key_is_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT /api/config with an unknown key returns 422 listing the key."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.put("/api/config", json={"no_such_key": "1"})

    resp = asyncio.run(_run())
    assert resp.status_code == 422
    assert "no_such_key" in resp.json()["error"]


def test_chat_answer_malformed_body_is_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/chat/questions/{id}/answer with bad JSON returns 400."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/chat/questions/q1/answer",
                content=b"{not json",
                headers={"Content-Type": "application/json"},
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_auth_uses_constant_time_compare() -> None:
    """serve/auth.py compares tokens with secrets.compare_digest, not ==."""
    src = Path(auth_mod.__file__).read_text(encoding="utf-8")
    assert "compare_digest" in src
