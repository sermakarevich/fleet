"""The one place CLI commands get their dependencies.

Called by every ``cli/*`` command module. Path resolution lives in
``state/paths`` (not here): commands call those helpers instead of
resolving paths, queues, or config themselves.
"""

from __future__ import annotations

from pathlib import Path

from fleet.beads.queue import BeadsQueue
from fleet.core.config import RuntimeConfig
from fleet.state import paths
from fleet.state.config_file import load as load_config


def fleet_home() -> Path:
    """Fleet home directory (``$FLEET_HOME`` or ``~/.fleet``)."""
    return paths.fleet_home()


def queue(fleet_home: Path) -> BeadsQueue:
    """Beads queue bound to the fleet home."""
    return BeadsQueue(fleet_home)


def config(fleet_home: Path) -> RuntimeConfig:
    """Runtime config, creating ``runtime.toml`` with defaults when missing."""
    return load_config(fleet_home / "runtime.toml")
