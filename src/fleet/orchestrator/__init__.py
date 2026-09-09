"""Orchestrator: the supervisor process, split by concern.

The supervisor is a thin runner over ordered services (see ADR 0005):
each module in this package owns one concern with its own cadence, and
`default_services()` builds the production list in hook order.
"""

from __future__ import annotations

from fleet.integrations.ask_human.store import QuestionStore

from .claim import Claim
from .config_reload import make_config_reload
from .kill_sentinel import make_kill_sentinel
from .leases import LeaseReconcile
from .merge_validation import MergeValidation
from .reap import Reap
from .retention_gc import make_retention_gc
from .scheduler import make_scheduler
from .service import Service
from .stall import StallWatch
from .state import SupervisorState
from .status_log import make_status_log
from .supervisor import Supervisor
from .triage import Triage

__all__ = [
    "Claim",
    "LeaseReconcile",
    "MergeValidation",
    "Reap",
    "Service",
    "StallWatch",
    "Supervisor",
    "SupervisorState",
    "Triage",
    "default_services",
]


def default_services(question_store: QuestionStore | None = None) -> list[Service]:
    """Build the production service list in hook order.

    The triage question store is injected by the caller (the CLI passes the
    real ask_human store).
    """
    return [
        make_config_reload(),
        LeaseReconcile(),
        make_scheduler(),
        Claim(),
        MergeValidation(),
        Reap(),
        StallWatch(),
        make_kill_sentinel(),
        Triage(store=question_store),
        make_retention_gc(),
        make_status_log(),
    ]
