"""Tests for GET /api/analytics/summary endpoint."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from unittest.mock import MagicMock

from fleet.serve.app import create_app


def _patch_no_beads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkey-patch get_beads_status_map to return None (skip beads in tests, per spec: 'bd unavailable → raw statuses used')."""
    monkeypatch.setattr(
        "fleet.serve.beads_info.get_beads_status_map",
        MagicMock(return_value=None),
    )


def _reset_analytics_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the analytics_core module-level cache that persists across tests."""
    import sys

    # Delete the module so fresh import gets a fresh cache
    stale = [k for k in sys.modules if k.startswith("fleet.serve.analytics_core")]
    for key in stale:
        del sys.modules[key]
    import fleet.serve.analytics_core as ac

    ac._info_cache.clear()
    monkeypatch.setattr(ac, "_info_cache", {})


def make_task_dir(
    tasks_root: Path,
    task_id: str,
    *,
    status: str = "in_progress",
    coder: str = "claude",
    model: str = "sonnet",
    cwd: str = "/repo",
    priority: int = 1,
    created_at: str | None = None,
    status_raw: str | None = None,
) -> Path:
    """Create a task directory with task.json and events."""
    td = tasks_root / task_id
    td.mkdir(parents=True)
    data: dict = {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": status_raw or status,
        "cwd": cwd,
        "coder": coder,
        "model": model,
        "priority": priority,
    }
    if created_at is not None:
        data["created_at"] = created_at
    (td / "task.json").write_text(json.dumps(data), "utf-8")
    return td


def write_events(td: Path, lines: list[str]) -> None:
    """Write event lines to events.jsonl."""
    (td / "events.jsonl").write_text("\n".join(lines) + "\n", "utf-8")


def ev(
    ts: str = "2025-06-01T10:00:00Z",
    kind: str = "session_started",
    session_id: str | None = None,
    **kwargs,
) -> str:
    r: dict = {"ts": ts, "kind": kind}
    if session_id:
        r["session_id"] = session_id
    r.update(kwargs)
    return json.dumps(r)


def _make_future_days(n_days: int) -> str:
    """Return an ISO timestamp n days ago now."""
    return (datetime.now(tz=timezone.utc) - timedelta(days=n_days)).isoformat()


def _make_now() -> str:
    """Return current ISO timestamp with tz."""
    return datetime.now(tz=timezone.utc).isoformat()


def _make_window_day(hours_ago: int = 6) -> str:
    """Return a timestamp hours_ago ago — comfortably within any 1–7 day window."""
    return (datetime.now(tz=timezone.utc) - timedelta(hours=hours_ago)).isoformat()


class TestSummaryDefaultDays:
    """Test 1: default days=7 — KPIs are correct."""

    def test_kpis_completed_success_rate_output_tokens_avg_segments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        tasks_root = tmp_path / "tasks"

        now = _make_now()
        window = _make_window_day(1)

        # Task 1: closed success with session_ids and output_tokens (within window)
        td1 = make_task_dir(
            tasks_root, "task-1", status="closed", cwd="/proj-a", created_at=window
        )
        write_events(
            td1,
            [
                ev(ts=window, kind="session_started", session_id="s1"),
                ev(ts=window, kind="session_started", session_id="s2"),
                ev(
                    ts=window,
                    kind="tool_result",
                    tool_name="Read",
                    usage={"output_tokens": 100, "input_tokens": 50},
                ),
                ev(ts=window, kind="error"),
            ],
        )

        # Task 2: closed success within window
        td2 = make_task_dir(tasks_root, "task-2", status="closed", cwd="/proj-a")
        write_events(
            td2,
            [
                ev(ts=window, kind="session_started", session_id="s3"),
                ev(
                    ts=window,
                    kind="tool_result",
                    tool_name="Edit",
                    usage={"output_tokens": 200, "input_tokens": 100},
                ),
            ],
        )

        # Task 3: failed, within window
        td3 = make_task_dir(tasks_root, "task-3", status="failed", cwd="/proj-b")
        write_events(
            td3,
            [
                ev(ts=window, kind="session_started", session_id="s4"),
                ev(ts=window, kind="error"),
                ev(ts=window, kind="error"),
            ],
        )

        # Task 4: in_progress — counted as active, not completed
        make_task_dir(tasks_root, "task-4", status="in_progress", cwd="/proj-c")

        # Task 5: blocked, within window
        td5 = make_task_dir(
            tasks_root, "task-5", status="blocked", cwd="/proj-a", created_at=window
        )
        write_events(
            td5,
            [
                ev(ts=window, kind="session_started", session_id="s5"),
                ev(
                    ts=window,
                    kind="tool_result",
                    tool_name="Read",
                    usage={"output_tokens": 50, "input_tokens": 25},
                ),
            ],
        )

        # Also set noclose on task-5
        (td5 / ".noclose").touch()

        # Task 6: rate limited completed task
        td6 = make_task_dir(
            tasks_root, "task-6", status="closed", cwd="/proj-b", created_at=window
        )
        write_events(
            td6,
            [
                ev(ts=window, kind="session_started", session_id="s6"),
                ev(ts=window, kind="rate_limit", rate_info={"status": "rejected"}),
                ev(
                    ts=window,
                    kind="tool_result",
                    tool_name="Read",
                    usage={"output_tokens": 300, "input_tokens": 150},
                ),
            ],
        )

        app = create_app()

        async def _run() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.get("/api/analytics/summary")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()

        # window_days echo
        assert data["window_days"] == 7

        kpis = data["kpis"]

        # completed = task-1 + task-2 + task-3 + task-5 + task-6 = 5
        assert kpis["completed"] == 5

        # success_rate = 3/5 (task-1, task-2, task-6 are success)
        assert kpis["success_rate"] == 0.6

        # active_now: task-4 in_progress
        assert kpis["active_now"] == 1

        # queued: none (no "open" or "ready" statuses)
        assert kpis["queued"] == 0

        # total_output_tokens: 100 (task-1) + 200 (task-2) + 0 (task-3) + 50 (task-5) + 300 (task-6) = 650
        assert kpis["total_output_tokens"] == 650

        # avg_segments: (2 + 1 + 1 + 1 + 1) / 5 = 6 / 5 = 1.2
        assert kpis["avg_segments"] == pytest.approx(1.2, abs=0.01)

        # error_events: task-1 (1) + task-3 (2) + task-5 (0) + task-6 (0) = 3
        assert kpis["error_events"] == 3

        # noclose_count: task-5
        assert kpis["noclose_count"] == 1

        # rate_limited_tasks: task-6 only
        assert kpis["rate_limited_tasks"] >= 1

        # throughput bucket_size should be "day" for default 7
        assert data["throughput"]["bucket_size"] == "day"


class TestSummaryDaysParam:
    """Test 2: days=1 excludes old completions; days=0 includes everything."""

    def test_days_1_excludes_old_completion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        _reset_analytics_cache(monkeypatch)
        tasks_root = tmp_path / "tasks"

        now = _make_now()
        window = _make_window_day(1)

        # Task 1: completed 3 days ago — should be excluded with days=1
        td1 = make_task_dir(
            tasks_root,
            "task-old",
            status="closed",
            cwd="/proj-x",
            created_at=_make_future_days(3),
        )
        write_events(
            td1,
            [
                ev(ts=_make_future_days(3), kind="session_started", session_id="s1"),
                ev(
                    ts=_make_future_days(3),
                    kind="tool_result",
                    tool_name="Edit",
                    usage={"output_tokens": 1000, "input_tokens": 500},
                ),
            ],
        )

        # Task 2: completed 1 day ago — should be included with days=1
        td2 = make_task_dir(tasks_root, "task-recent", status="closed", cwd="/proj-x")
        write_events(
            td2,
            [
                ev(ts=window, kind="session_started", session_id="s2"),
                ev(
                    ts=window,
                    kind="tool_result",
                    tool_name="Read",
                    usage={"output_tokens": 500, "input_tokens": 300},
                ),
            ],
        )

        # Task 3: active — never filtered
        make_task_dir(tasks_root, "task-active", status="in_progress", cwd="/proj-x")

        app = create_app()

        async def _run(d: int) -> dict:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                r = await client.get(f"/api/analytics/summary?days={d}")
                return r.json()

        d1 = asyncio.run(_run(1))
        d0 = asyncio.run(_run(0))

        # days=1: only task-recent is completed in window
        assert d1["kpis"]["completed"] == 1
        assert d1["kpis"]["total_output_tokens"] == 500

        # days=0: all time — both task-old and task-recent are completed
        assert d0["kpis"]["completed"] == 2
        assert d0["kpis"]["total_output_tokens"] == 1500

        # active is never filtered
        assert d1["kpis"]["active_now"] == 1
        assert d0["kpis"]["active_now"] == 1


class TestSummaryModelAndProjectBreakdowns:
    """Test 3: by_model and by_project row math."""

    def test_by_model_and_by_project_maths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        _reset_analytics_cache(monkeypatch)
        tasks_root = tmp_path / "tasks"

        window = _make_window_day(2)

        # (claude, sonnet) → 2 tasks, 1 success + 1 failure
        td1 = make_task_dir(
            tasks_root,
            "task-mm1",
            status="closed",
            coder="claude",
            model="sonnet",
            cwd="/proj-y",
        )
        write_events(
            td1,
            [
                ev(ts=window, kind="session_started", session_id="sm1"),
                ev(
                    ts=window,
                    kind="tool_result",
                    tool_name="Edit",
                    usage={
                        "output_tokens": 300,
                        "input_tokens": 100,
                        "cache_creation_input_tokens": 50,
                        "cache_read_input_tokens": 10,
                    },
                ),
            ],
        )

        td2 = make_task_dir(
            tasks_root,
            "task-mm2",
            status="failed",
            coder="claude",
            model="sonnet",
            cwd="/proj-z",
        )
        write_events(
            td2,
            [
                ev(ts=window, kind="session_started", session_id="sm2"),
                ev(ts=window, kind="error"),
            ],
        )

        # (claude, opus) → 1 task, success
        td3 = make_task_dir(
            tasks_root,
            "task-mm3",
            status="closed",
            coder="claude",
            model="opus",
            cwd="/proj-y",
        )
        write_events(
            td3,
            [
                ev(ts=window, kind="session_started", session_id="sm3"),
                ev(
                    ts=window,
                    kind="tool_result",
                    tool_name="Read",
                    usage={"output_tokens": 200, "input_tokens": 100},
                ),
            ],
        )

        # null coder → "unknown"
        td4 = make_task_dir(
            tasks_root, "task-mm4", status="closed", coder="", model="", cwd="/proj-y"
        )
        write_events(
            td4,
            [
                ev(ts=window, kind="session_started", session_id="sm4"),
                ev(
                    ts=window,
                    kind="tool_result",
                    tool_name="Write",
                    usage={"output_tokens": 100, "input_tokens": 50},
                ),
            ],
        )

        app = create_app()

        async def _run() -> dict:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                r = await client.get("/api/analytics/summary")
                return r.json()

        data = asyncio.run(_run())

        # by_model
        by_model_map = {bm["coder"]: {bm["model"]: bm} for bm in data["by_model"]}
        import pprint

        pprint.pprint(data["by_model"])
        import pprint

        pprint.pprint(by_model_map)
        import sys

        sys.stdout.flush()

        # claude + sonnet: total=2, success_rate=0.5
        sonnet_row = by_model_map["claude"]["sonnet"]
        assert sonnet_row["total"] == 2
        assert sonnet_row["success_rate"] == pytest.approx(0.5, abs=0.01)
        assert (
            sonnet_row["output_tokens"] == 300
        )  # task-mm1 only (task-mm2 has no usage)

        # claude + opus: total=1, success_rate=1.0
        opus_row = by_model_map["claude"]["opus"]
        assert opus_row["total"] == 1
        assert opus_row["success_rate"] == 1.0

        # unknown + unknown: total=1
        um_row = by_model_map["unknown"]["unknown"]
        assert um_row["total"] == 1

        # by_project
        by_proj_map = {bp["cwd"]: bp for bp in data["by_project"]}

        # /proj-y: 3 total (task-mm1, task-mm3, task-mm4), 2 success
        profy = by_proj_map["/proj-y"]
        assert profy["total"] == 3
        assert profy["success_rate"] == pytest.approx(2 / 3, abs=0.01)
        assert profy["output_tokens"] == 300 + 200 + 100  # 600

        # /proj-z: 1 total (task-mm2), 0 success
        profz = by_proj_map["/proj-z"]
        assert profz["total"] == 1
        assert profz["success_rate"] == 0.0


class TestSummaryThroughputBuckets:
    """Test 4: throughput bucket_size == 'hour' for days=2 and 'day' for days=7."""

    def test_bucket_size_day_for_days_7(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        _reset_analytics_cache(monkeypatch)
        tasks_root = tmp_path / "tasks"

        window = _make_window_day(2)

        td1 = make_task_dir(tasks_root, "task-bs1", status="closed", cwd="/p")
        write_events(
            td1,
            [
                ev(ts=window, kind="session_started", session_id="sb1"),
                ev(ts=window, kind="tool_result", usage={"output_tokens": 10}),
            ],
        )

        app = create_app()

        async def _run(d: int) -> dict:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                r = await client.get(f"/api/analytics/summary?days={d}")
                return r.json()

        d7 = asyncio.run(_run(7))
        assert d7["throughput"]["bucket_size"] == "day"
        assert len(d7["throughput"]["buckets"]) > 0
        b = d7["throughput"]["buckets"][0]
        assert b["success"] >= 1

        d2 = asyncio.run(_run(2))
        assert d2["throughput"]["bucket_size"] == "hour"
        assert len(d2["throughput"]["buckets"]) > 0
        b2 = d2["throughput"]["buckets"][0]
        # For days=2 (<=3), buckets are hourly
        assert ":" in b2["bucket"]  # ISO hour format includes time

        d0 = asyncio.run(_run(0))
        assert d0["throughput"]["bucket_size"] == "day"


class TestSummaryDaysClamping:
    """Test 5: days clamping — 9999 → 365, window_days echoes."""

    def test_days_clamping(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        tasks_root = tmp_path / "tasks"

        window = _make_window_day(2)

        td1 = make_task_dir(tasks_root, "task-cls1", status="closed", cwd="/p")
        write_events(
            td1,
            [
                ev(ts=window, kind="session_started", session_id="sc1"),
            ],
        )

        app = create_app()

        async def _run(d: int) -> dict:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                r = await client.get(f"/api/analytics/summary?days={d}")
                return r.json()

        # days=9999 → clamped to 365
        d9999 = asyncio.run(_run(9999))
        assert d9999["window_days"] == 365

        # days=366 → clamped to 365
        d366 = asyncio.run(_run(366))
        assert d366["window_days"] == 365

        # days=7 → as-is
        d7 = asyncio.run(_run(7))
        assert d7["window_days"] == 7

        # days=0 → all time, echoes 0
        d0 = asyncio.run(_run(0))
        assert d0["window_days"] == 0
