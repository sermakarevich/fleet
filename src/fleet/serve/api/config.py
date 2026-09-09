"""Config read and write REST routes (FR-43)."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.coders import get_coder
from fleet.core.config import RuntimeConfig
from fleet.serve.api.models import ConfigView
from fleet.state.config_file import load as load_config
from fleet.state.config_file import write as write_config
from fleet.state.paths import fleet_home as get_fleet_home

router = APIRouter(prefix="/api")


def _read_config(config_path: Path) -> RuntimeConfig:
    """Load runtime.toml (runs in a thread)."""
    return load_config(config_path)


def _write_config(config_path: Path, updates: dict[str, str]) -> RuntimeConfig:
    """Write runtime.toml updates atomically (runs in a thread)."""
    return write_config(config_path, updates)


@router.get("/config", response_model=ConfigView)
async def get_config() -> JSONResponse:
    """Full RuntimeConfig as JSON (FR-43)."""
    fleet_home = get_fleet_home()
    config = await asyncio.to_thread(_read_config, fleet_home / "runtime.toml")
    return JSONResponse(asdict(config))


@router.put("/config", response_model=ConfigView)
async def put_config(request: Request) -> JSONResponse:
    """Update runtime.toml atomically; rejects unknown coders/values."""
    fleet_home = get_fleet_home()
    body = await request.json()
    updates = {k: str(v) for k, v in body.items()}
    if "coder" in updates:
        try:
            get_coder(updates["coder"])
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
    try:
        new_cfg = await asyncio.to_thread(_write_config, fleet_home / "runtime.toml", updates)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse(asdict(new_cfg))
