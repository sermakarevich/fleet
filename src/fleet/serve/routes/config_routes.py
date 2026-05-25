"""Config read and write REST routes (FR-43)."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.config import load as load_config, write_atomic
from fleet.serve.stats import fleet_home as get_fleet_home


def create_config_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/config")
    async def get_config() -> JSONResponse:
        home = get_fleet_home()
        cfg = load_config(home / "runtime.toml")
        return JSONResponse(asdict(cfg))

    @router.put("/config")
    async def put_config(request: Request) -> JSONResponse:
        home = get_fleet_home()
        body = await request.json()
        updates = {k: str(v) for k, v in body.items()}
        try:
            new_cfg = write_atomic(home / "runtime.toml", updates)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse(asdict(new_cfg))

    return router
