"""The one place CLI commands get their dependencies.

Called by every ``cli/*`` command module. Replaces the two duplicated
``_resolve_log_dir`` bodies that lived in ``cli/tasks.py`` and
``cli/daemons.py``: commands call these helpers instead of resolving paths,
queues, or config themselves.
"""

from __future__ import annotations

from pathlib import Path

from fleet.beads.queue import BeadsQueue
from fleet.core.config import RuntimeConfig
from fleet.core.limits import LOG_ROOT
from fleet.state.config_file import load as load_config
from fleet.state.paths import fleet_home


def home() -> Path:
    """Fleet home directory (``$FLEET_HOME`` or ``~/.fleet``)."""
    return fleet_home()


def log_dir(home: Path) -> Path:
    """Supervisor log dir: absolute ``LOG_ROOT`` as-is, else under the fleet home."""
    root = Path(LOG_ROOT)
    return root if root.is_absolute() else home / root


def queue(home: Path) -> BeadsQueue:
    """Beads queue bound to the fleet home."""
    return BeadsQueue(home)


def config(home: Path) -> RuntimeConfig:
    """Runtime config, creating ``runtime.toml`` with defaults when missing."""
    return load_config(home / "runtime.toml")
