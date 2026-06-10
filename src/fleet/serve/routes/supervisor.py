"""Supervisor status and pause/resume REST routes (FR-42)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.config import load as load_config
from fleet.daemon import Daemon, DaemonSpec, _pid_alive, code_fingerprint, python_module_argv
from fleet.schemas import LOG_ROOT, SHUTDOWN_GRACE_SEC
from fleet.serve.stats import fleet_home as get_fleet_home


def _read_pid_info(home: Path) -> tuple[int | None, str | None, str | None]:
    pid_file = home / ".supervisor.pid"
    if not pid_file.exists():
        return None, None, None
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
        try:
            data = json.loads(text)
            pid = int(data.get("pid", 0)) or None
            started_at = data.get("started_at")
            version_fingerprint = data.get("version_fingerprint")
            return pid, started_at, version_fingerprint
        except (ValueError, json.JSONDecodeError):
            pid = int(text) if text.isdigit() else None
            return pid, None, None
    except OSError:
        return None, None, None


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
        pid, started_at, stored_fp = _read_pid_info(home)
        running = pid is not None and _pid_alive(pid)
        active_count = _count_active(home) if running else 0
        paused = (home / ".pause").exists()
        max_concurrent = cfg.max_concurrent
        current_fp = code_fingerprint()
        stale = stored_fp is not None and stored_fp != current_fp
        return JSONResponse({
            "pid": pid,
            "started_at": started_at,
            "running": running,
            "max_concurrent": max_concurrent,
            "active_count": active_count,
            "free_slots": max(0, max_concurrent - active_count),
            "paused": paused,
            "version_fingerprint": stored_fp,
            "stale": stale,
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

    @router.post("/restart")
    async def restart_supervisor() -> JSONResponse:
        home = get_fleet_home()
        log_root = Path(LOG_ROOT)
        if not log_root.is_absolute():
            log_root = home / log_root
        spec = DaemonSpec(
            name="supervisor",
            pidfile=home / ".supervisor.pid",
            logfile=log_root / "supervisor.daemon.log",
            argv=python_module_argv("run", "foreground"),
            cwd=home,
            stop_timeout=float(SHUTDOWN_GRACE_SEC + 5),
            extra={},
        )
        daemon = Daemon(spec)
        result = await asyncio.to_thread(daemon.restart)
        pid_data = daemon.read_pidfile() or {}
        return JSONResponse({
            "pid": result.pid,
            "alive": result.alive,
            "started_at": pid_data.get("started_at"),
        })

    return router
