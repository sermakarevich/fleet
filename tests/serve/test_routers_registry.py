"""Tests for the serve/api ROUTERS registry (ADR 0006 rule 3)."""

from __future__ import annotations

import importlib
from pathlib import Path

from fastapi import APIRouter

from fleet.serve.api import ROUTERS
from fleet.serve.app import create_app

API_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "fleet" / "serve" / "api"


def _api_modules() -> list[str]:
    """Importable serve.api.* module names, excluding the registry itself."""
    return sorted(
        f"fleet.serve.api.{p.stem}" for p in API_DIR.glob("*.py") if p.stem not in ("__init__",)
    )


def test_every_router_module_is_registered() -> None:
    """Every serve/api module defining `router` appears in ROUTERS (identity)."""
    for name in _api_modules():
        mod = importlib.import_module(name)
        router = getattr(mod, "router", None)
        if router is None:
            continue
        assert isinstance(router, APIRouter), f"{name}.router is not an APIRouter"
        assert any(r is router for r in ROUTERS), f"{name}.router missing from ROUTERS"


def test_routers_list_is_unique() -> None:
    """ROUTERS holds distinct router objects."""
    assert len(ROUTERS) > 0
    assert len({id(r) for r in ROUTERS}) == len(ROUTERS)


def test_task_routers_stay_small() -> None:
    """Split task routers stay at most 120 lines (ADR 0006 bead 9)."""
    for path in sorted(API_DIR.glob("tasks_*.py")):
        lines = path.read_text(encoding="utf-8").count("\n") + 1
        assert lines <= 120, f"{path.name} has {lines} lines (>120)"


def test_app_serves_registered_routes(tmp_path, monkeypatch) -> None:
    """create_app exposes every registered router path (spot check)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()
    paths = {getattr(r, "path", "") for r in app.routes}
    for expected in (
        "/api/tasks",
        "/api/tasks/{task_id}",
        "/api/tasks/{task_id}/kill",
        "/api/tasks/{task_id}/unblock",
        "/api/tasks/{task_id}/events",
        "/api/tasks/{task_id}/artifacts/state",
        "/api/beads",
        "/api/supervisor",
        "/api/config",
        "/api/analytics/summary",
        "/api/search",
        "/api/schedules",
        "/api/schedules/{schedule_id}",
        "/api/chat/questions",
        "/healthz",
    ):
        assert expected in paths, f"{expected} not served"
