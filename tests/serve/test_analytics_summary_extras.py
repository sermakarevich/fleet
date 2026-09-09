"""Tests for analytics extras and token stats (unit under test: serve/analytics/summary.py)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
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
        td1 = make_task_dir(tasks_root, "task-hist1", status="closed", coder="", model="", cwd="/p")
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
        td2 = make_task_dir(tasks_root, "task-hist2", status="closed", coder="", model="", cwd="/p")
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
        # Use a different hour to avoid collision (the window hour moves with the clock).
        other_hour = (window_dt.hour + 5) % 24
        tuesday_dt = window_dt.replace(hour=other_hour)
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
        assert heatmap[td2_wd][other_hour] == 1

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
        write_events(td_cp, [ev(ts=ts, kind="session_started", session_id="cp")])
        # Context pressure is outcome-driven from attempts.jsonl (no marker file).
        (td_cp / "attempts.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"event": "start", "n": 1, "ts": ts}),
                    json.dumps(
                        {
                            "event": "end",
                            "n": 1,
                            "ts": ts,
                            "outcome": "context_pressure",
                            "exit_code": None,
                            "reason": "context limit",
                            "action": "release",
                        }
                    ),
                ]
            )
            + "\n",
            "utf-8",
        )

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

        td = make_task_dir(tasks_root, "task-tok", status="closed", cwd="/p", created_at=window)
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
