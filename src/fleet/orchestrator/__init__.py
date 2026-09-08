"""Orchestrator: the supervisor process, split by concern.

The supervisor is a thin runner over ordered services (see ADR 0005):
each module in this package owns one concern with its own cadence, and
`default_services()` builds the production list in hook order.
"""

from __future__ import annotations

from .claim import Claim
from .config_reload import ConfigReload
from .kill_sentinel import KillSentinel
from .leases import LeaseReconcile
from .merge_validation import MergeValidation
from .reap import Reap
from .retention_gc import RetentionGc
from .service import Service
from .stall import StallWatch
from .state import SupervisorState
from .status_log import StatusLog
from .supervisor import Supervisor
from .triage import Triage

__all__ = [
    "Claim",
    "ConfigReload",
    "KillSentinel",
    "LeaseReconcile",
    "MergeValidation",
    "Reap",
    "RetentionGc",
    "Service",
    "StallWatch",
    "StatusLog",
    "Supervisor",
    "SupervisorState",
    "Triage",
    "default_services",
]


def default_services() -> list[Service]:
    """Build the production service list in hook order."""
    return [
        ConfigReload(),
        LeaseReconcile(),
        Claim(),
        MergeValidation(),
        Reap(),
        StallWatch(),
        KillSentinel(),
        Triage(),
        RetentionGc(),
        StatusLog(),
    ]
