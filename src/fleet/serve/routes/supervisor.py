"""Supervisor status and pause/resume REST routes (FR-42)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.config import load as load_config
from fleet.serve.stats import fleet_home as get_fleet_home


def _read_pid_info(home: Path) -> tuple[int | None, str | None]:
    pid_file = home / ".supervisor.pid"
    if not pid_file.exists():
        return None, None
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
        try:
            data = json.loads(text)
            pid = int(data.get("pid", 0)) or None
            started_at = data.get("started_at")
            return pid, started_at
        except (ValueError, json.JSONDecodeError):
            pid = int(text) if text.isdigit() else None
            return pid, None
    except OSError:
        return None, None


def _count_active(home: Path) -> int:
    tasks_dir = home / "tasks"
    if not tasks_dir.is_dir():
        return 0
    count = 0
    for task_dir in tasks_dir.iterdir():
        if not task_dir.is_dir():
            continue
        task_file = task_dir / "task.json"
        if not task_file.exists():
            continue
        try:
            data = json.loads(task_file.read_text(encoding="utf-8"))
            if data.get("status") == "in_progress":
                count += 1
        except (OSError, json.JSONDecodeError):
            continue
    return count


def create_supervisor_router() -> APIRouter:
    router = APIRouter(prefix="/api/supervisor")

    @router.get("")
    async def get_supervisor_status() -> JSONResponse:
        home = get_fleet_home()
        cfg = load_config(home / "runtime.toml")
        pid, started_at = _read_pid_info(home)
        active_count = _count_active(home)
        paused = (home / ".pause").exists()
        max_concurrent = cfg.max_concurrent
        return JSONResponse({
            "pid": pid,
            "started_at": started_at,
            "max_concurrent": max_concurrent,
            "active_count": active_count,
            "free_slots": max(0, max_concurrent - active_count),
            "paused": paused,
        })

    @router.post("/pause")
    async def pause_supervisor() -> JSONResponse:
        home = get_fleet_home()
        (home / ".pause").touch()
        return JSONResponse({"paused": True})

    @router.post("/resume")
    async def resume_supervisor() -> JSONResponse:
        home = get_fleet_home()
        pause_file = home / ".pause"
        if pause_file.exists():
            pause_file.unlink()
        return JSONResponse({"paused": False})

    return router
