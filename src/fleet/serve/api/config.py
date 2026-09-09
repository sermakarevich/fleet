"""Config read and write REST routes (FR-43)."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.coders import get_coder
from fleet.core.config import RuntimeConfig
from fleet.core.errors import ConfigError
from fleet.serve.api.models import ConfigView
from fleet.serve.auth import HTTP_AUTH
from fleet.serve.errors import parse_json_body, unprocessable
from fleet.state.config_file import load as load_config
from fleet.state.config_file import write as write_config
from fleet.state.paths import fleet_home as get_fleet_home

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])

_CONFIG_KEYS = frozenset(f.name for f in fields(RuntimeConfig))


def _read_config(config_path: Path) -> RuntimeConfig:
    """Load runtime.toml (runs in a thread)."""
    return load_config(config_path)


def _write_config(config_path: Path, updates: dict[str, Any]) -> RuntimeConfig:
    """Write runtime.toml updates atomically (runs in a thread)."""
    return write_config(config_path, updates)


def _check_updates(body: Any) -> dict[str, Any]:
    """Validated update dict: object body, known keys, known coder."""
    if not isinstance(body, dict):
        raise unprocessable("config body must be a JSON object")
    unknown = sorted(set(body) - _CONFIG_KEYS)
    if unknown:
        raise unprocessable(f"unknown config key(s): {', '.join(unknown)}")
    if "coder" in body:
        try:
            get_coder(body["coder"])
        except ValueError as exc:
            raise unprocessable(str(exc)) from exc
    return body


@router.get("/config", response_model=ConfigView)
async def get_config() -> JSONResponse:
    """Full RuntimeConfig as JSON (FR-43)."""
    fleet_home = get_fleet_home()
    config = await asyncio.to_thread(_read_config, fleet_home / "runtime.toml")
    return JSONResponse(asdict(config))


@router.put("/config", response_model=ConfigView)
async def put_config(request: Request) -> JSONResponse:
    """Update runtime.toml atomically; rejects unknown keys and bad values."""
    updates = _check_updates(await parse_json_body(request))
    fleet_home = get_fleet_home()
    try:
        new_cfg = await asyncio.to_thread(_write_config, fleet_home / "runtime.toml", updates)
    except (ConfigError, ValueError) as exc:
        raise unprocessable(str(exc)) from exc
    return JSONResponse(asdict(new_cfg))
