"""Tests for beads/status_cache.py: BdError fallback (mq57m) and single-flight TTL (0714c).

When `bd list` fails the cache must keep serving the last-known good map
(never silently fall back to raw task.json statuses) and report
beads_available=False with the error string.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from fleet.beads import status_cache
from fleet.beads import status_cache as status_cache_mod
from fleet.beads.client import BdError
from fleet.beads.status_cache import BeadsSnapshot, get_beads_snapshot
from fleet.serve.app import create_app


@pytest.fixture(autouse=True)
def _clear_module_cache() -> None:
    """Clear module-level cache state before and after every test."""
    for d in (
        status_cache._beads_map_cache,
        status_cache._beads_last_good,
        status_cache._beads_last_error,
        status_cache._beads_last_ok_at,
        status_cache._beads_last_warn_at,
    ):
        d.clear()
    status_cache._beads_list_call_count = 0
    yield
    for d in (
        status_cache._beads_map_cache,
        status_cache._beads_last_good,
        status_cache._beads_last_error,
        status_cache._beads_last_ok_at,
        status_cache._beads_last_warn_at,
    ):
        d.clear()
    status_cache._beads_list_call_count = 0


def _reset_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear all module-level beads cache state so tests are isolated."""
    for name in (
        "fleet.beads.status_cache._beads_map_cache",
        "fleet.beads.status_cache._beads_last_good",
        "fleet.beads.status_cache._beads_last_error",
        "fleet.beads.status_cache._beads_last_ok_at",
        "fleet.beads.status_cache._beads_last_warn_at",
    ):
        monkeypatch.setattr(name, {})
    monkeypatch.setattr("fleet.beads.status_cache._beads_list_call_count", 0)


def _bead_row(bead_id: str, status: str = "closed") -> dict:
    return {"id": bead_id, "status": status, "created_at": "2024-01-01T00:00:00Z"}


def test_second_call_bderror_returns_first_map_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First call ok, second call BdError -> first map served, available False."""
    _reset_cache(monkeypatch)
    good_map = [_bead_row("fleet-aaa")]
    monkeypatch.setattr(status_cache_mod.beads_client, "list_all", MagicMock(return_value=good_map))
    first = get_beads_snapshot(tmp_path)
    assert first.available is True
    assert first.error is None
    assert first.stale is False
    assert set(first.map or {}) == {"fleet-aaa"}

    monkeypatch.setattr(
        status_cache_mod.beads_client,
        "list_all",
        MagicMock(side_effect=BdError("bd hung")),
    )
    # Expire the TTL entry so the second call really shells out (and fails).
    status_cache_mod._beads_map_cache[str(tmp_path)] = (0.0, first.map)
    second = get_beads_snapshot(tmp_path)
    assert second.map == first.map
    assert second.available is False
    assert second.stale is True
    assert second.error == "bd hung"


def test_bderror_without_good_map_returns_none_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BdError on the very first call -> map None, available False, error set."""
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        status_cache_mod.beads_client,
        "list_all",
        MagicMock(side_effect=BdError("no bd binary")),
    )
    snap = get_beads_snapshot(tmp_path)
    assert snap.map is None
    assert snap.available is False
    assert snap.error == "no bd binary"
    assert isinstance(snap, BeadsSnapshot)


def test_recovery_clears_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful call after a failure clears the recorded error."""
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        status_cache_mod.beads_client,
        "list_all",
        MagicMock(side_effect=BdError("boom")),
    )
    assert get_beads_snapshot(tmp_path).available is False
    monkeypatch.setattr(
        status_cache_mod.beads_client,
        "list_all",
        MagicMock(return_value=[_bead_row("fleet-bbb", "open")]),
    )
    status_cache_mod._beads_map_cache[str(tmp_path)] = (0.0, None)
    snap = get_beads_snapshot(tmp_path)
    assert snap.available is True
    assert snap.error is None
    assert set(snap.map or {}) == {"fleet-bbb"}


def test_api_beads_down_marks_stale_statuses_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """list_all raising -> envelope carries beads_available false; a stale
    in_progress task.json row is served as unknown, never as running."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = tmp_path / "tasks" / "task-stale"
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(
        json.dumps(
            {
                "id": "task-stale",
                "title": "Stale",
                "status": "in_progress",
                "created_at": "2024-01-01T00:00:00Z",
                "cwd": "/repo",
                "coder": "claude",
                "model": "sonnet",
            }
        )
    )
    closed_dir = tmp_path / "tasks" / "task-done"
    closed_dir.mkdir(parents=True)
    (closed_dir / "task.json").write_text(
        json.dumps(
            {
                "id": "task-done",
                "title": "Done",
                "status": "closed",
                "created_at": "2024-01-02T00:00:00Z",
                "cwd": "/repo",
                "coder": "claude",
                "model": "sonnet",
            }
        )
    )
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        status_cache_mod.beads_client,
        "list_all",
        MagicMock(side_effect=BdError("dolt locked")),
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
    assert data["beads_available"] is False
    assert data["beads_error"] == "dolt locked"
    by_id = {t["id"]: t for t in data["tasks"]}
    assert by_id["task-stale"]["status"] == "unknown"
    assert by_id["task-done"]["status"] == "closed"


# --- single-flight / TTL tests (fleet-0714c) ---


def _full_entry(status: str) -> dict:
    return {
        "status": status,
        "created_at": None,
        "priority": None,
        "title": None,
        "description": None,
        "notes": None,
        "metadata": {},
    }


def test_concurrent_refresh_is_single_flight(tmp_path: Path) -> None:
    """Two threads racing a slow refresh produce exactly 1 subprocess call.

    The thread that loses the race must return immediately with the
    last-known map instead of blocking behind the in-flight refresh.
    """
    started = threading.Event()
    release = threading.Event()

    def slow_list_all(fleet_home: Path) -> list[dict]:
        started.set()
        release.wait(timeout=5)
        return [{"id": "fleet-1", "status": "open"}]

    # Seed a last-known map so the second (losing) caller has something to return.
    status_cache._beads_map_cache[str(tmp_path)] = (
        time.monotonic() - 1,  # already expired
        {"fleet-0": {"status": "closed"}},
    )

    results: dict[str, dict | None] = {}

    def first_caller() -> None:
        results["first"] = status_cache.get_beads_status_map(tmp_path)

    def second_caller() -> None:
        started.wait(timeout=5)
        results["second"] = status_cache.get_beads_status_map(tmp_path)
        release.set()

    with patch("fleet.beads.status_cache.beads_client.list_all", side_effect=slow_list_all):
        t1 = threading.Thread(target=first_caller)
        t2 = threading.Thread(target=second_caller)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

    assert status_cache._beads_list_call_count == 1
    assert results["second"] == {"fleet-0": {"status": "closed"}}
    assert results["first"] == {"fleet-1": _full_entry("open")}


def test_bd_error_keeps_previous_map(tmp_path: Path) -> None:
    """A BdError after a successful call keeps returning the previous map."""
    with patch(
        "fleet.beads.status_cache.beads_client.list_all",
        return_value=[{"id": "fleet-1", "status": "open"}],
    ):
        first = status_cache.get_beads_status_map(tmp_path)
    assert first == {"fleet-1": _full_entry("open")}

    # Force expiry so the next call actually triggers a refresh attempt.
    key = str(tmp_path)
    expires_at, value = status_cache._beads_map_cache[key]
    status_cache._beads_map_cache[key] = (time.monotonic() - 1, value)

    with patch("fleet.beads.status_cache.beads_client.list_all", side_effect=BdError("boom")):
        second = status_cache.get_beads_status_map(tmp_path)

    assert second == {"fleet-1": _full_entry("open")}


def test_bd_error_with_no_previous_value_returns_none(tmp_path: Path) -> None:
    with patch("fleet.beads.status_cache.beads_client.list_all", side_effect=BdError("boom")):
        result = status_cache.get_beads_status_map(tmp_path)
    assert result is None
    assert status_cache._beads_list_call_count == 1


def test_refresh_beads_status_map_forces_refresh(tmp_path: Path) -> None:
    with patch(
        "fleet.beads.status_cache.beads_client.list_all",
        return_value=[{"id": "fleet-1", "status": "open"}],
    ):
        result = status_cache.refresh_beads_status_map(tmp_path)
    assert result == {"fleet-1": _full_entry("open")}
    assert status_cache._beads_list_call_count == 1
