"""Config read and write REST routes (FR-43)."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.coders import get_coder
from fleet.core import limits as core_limits
from fleet.core import retry_policy as retry_mod
from fleet.core import triage_policy as triage_mod
from fleet.core.config import RESTART_REQUIRED_FIELDS, RuntimeConfig
from fleet.core.errors import ConfigError
from fleet.serve.api.models import ConfigConstantsResponse, ConfigView
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


def _config_payload(config: RuntimeConfig) -> dict[str, Any]:
    """Full RuntimeConfig as JSON plus the restart-required field names."""
    payload = asdict(config)
    payload["restart_required"] = list(RESTART_REQUIRED_FIELDS)
    return payload


# Unit hint by constant-name suffix; "" when the value is unit-free.
_UNIT_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("_SEC", "seconds"),
    ("_MINUTES", "minutes"),
    ("_BYTES", "bytes"),
    ("_DAYS", "days"),
    ("_PCT", "percent"),
    ("_TOKENS", "tokens"),
    ("_LINES", "lines"),
)


def _unit_for(name: str) -> str:
    """Unit hint for a constant name, or "" when it has none."""
    for suffix, unit in _UNIT_SUFFIXES:
        if name.endswith(suffix):
            return unit
    return ""


# Retry/triage constants outside core/limits.py: (name, doc, module label).
_EXTRA_CONSTANTS: tuple[tuple[str, str, str], ...] = (
    (
        "FAILURE_WAIT_SEC",
        "Back-off seconds per consecutive failure round.",
        "core/retry_policy.py",
    ),
    (
        "FAILURE_JITTER_SEC",
        "Random seconds added on top of the failure back-off.",
        "core/retry_policy.py",
    ),
    (
        "WAITING_WAIT_SEC",
        "Delay before a waiting task becomes claimable again.",
        "core/retry_policy.py",
    ),
    (
        "MAX_PER_TASK_QUESTIONS",
        "Max per-task triage questions posted in a single tick.",
        "core/triage_policy.py",
    ),
)

_EXTRA_MODULES: dict[str, Any] = {
    "core/retry_policy.py": retry_mod,
    "core/triage_policy.py": triage_mod,
}


def _constant_rows() -> list[dict[str, str]]:
    """TUNABLE_DOCS plus the retry/triage constants as JSON rows."""
    rows = [
        {
            "name": name,
            "value": repr(getattr(core_limits, name)),
            "unit": _unit_for(name),
            "doc": doc,
            "module": "core/limits.py",
        }
        for name, doc in core_limits.TUNABLE_DOCS.items()
    ]
    for name, doc, module in _EXTRA_CONSTANTS:
        rows.append(
            {
                "name": name,
                "value": repr(getattr(_EXTRA_MODULES[module], name)),
                "unit": _unit_for(name),
                "doc": doc,
                "module": module,
            }
        )
    return rows


@router.get("/config", response_model=ConfigView)
async def get_config() -> JSONResponse:
    """Full RuntimeConfig as JSON (FR-43)."""
    fleet_home = get_fleet_home()
    config = await asyncio.to_thread(_read_config, fleet_home / "runtime.toml")
    return JSONResponse(_config_payload(config))


@router.get("/config/constants", response_model=ConfigConstantsResponse)
async def get_config_constants() -> JSONResponse:
    """Read-only code-level tunables with docs (ADR 0009 Settings)."""
    return JSONResponse({"constants": _constant_rows()})


@router.put("/config", response_model=ConfigView)
async def put_config(request: Request) -> JSONResponse:
    """Update runtime.toml atomically; rejects unknown keys and bad values."""
    updates = _check_updates(await parse_json_body(request))
    fleet_home = get_fleet_home()
    try:
        new_cfg = await asyncio.to_thread(_write_config, fleet_home / "runtime.toml", updates)
    except (ConfigError, ValueError) as exc:
        raise unprocessable(str(exc)) from exc
    return JSONResponse(_config_payload(new_cfg))
