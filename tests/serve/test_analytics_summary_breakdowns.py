"""Tests for analytics breakdowns (unit under test: serve/analytics/summary.py)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fleet.serve.app import create_app
from tests.serve.conftest import (
    _make_window_day,
    _patch_no_beads,
    _reset_analytics_cache,
    ev,
    make_task_dir,
    write_events,
)


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
        assert sonnet_row["output_tokens"] == 300  # task-mm1 only (task-mm2 has no usage)

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
