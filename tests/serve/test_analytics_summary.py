"""Tests for GET /api/analytics/summary endpoint."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from fleet.serve.app import create_app


def _patch_no_beads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkey-patch get_beads_status_map to return None (skip beads in tests, per spec: 'bd unavailable → raw statuses used')."""
    monkeypatch.setattr(
        "fleet.beads.cache.get_beads_status_map",
        MagicMock(return_value=None),
    )


def _reset_analytics_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the state.events mtime+size cache that persists across tests."""
    import fleet.state.events as events_mod

    monkeypatch.setattr(events_mod, "_cache", {})


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
    """Write event lines to attempts/1/events.jsonl."""
    attempt_dir = td / "attempts" / "1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "events.jsonl").write_text("\n".join(lines) + "\n", "utf-8")


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
    return (datetime.now(tz=UTC) - timedelta(days=n_days)).isoformat()


def _make_now() -> str:
    """Return current ISO timestamp with tz."""
    return datetime.now(tz=UTC).isoformat()


def _make_window_day(hours_ago: int = 6) -> str:
    """Return a timestamp hours_ago ago — comfortably within any 1–7 day window."""
    return (datetime.now(tz=UTC) - timedelta(hours=hours_ago)).isoformat()


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
        # Build nested map correctly (dict comprehension overwrites — use loop instead)
        by_model_map: dict[str, dict[str, dict]] = {}
        for bm in data["by_model"]:
            by_model_map.setdefault(bm["coder"], {})[bm["model"]] = bm

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

        # /proj-y: 3 total (task-mm1, task-mm3, task-mm4), all success
        profy = by_proj_map["/proj-y"]
        assert profy["total"] == 3
        assert profy["success_rate"] == 1.0
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
        asyncio.run(_run(0))


class TestSummaryExtras:
    """Test 6: tools, context_histogram, heatmap, errors_recent, rate_limits."""

    def test_tools_reflect_tool_result_counts_and_total(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        _reset_analytics_cache(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        tasks_root = tmp_path / "tasks"

        window = _make_window_day(1)

        # Task A: two tool_result events (Read + Edit)
        td1 = make_task_dir(tasks_root, "task-tools-a", status="closed", cwd="/p")
        write_events(
            td1,
            [
                ev(ts=window, kind="session_started", session_id="t1"),
                ev(ts=window, kind="tool_result", tool_name="Read"),
                ev(ts=window, kind="tool_result", tool_name="Edit"),
            ],
        )

        # Task B: three tool_result events (Read x2, Write x1)
        td2 = make_task_dir(tasks_root, "task-tools-b", status="closed", cwd="/p")
        write_events(
            td2,
            [
                ev(ts=window, kind="session_started", session_id="t2"),
                ev(ts=window, kind="tool_result", tool_name="Read"),
                ev(ts=window, kind="tool_result", tool_name="Read"),
                ev(ts=window, kind="tool_result", tool_name="Write"),
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

        tools = data["tools"]
        # total = 3 Read + 1 Edit + 1 Write = 5
        assert tools["total"] == 5
        rows_by_name = {row["name"]: row["count"] for row in tools["rows"]}
        assert rows_by_name["Read"] == 3
        assert rows_by_name["Edit"] == 1
        assert rows_by_name["Write"] == 1
        assert len(tools["rows"]) == 3

    def test_context_histogram_buckets_peak_tokens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        _reset_analytics_cache(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        tasks_root = tmp_path / "tasks"

        window = _make_window_day(1)

        # Task with peak_context_tokens that falls into 25-50 bucket
        # peak = 50000, limit = 200_000 (unknown coder) -> ratio = 25% -> 25-50 bucket is [25, 50)
        # Actually 25% -> 25-50 bucket: ratio >= 25 -> yes
        # Let's pick peak = 30000 -> ratio = 15% -> 0-25 bucket
        td1 = make_task_dir(
            tasks_root, "task-hist1", status="closed", coder="", model="", cwd="/p"
        )
        write_events(
            td1,
            [
                ev(ts=window, kind="session_started", session_id="h1"),
                ev(
                    ts=window,
                    kind="tool_result",
                    usage={"input_tokens": 30000, "output_tokens": 100},
                ),
            ],
        )

        # Task with peak_context_tokens = 150_000 out of 200_000 -> 75% -> 75-100 bucket
        td2 = make_task_dir(
            tasks_root, "task-hist2", status="closed", coder="", model="", cwd="/p"
        )
        write_events(
            td2,
            [
                ev(ts=window, kind="session_started", session_id="h2"),
                ev(
                    ts=window,
                    kind="tool_result",
                    usage={
                        "input_tokens": 150000,
                        "output_tokens": 200,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
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

        hist = data["context_histogram"]
        buckets = hist["buckets"]
        # total should be 2 (two completed records with peak_context_tokens)
        total = sum(buckets.values())
        assert total == 2
        # Both coders are empty -> unknown coder -> 200k fallback
        # Task 1: 30000/200000 = 15% -> "0-25"
        assert buckets["0-25"] == 1
        # Task 2: 150000/200000 = 75% -> "75-100"
        assert buckets["75-100"] == 1

    def test_heatmap_is_7x24_and_totals_match_event_counts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        _reset_analytics_cache(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        tasks_root = tmp_path / "tasks"

        # Use a timestamp within the window — check weekday dynamically
        window = _make_window_day(6)  # 6 hours ago, within any 1-day window

        window_dt = datetime.fromisoformat(window.replace("Z", "+00:00"))
        wd = window_dt.weekday()  # 0=Mon

        td1 = make_task_dir(tasks_root, "task-hm1", status="closed", cwd="/p")
        write_events(
            td1,
            [
                ev(ts=window, kind="session_started", session_id="hm1"),
                ev(ts=window, kind="tool_result", tool_name="Read"),
                ev(ts=window, kind="tool_result", tool_name="Edit"),
            ],
        )

        # Add an active task too (still counted for heatmap)
        # Use a different hour to avoid collision
        tuesday_dt = window_dt.replace(hour=14)
        tuesday_ts = tuesday_dt.isoformat()
        td2_wd = tuesday_dt.weekday()
        td2 = make_task_dir(tasks_root, "task-hm2", status="in_progress", cwd="/p")
        write_events(
            td2,
            [
                ev(ts=tuesday_ts, kind="session_started", session_id="hm2"),
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

        heatmap = data["heatmap"]
        # Must be 7x24
        assert len(heatmap) == 7
        assert all(len(row) == 24 for row in heatmap)

        # Total events from windowed records:
        # task-hm1: 3 events all at window weekday/hour
        # task-hm2: 1 event at tuesday_dt weekday/hour
        total_heatmap = sum(sum(row) for row in heatmap)
        assert total_heatmap == 4

        # Check the specific indices
        assert heatmap[wd][window_dt.hour] == 3
        assert heatmap[td2_wd][14] == 1

    def test_errors_recent_contains_failed_and_blocked_newest_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        _reset_analytics_cache(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        tasks_root = tmp_path / "tasks"

        # Failed task with older timestamp
        td1 = make_task_dir(tasks_root, "task-err-1", status="failed", cwd="/p")
        old_ts = _make_future_days(3)
        write_events(
            td1,
            [
                ev(ts=old_ts, kind="session_started", session_id="e1"),
            ],
        )

        # Blocked task with newer timestamp
        td2 = make_task_dir(tasks_root, "task-err-2", status="blocked", cwd="/p")
        recent_ts = _make_future_days(1)
        write_events(
            td2,
            [
                ev(ts=recent_ts, kind="session_started", session_id="e2"),
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

        errors = data["errors_recent"]
        # Should have both failed and blocked
        assert len(errors) == 2
        # Newest first: task-err-2 (blocked, 1 day ago) > task-err-1 (failed, 3 days ago)
        assert errors[0]["id"] == "task-err-2"
        assert errors[0]["outcome"] == "blocked"
        assert errors[1]["id"] == "task-err-1"
        assert errors[1]["outcome"] == "failed"
        # Verify all fields present
        assert "title" in errors[0]
        assert "coder" in errors[0]
        assert "model" in errors[0]
        assert "ended_at" in errors[0]

    def test_errors_recent_includes_flagged_closed_tasks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Closed tasks that hit a problem flag surface labeled by the flag."""
        _patch_no_beads(monkeypatch)
        _reset_analytics_cache(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        tasks_root = tmp_path / "tasks"

        ts = _make_window_day(1)

        td_ok = make_task_dir(tasks_root, "task-clean", status="closed", cwd="/p")
        write_events(td_ok, [ev(ts=ts, kind="session_started", session_id="ok")])

        td_nc = make_task_dir(tasks_root, "task-noclose", status="closed", cwd="/p")
        write_events(td_nc, [ev(ts=ts, kind="session_started", session_id="nc")])
        (td_nc / "attempts.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"event": "start", "n": 1, "ts": ts}),
                    json.dumps(
                        {
                            "event": "end",
                            "n": 1,
                            "ts": ts,
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

        td_cp = make_task_dir(tasks_root, "task-ctx", status="closed", cwd="/p")
        write_events(td_cp, [ev(ts=ts, kind="context_pressure", session_id="cp")])

        td_rl = make_task_dir(tasks_root, "task-rl", status="closed", cwd="/p")
        write_events(
            td_rl,
            [ev(ts=ts, kind="rate_limit", rate_info={"status": "rejected"})],
        )

        app = create_app()

        async def _run() -> dict:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                r = await client.get("/api/analytics/summary")
                return r.json()

        data = asyncio.run(_run())

        by_id = {e["id"]: e["outcome"] for e in data["errors_recent"]}
        assert "task-clean" not in by_id
        assert by_id["task-noclose"] == "noclose"
        assert by_id["task-ctx"] == "context_pressure"
        assert by_id["task-rl"] == "rate_limited"

    def test_rate_limits_lists_rejected_event_with_task_id_and_ts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        _reset_analytics_cache(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        tasks_root = tmp_path / "tasks"

        window = _make_window_day(1)

        # Task with a rate_limit rejected event
        td1 = make_task_dir(tasks_root, "task-rl1", status="closed", cwd="/p")
        write_events(
            td1,
            [
                ev(ts=window, kind="session_started", session_id="rl1"),
                ev(ts=window, kind="rate_limit", rate_info={"status": "rejected"}),
            ],
        )

        # Task with a rate_limit accepted event (should NOT appear)
        td2 = make_task_dir(tasks_root, "task-rl2", status="closed", cwd="/p")
        write_events(
            td2,
            [
                ev(ts=window, kind="session_started", session_id="rl2"),
                ev(ts=window, kind="rate_limit", rate_info={"status": "accepted"}),
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

        rl = data["rate_limits"]
        # Only the rejected event should be listed
        assert len(rl) == 1
        assert "ts" in rl[0]
        assert "task_id" in rl[0]
        assert rl[0]["task_id"] == "task-rl1"
        assert rl[0]["ts"] == window


class TestSummaryTokenStats:
    """Token totals KPIs + token_throughput series."""

    def test_token_totals_and_throughput(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_no_beads(monkeypatch)
        _reset_analytics_cache(monkeypatch)
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        tasks_root = tmp_path / "tasks"
        window = _make_window_day(1)

        td = make_task_dir(
            tasks_root, "task-tok", status="closed", cwd="/p", created_at=window
        )
        write_events(
            td,
            [
                ev(ts=window, kind="session_started", session_id="tk1"),
                ev(
                    ts=window,
                    kind="tool_result",
                    tool_name="Read",
                    usage={
                        "output_tokens": 100,
                        "input_tokens": 1000,
                        "cache_creation_input_tokens": 40,
                        "cache_read_input_tokens": 60,
                    },
                ),
            ],
        )

        app = create_app()

        async def _run() -> dict:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                r = await client.get("/api/analytics/summary?days=7")
                return r.json()

        data = asyncio.run(_run())
        kpis = data["kpis"]
        assert kpis["total_output_tokens"] == 100
        assert kpis["total_input_tokens"] == 1000
        assert kpis["total_cache_creation_tokens"] == 40
        assert kpis["total_cache_read_tokens"] == 60

        tt = data["token_throughput"]
        assert tt["bucket_size"] == "day"
        assert len(tt["buckets"]) == 1
        b = tt["buckets"][0]
        assert b["output_tokens"] == 100
        assert b["input_tokens"] == 1000
        assert b["cache_tokens"] == 100  # 40 + 60
