"""Serve API router registry, one list.

Called by serve/app.py (`for r in ROUTERS: app.include_router(r)`). Adding a
router is adding one line here. Every module under serve/api/ that defines a
module-level ``router`` must appear in this list (enforced by
tests/serve/test_routers_registry.py).

Blocking-I/O rule: ``async def`` handlers never touch the filesystem (or a
subprocess, socket, or sqlite) directly — the read runs in a sync helper via
``await asyncio.to_thread(...)``. (Starlette would also accept a plain
``def`` handler run in its threadpool, but this codebase keeps handlers
async and pushes the blocking call one level down so every route reads the
same way.) Enforced by tests/test_no_blocking_io_in_async.py.
"""

from __future__ import annotations

from fastapi import APIRouter

from fleet.serve.api.analytics import router as analytics_router
from fleet.serve.api.beads import router as beads_router
from fleet.serve.api.chat import router as chat_router
from fleet.serve.api.config import router as config_router
from fleet.serve.api.schedules import router as schedules_router
from fleet.serve.api.search import router as search_router
from fleet.serve.api.supervisor import router as supervisor_router
from fleet.serve.api.system import router as system_router
from fleet.serve.api.system import ws_router as system_ws_router
from fleet.serve.api.tasks_actions import router as tasks_actions_router
from fleet.serve.api.tasks_artifacts import router as tasks_artifacts_router
from fleet.serve.api.tasks_attempts import router as tasks_attempts_router
from fleet.serve.api.tasks_detail import router as tasks_detail_router
from fleet.serve.api.tasks_list import router as tasks_list_router
from fleet.serve.api.tasks_stream import router as tasks_stream_router
from fleet.serve.api.workflows import router as workflows_router

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
    system_ws_router,
    config_router,
    analytics_router,
    search_router,
    schedules_router,
    workflows_router,
    chat_router,
]
