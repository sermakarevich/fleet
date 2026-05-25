"""FastAPI application factory for `fleet serve` (FR-48, FR-49)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from fleet.config import load as load_config
from fleet.serve.stats import fleet_home


@dataclass
class AppState:
    fleet_home: Path
    config: Any
    config_mtime: float | None


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    home = fleet_home()
    runtime_toml = home / "runtime.toml"
    cfg = load_config(runtime_toml)
    mtime: float | None = runtime_toml.stat().st_mtime if runtime_toml.exists() else None
    app.state.fleet_state = AppState(fleet_home=home, config=cfg, config_mtime=mtime)
    yield


def create_app() -> FastAPI:
    """Create and configure the fleet FastAPI application."""
    app = FastAPI(lifespan=_lifespan)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "fleet_home": str(fleet_home())})

    return app
