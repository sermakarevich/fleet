"""Supervisor status and pause/resume REST routes (FR-42)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.observability.daemon import restart, supervisor_spec
from fleet.observability.pidfile import read as read_pid_record
from fleet.observability.process import ServiceRegistry
from fleet.serve.api.models import PauseResponse, RestartResponse, SupervisorResponse
from fleet.serve.auth import HTTP_AUTH
from fleet.state.config_file import load as load_config
from fleet.state.paths import fleet_home as get_fleet_home
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api/supervisor", dependencies=[HTTP_AUTH])


def _count_active(fleet_home: Path) -> int:
    """In-progress tasks, counted only when the supervisor is alive."""
    rows = TaskIndex(fleet_home).iter_meta()
    return sum(1 for _, raw in rows if raw.get("status") == "in_progress")


def _supervisor_snapshot() -> dict:
    """Supervisor liveness payload (runs in a thread; reads pid/task files)."""
    fleet_home = get_fleet_home()
    config = load_config(fleet_home / "runtime.toml")
    svc = ServiceRegistry(fleet_home).status("supervisor")
    running = svc.alive
    active_count = _count_active(fleet_home) if running else 0
    paused = (fleet_home / ".pause").exists()
    max_concurrent = config.max_concurrent
    return {
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


def _set_paused(paused: bool) -> None:
    """Create or remove the .pause flag file (runs in a thread)."""
    pause_file = get_fleet_home() / ".pause"
    if paused:
        pause_file.touch()
    elif pause_file.exists():
        pause_file.unlink()


@router.get("", response_model=SupervisorResponse)
async def get_supervisor_status() -> JSONResponse:
    """Supervisor liveness, slot counts, pause flag, code staleness (FR-42)."""
    snapshot = await asyncio.to_thread(_supervisor_snapshot)
    return JSONResponse(snapshot)


@router.post("/pause", response_model=PauseResponse)
async def pause_supervisor() -> JSONResponse:
    """Pause claiming (running workers finish)."""
    await asyncio.to_thread(_set_paused, True)
    return JSONResponse({"paused": True})


@router.post("/resume", response_model=PauseResponse)
async def resume_supervisor() -> JSONResponse:
    """Clear the pause flag."""
    await asyncio.to_thread(_set_paused, False)
    return JSONResponse({"paused": False})


@router.post("/restart", response_model=RestartResponse)
async def restart_supervisor() -> JSONResponse:
    """Restart the supervisor daemon; returns the new pid facts."""
    fleet_home = get_fleet_home()
    spec = supervisor_spec(fleet_home)
    result = await asyncio.to_thread(restart, spec)
    record = read_pid_record(spec.pidfile)
    return JSONResponse(
        {
            "pid": result.pid,
            "alive": result.alive,
            "started_at": record.started_at if record is not None else None,
        }
    )
