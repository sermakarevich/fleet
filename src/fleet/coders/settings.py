"""Coder settings: env-derived knobs and per-coder settings records.

Every ``os.environ`` read that configures a coder lives in
:func:`settings_from_env`, which the spawn boundary
(``orchestrator/spawn.py``) calls once per task; a coder module never touches
``os.environ`` itself. This module also owns the settings records:
:class:`BedrockSettings` (the shared AWS overlay), :class:`OpencodeSettings`
and :class:`PiSettings` (each coder's own knobs). It stays light (stdlib plus
the Ollama URL) so the lazy ``coders`` registry can import it at package load.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from fleet.coders.ollama import DEFAULT_OLLAMA_URL


def default_log_file() -> Path:
    """Default opencode CLI log path (the home-based location, no env)."""
    return Path.home() / ".local" / "share" / "opencode" / "log" / "opencode.log"


def default_agent_dir() -> Path:
    """Default pi agent dir (the home-based location, no env)."""
    return Path.home() / ".pi" / "agent"


@dataclass(frozen=True, slots=True)
class BedrockSettings:
    """AWS profile/region/window for Bedrock-routed models; inert otherwise."""

    profile: str = ""
    region: str = ""
    context_limit: int | None = None


@dataclass(frozen=True, slots=True)
class OpencodeSettings:
    """Opencode-only knobs: CLI log location, Ollama URL, Bedrock overlay."""

    log_file: Path = field(default_factory=default_log_file)
    ollama_url: str = DEFAULT_OLLAMA_URL
    bedrock: BedrockSettings | None = None


@dataclass(frozen=True, slots=True)
class PiSettings:
    """Pi-only knobs: agent dir, Ollama URL, Bedrock overlay."""

    agent_dir: Path = field(default_factory=default_agent_dir)
    ollama_url: str = DEFAULT_OLLAMA_URL
    bedrock: BedrockSettings | None = None


@dataclass(frozen=True, slots=True)
class CoderEnvSettings:
    """Env-derived coder knobs, resolved once at the spawn boundary."""

    opencode_log_file: Path
    pi_agent_dir: Path


def settings_from_env(environ: Mapping[str, str]) -> CoderEnvSettings:
    """Read coder env knobs from *environ* (``os.environ`` in production).

    ``OPENCODE_LOG_FILE`` overrides where the opencode CLI writes its log;
    ``PI_CODING_AGENT_DIR`` overrides where pi reads ``models.json``. Either
    may be absent or blank, in which case the home-based default applies.
    """
    log_file = environ.get("OPENCODE_LOG_FILE")
    agent_dir = environ.get("PI_CODING_AGENT_DIR")
    return CoderEnvSettings(
        opencode_log_file=Path(log_file) if log_file else default_log_file(),
        pi_agent_dir=Path(agent_dir) if agent_dir else default_agent_dir(),
    )
