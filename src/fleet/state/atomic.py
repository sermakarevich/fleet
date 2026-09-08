"""Atomic file writes for task-directory state.

Every overwrite of a marker, JSON or TOML file under ``$FLEET_HOME`` goes
through :func:`write_text_atomic` (or :func:`write_json_atomic` for JSON):
write to a sibling temp file, fsync, then ``os.replace`` so concurrent
readers (UI, CLI, another supervisor) never see a half-written file. This
module is the only place that writes a file atomically.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write *text* to *path* atomically via temp file + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def write_json_atomic(path: Path, obj: Any) -> None:
    """Write *obj* as indented JSON to *path* atomically."""
    write_text_atomic(path, json.dumps(obj, indent=2))
