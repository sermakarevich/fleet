"""Coder registry: names to implementations, resolved lazily.

``REGISTRY`` maps a coder name to ``"module:Class"``; importing this package
imports none of the coder modules (each pulls in CLI-specific helpers). Use
:func:`resolve_coder` to build a coder, :func:`get_coder` to look up (and
validate) the class, :func:`coder_kwargs` to build constructor kwargs from
config plus env settings, :func:`context_limit_for` for the shared window
lookup, and :func:`list_coders` for coder metadata. Called by the
orchestrator (spawn), workers (compact), the CLI, and serve.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from fleet.coders.base import FALLBACK_CONTEXT_LIMIT, Coder, CoderSpec
from fleet.coders.base import context_limit_for as spec_window
from fleet.coders.settings import (
    BedrockSettings,
    CoderEnvSettings,
    OpencodeSettings,
    PiSettings,
)
from fleet.core.config import RuntimeConfig

REGISTRY: dict[str, str] = {
    "claude": "fleet.coders.claude:ClaudeCoder",
    "agy": "fleet.coders.agy:AgyCoder",
    "codex": "fleet.coders.codex:CodexCoder",
    "opencode": "fleet.coders.opencode:OpencodeCoder",
    "pi": "fleet.coders.pi:PiCoder",
}

__all__ = [
    "REGISTRY",
    "Coder",
    "CoderSpec",
    "coder_kwargs",
    "context_limit_for",
    "get_coder",
    "list_coders",
    "resolve_coder",
]


def _lookup(name: str) -> Any:
    """Import the coder class for *name*, or raise ValueError when unknown."""
    try:
        target = REGISTRY[name]
    except KeyError:
        available = sorted(REGISTRY)
        raise ValueError(f"Unknown coder {name!r}. Available: {available}") from None
    module_name, _, class_name = target.partition(":")
    return getattr(importlib.import_module(module_name), class_name)


def get_coder(name: str) -> type[Coder]:
    """Return the coder class for the given name, or raise ValueError."""
    return _lookup(name)


def resolve_coder(name: str, **kwargs: Any) -> Coder:
    """Build the coder for *name* (module imported lazily), or raise ValueError."""
    return _lookup(name)(**kwargs)


def _bedrock_of(config: RuntimeConfig) -> BedrockSettings | None:
    """Bedrock overlay from config, or None when the operator set neither field."""
    if not config.opencode_bedrock_profile and not config.opencode_bedrock_region:
        return None
    return BedrockSettings(
        profile=config.opencode_bedrock_profile,
        region=config.opencode_bedrock_region,
    )


def _opencode_kwargs(*, config: RuntimeConfig, env: CoderEnvSettings) -> dict[str, Any]:
    """Opencode extras: default model plus settings (env log file, routing)."""
    return {
        "default_model": config.opencode_default_model,
        "settings": OpencodeSettings(
            log_file=env.opencode_log_file,
            ollama_url=config.opencode_ollama_url,
            bedrock=_bedrock_of(config),
        ),
    }


def _pi_kwargs(*, config: RuntimeConfig, env: CoderEnvSettings) -> dict[str, Any]:
    """Pi extras: default model plus settings (env agent dir, routing)."""
    return {
        "default_model": config.opencode_default_model,
        "settings": PiSettings(
            agent_dir=env.pi_agent_dir,
            ollama_url=config.opencode_ollama_url,
            bedrock=_bedrock_of(config),
        ),
    }


_EXTRA_KWARGS = {
    "opencode": _opencode_kwargs,
    "pi": _pi_kwargs,
}
"""Coder names taking more than model + fleet_home, mapped to their builder."""


def coder_kwargs(
    name: str,
    *,
    model: str | None,
    fleet_home: Path,
    config: RuntimeConfig,
    env: CoderEnvSettings,
) -> dict[str, Any]:
    """Constructor kwargs for *name*: model + fleet_home for all, extras per coder.

    Only opencode and pi take extras (default model plus a settings record
    built from *config* routing and *env* overrides).
    """
    kwargs: dict[str, Any] = {"model": model, "fleet_home": fleet_home}
    build = _EXTRA_KWARGS.get(name)
    if build is not None:
        kwargs.update(build(config=config, env=env))
    return kwargs


def context_limit_for(
    coder_name: str | None,
    model: str | None = None,
    overrides: dict[str, int] | None = None,
) -> int:
    """Resolved context window for a coder/model pair (one denominator for UI + supervisor)."""
    if not coder_name:
        return FALLBACK_CONTEXT_LIMIT
    try:
        spec: CoderSpec = _lookup(coder_name).spec
    except ValueError:
        return FALLBACK_CONTEXT_LIMIT
    return spec_window(spec, model, overrides)


def list_coders() -> list[dict]:
    """Return coder metadata for all registered coders."""
    coders = []
    for name in REGISTRY:
        spec: CoderSpec = _lookup(name).spec
        coders.append(
            {
                "name": spec.name,
                "context_limit": spec.context_limit,
                "default_model": spec.default_model,
            }
        )
    return coders
