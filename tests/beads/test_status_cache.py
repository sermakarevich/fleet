"""Tests for the single-flight, TTL-cached beads status map (beads/status_cache.py)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from fleet.beads import status_cache
from fleet.beads.client import BdError


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


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    status_cache._beads_map_cache.clear()
    status_cache._beads_list_call_count = 0
    yield
    status_cache._beads_map_cache.clear()
    status_cache._beads_list_call_count = 0


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
