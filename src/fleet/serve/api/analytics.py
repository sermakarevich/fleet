"""Analytics REST routes (FR-35..FR-41). Thin: parses input, calls the summary aggregator."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.analytics.summary import compute_summary
from fleet.state.paths import fleet_home as get_fleet_home


def create_analytics_router() -> APIRouter:
    router = APIRouter(prefix="/api/analytics")

    @router.get("/summary")
    async def get_summary(days: int = 7) -> JSONResponse:
        return JSONResponse(await asyncio.to_thread(compute_summary, get_fleet_home(), days))

    return router
