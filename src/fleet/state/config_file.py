"""runtime.toml file I/O; the pure parse/render helpers live in core.config.

The single owner of the runtime.toml file on disk (ADR 0006 rule 1).
Called by ``orchestrator/config_reload.py`` (hot-reload),
``cli/config.py`` and ``serve/api/config.py`` (show/set), plus the various
startup paths that ensure defaults exist (``cli/tasks.py`` init,
``cli/daemons.py``, ``serve/app.py``). Coder-name validation is NOT done
here (state never imports coders): ``cli/config.py`` and
``serve/api/config.py`` validate ``coder`` values before calling
:func:`write`.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

from fleet.core.config import RuntimeConfig, defaults, merge, parse, render_toml
from fleet.state.atomic import write_text_atomic


def load(path: Path) -> RuntimeConfig:
    """Read + parse runtime.toml; create with defaults when missing."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, render_toml(defaults()))
        return RuntimeConfig()
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return parse(data)


def reload_if_changed(
    path: Path, current_mtime: float | None
) -> tuple[RuntimeConfig, float] | None:
    """Return (new_config, new_mtime) if file changed, else None."""
    path = Path(path)
    stat = os.stat(path)
    if current_mtime is not None and stat.st_mtime == current_mtime:
        return None
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return parse(data), stat.st_mtime


def write(path: Path, updates: Mapping[str, object]) -> RuntimeConfig:
    """Merge updates into on-disk TOML atomically; return new RuntimeConfig."""
    path = Path(path)
    if path.exists():
        with path.open("rb") as fh:
            existing = tomllib.load(fh)
    else:
        existing = {}
    merged = merge(existing, updates)
    write_text_atomic(path, render_toml(merged))
    return RuntimeConfig(**merged)
