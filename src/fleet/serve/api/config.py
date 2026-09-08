"""Config read and write REST routes (FR-43)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.coders import get_coder
from fleet.state.config_file import load as load_config
from fleet.state.config_file import write as write_config
from fleet.state.paths import fleet_home as get_fleet_home

router = APIRouter(prefix="/api")


@router.get("/config")
async def get_config() -> JSONResponse:
    """Full RuntimeConfig as JSON (FR-43)."""
    home = get_fleet_home()
    cfg = load_config(home / "runtime.toml")
    return JSONResponse(asdict(cfg))


@router.put("/config")
async def put_config(request: Request) -> JSONResponse:
    """Update runtime.toml atomically; rejects unknown coders/values."""
    home = get_fleet_home()
    body = await request.json()
    updates = {k: str(v) for k, v in body.items()}
    if "coder" in updates:
        try:
            get_coder(updates["coder"])
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
    try:
        new_cfg = write_config(home / "runtime.toml", updates)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse(asdict(new_cfg))
