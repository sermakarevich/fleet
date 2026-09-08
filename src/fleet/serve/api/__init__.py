"""Serve API router registry, one list.

Called by serve/app.py (`for r in ROUTERS: app.include_router(r)`). Adding a
router is adding one line here. Every module under serve/api/ that defines a
module-level ``router`` must appear in this list (enforced by
tests/serve/test_routers_registry.py).
"""

from __future__ import annotations

from fastapi import APIRouter

from fleet.serve.api.analytics import router as analytics_router
from fleet.serve.api.beads import router as beads_router
from fleet.serve.api.chat import router as chat_router
from fleet.serve.api.config import router as config_router
from fleet.serve.api.search import router as search_router
from fleet.serve.api.supervisor import router as supervisor_router
from fleet.serve.api.system import router as system_router
from fleet.serve.api.tasks_actions import router as tasks_actions_router
from fleet.serve.api.tasks_artifacts import router as tasks_artifacts_router
from fleet.serve.api.tasks_attempts import router as tasks_attempts_router
from fleet.serve.api.tasks_detail import router as tasks_detail_router
from fleet.serve.api.tasks_list import router as tasks_list_router
from fleet.serve.api.tasks_stream import router as tasks_stream_router

ROUTERS: list[APIRouter] = [
    tasks_list_router,
    tasks_detail_router,
    tasks_attempts_router,
    tasks_actions_router,
    tasks_artifacts_router,
    tasks_stream_router,
    beads_router,
    supervisor_router,
    system_router,
    config_router,
    analytics_router,
    search_router,
    chat_router,
]
