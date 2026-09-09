"""Process liveness probe shared by every layer.

The single owner of the "is this pid alive" question (ADR 0006 rule 1):
``observability/daemon.py``, ``orchestrator/leases.py`` and
``state/task_summary.py`` used to carry their own copies. Callers are the
daemon manager, the lease reconciler, the task-summary lease badge, and the
serve routes that report supervisor liveness.
"""

from __future__ import annotations

import os
import socket


def host_name() -> str:
    """This machine's hostname for lease ownership checks (best effort)."""
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def pid_alive(pid: object) -> bool:
    """True when *pid* names a live process (signal 0 probe, best effort)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user — still alive for our purposes.
        return True
    except OSError:
        return False
    return True
