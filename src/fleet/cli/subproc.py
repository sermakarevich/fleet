"""One way for CLI commands to spawn a child process.

Called by ``cli/daemons.py`` (``just ui-build``), ``cli/ask_human.py``
(``claude mcp ...``) and ``cli/beads.py`` (the ``bd`` passthrough). Every
spawn carries ``SUBPROCESS_TIMEOUT_SEC``; a hung child raises
``SubprocessTimeout`` (logged with the argv) instead of hanging the
terminal forever. ``bd`` calls that need JSON envelopes go through
``beads/client.py`` instead.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from fleet.core.errors import SubprocessTimeout
from fleet.core.limits import SUBPROCESS_TIMEOUT_SEC

_log = logging.getLogger(__name__)


def run(
    argv: list[str],
    *,
    cwd: Path | str | None = None,
    capture: bool = False,
    timeout_s: float = SUBPROCESS_TIMEOUT_SEC,
) -> subprocess.CompletedProcess:
    """Run *argv*; raise SubprocessTimeout (logged with argv) on a hang.

    Output streams to the terminal unless *capture* is set (then stdout and
    stderr are captured as text, as before).
    """
    output_kwargs: dict = {"capture_output": True, "text": True} if capture else {}
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            timeout=timeout_s,
            **output_kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        _log.error("subprocess timeout", extra={"argv": argv, "timeout_s": timeout_s})
        raise SubprocessTimeout(list(argv), timeout_s) from exc
