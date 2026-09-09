"""Snapshot test: /api/analytics/summary output never changes on refactor.

Rebuilds the deterministic fixture fleet_home, runs ``compute_summary(fleet_home, 0)``
with beads unavailable, and asserts byte-equality with
``tests/fixtures/analytics_summary_snapshot.json`` (recorded from the
pre-registry implementation). days=0 plus fixed timestamps keep the output
free of clock dependence.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch as _patch

import pytest

from fleet.serve.analytics import records as records_mod
from fleet.serve.analytics.summary import compute_summary
from tests.serve.analytics.fixture_home import build_fixture_home

_SNAPSHOT = Path(__file__).resolve().parents[2] / "fixtures" / "analytics_summary_snapshot.json"


def test_summary_matches_recorded_snapshot(tmp_path: Path) -> None:
    """compute_summary(fleet_home, 0) equals the recorded fixture output."""
    records_mod._events_cache.clear()
    build_fixture_home(tmp_path)
    with _patch("fleet.beads.cache.get_beads_status_map", MagicMock(return_value=None)):
        actual = compute_summary(tmp_path, 0)
    expected = json.loads(_SNAPSHOT.read_text("utf-8"))
    assert actual == expected


def test_snapshot_fixture_has_every_section() -> None:
    """The recorded fixture covers the whole response shape."""
    expected = json.loads(_SNAPSHOT.read_text("utf-8"))
    assert set(expected) == {
        "window_days",
        "kpis",
        "throughput",
        "token_throughput",
        "by_model",
        "by_project",
        "tools",
        "context_histogram",
        "heatmap",
        "errors_recent",
        "rate_limits",
    }
    assert len(expected["heatmap"]) == 7
    assert pytest.approx(expected["kpis"]["success_rate"]) == 0.6
