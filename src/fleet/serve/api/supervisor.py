"""Supervisor status and pause/resume REST routes (FR-42)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.observability.daemon import read_pidfile, restart, supervisor_spec
from fleet.observability.process import ServiceRegistry
from fleet.serve.api.models import PauseResponse, RestartResponse, SupervisorResponse
from fleet.state.config_file import load as load_config
from fleet.state.paths import fleet_home as get_fleet_home
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api/supervisor")


def _count_active(home: Path) -> int:
    """In-progress tasks, counted only when the supervisor is alive."""
    return sum(1 for _, raw in TaskIndex(home).iter_meta() if raw.get("status") == "in_progress")


@router.get("", response_model=SupervisorResponse)
async def get_supervisor_status() -> JSONResponse:
    """Supervisor liveness, slot counts, pause flag, code staleness (FR-42)."""
    home = get_fleet_home()
    cfg = load_config(home / "runtime.toml")
    svc = ServiceRegistry(home).status("supervisor")
    running = svc.alive
    active_count = _count_active(home) if running else 0
    paused = (home / ".pause").exists()
    max_concurrent = cfg.max_concurrent
    return JSONResponse(
        {
            "pid": svc.pid,
            "started_at": svc.since,
            "running": running,
            "max_concurrent": max_concurrent,
            "active_count": active_count,
            "free_slots": max(0, max_concurrent - active_count),
            "paused": paused,
            "version_fingerprint": svc.fingerprint,
            "stale": svc.stale,
        }
    )


@router.post("/pause", response_model=PauseResponse)
async def pause_supervisor() -> JSONResponse:
    """Pause claiming (running workers finish)."""
    home = get_fleet_home()
    (home / ".pause").touch()
    return JSONResponse({"paused": True})


@router.post("/resume", response_model=PauseResponse)
async def resume_supervisor() -> JSONResponse:
    """Clear the pause flag."""
    home = get_fleet_home()
    pause_file = home / ".pause"
    if pause_file.exists():
        pause_file.unlink()
    return JSONResponse({"paused": False})


@router.post("/restart", response_model=RestartResponse)
async def restart_supervisor() -> JSONResponse:
    """Restart the supervisor daemon; returns the new pid facts."""
    home = get_fleet_home()
    spec = supervisor_spec(home)
    result = await asyncio.to_thread(restart, spec)
    pid_data = read_pidfile(spec) or {}
    return JSONResponse(
        {
            "pid": result.pid,
            "alive": result.alive,
            "started_at": pid_data.get("started_at"),
        }
    )
