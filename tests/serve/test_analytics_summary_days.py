"""Tests for analytics summary day windows (unit under test: serve/analytics/summary.py)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app
from tests.serve.conftest import (
    _make_future_days,
    _make_window_day,
    _patch_no_beads,
    _reset_analytics_cache,
    ev,
    make_task_dir,
    write_events,
)


def _make_now() -> str:
    """Return current ISO timestamp with tz."""
    return datetime.now(tz=UTC).isoformat()


class TestSummaryDefaultDays:
    """Test 1: default days=7 — KPIs are correct."""

    def test_kpis_completed_success_rate_output_tokens_avg_segments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        tasks_root = tmp_path / "tasks"

        _make_now()
        window = _make_window_day(1)

        # Task 1: closed success with session_ids and output_tokens (within window)
        td1 = make_task_dir(tasks_root, "task-1", status="closed", cwd="/proj-a", created_at=window)
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

        # Also journal a success/release attempt on task-5 (noclose signal
        # comes from attempts history, not a marker file).
        (td5 / "attempts.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"event": "start", "n": 1, "ts": window}),
                    json.dumps(
                        {
                            "event": "end",
                            "n": 1,
                            "ts": window,
                            "outcome": "success",
                            "exit_code": 0,
                            "reason": "rc=0 without close",
                            "action": "release",
                        }
                    ),
                ]
            )
            + "\n",
            "utf-8",
        )

        # Task 6: rate limited completed task
        td6 = make_task_dir(tasks_root, "task-6", status="closed", cwd="/proj-b", created_at=window)
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

        # total_output_tokens: 100 + 200 + 0 + 50 + 300 = 650
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
    """Test 2: days=1 excludes old completions; days=365 includes everything."""

    def test_days_1_excludes_old_completion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        _reset_analytics_cache(monkeypatch)
        tasks_root = tmp_path / "tasks"

        _make_now()
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
        d365 = asyncio.run(_run(365))

        # days=1: only task-recent is completed in window
        assert d1["kpis"]["completed"] == 1
        assert d1["kpis"]["total_output_tokens"] == 500

        # days=365: wide window — both task-old and task-recent are completed
        assert d365["kpis"]["completed"] == 2
        assert d365["kpis"]["total_output_tokens"] == 1500

        # active is never filtered
        assert d1["kpis"]["active_now"] == 1
        assert d365["kpis"]["active_now"] == 1


class TestSummaryDaysClamping:
    """Test 5: days bounds — out-of-range values are rejected with 422."""

    def test_days_bounds(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

        async def _run(d: int) -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.get(f"/api/analytics/summary?days={d}")

        # days=9999 and days=366 exceed the 365-day max -> 422
        assert asyncio.run(_run(9999)).status_code == 422
        assert asyncio.run(_run(366)).status_code == 422

        # days=0 is below the 1-day min -> 422
        assert asyncio.run(_run(0)).status_code == 422

        # days=7 -> as-is
        d7 = asyncio.run(_run(7))
        assert d7.status_code == 200
        assert d7.json()["window_days"] == 7
