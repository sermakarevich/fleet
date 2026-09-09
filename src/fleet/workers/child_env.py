"""The one place a coder child environment is assembled.

Called by ``workers/llm_session.py`` (the session step) and
``workers/compact.py`` (the compaction model call). Layers the coder's own
overlay over the base environment, then the attempt facts (``FLEET_*``),
defaulting ``BEADS_DIR`` only when neither side set it. Nothing is stripped
silently: every key comes from the base env, the coder, or the attempt.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fleet.coders.base import Coder
    from fleet.core.task import Task


def child_env(
    coder: Coder,
    task: Task,
    task_dir: Path,
    attempt_dir: Path,
    base_env: Mapping[str, str] = os.environ,
    *,
    attempt_n: int | None = None,
    launch_mode: str | None = None,
    fleet_home: Path | None = None,
) -> dict[str, str]:
    """Assemble the child env: base + coder overlay + FLEET_* attempt facts."""
    env = {**base_env, **coder.env(task, task_dir)}
    env["FLEET_ATTEMPT_DIR"] = str(attempt_dir)
    if attempt_n is not None:
        env["FLEET_ATTEMPT_N"] = str(attempt_n)
    if launch_mode is not None:
        env["FLEET_LAUNCH_MODE"] = launch_mode
    if "BEADS_DIR" not in env and fleet_home is not None:
        env["BEADS_DIR"] = str(fleet_home / ".beads")
    return env
