"""Analytics REST routes (FR-35..FR-41). Thin: parses input, calls the summary aggregator."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from fleet.core.limits import ANALYTICS_DAYS_DEFAULT, ANALYTICS_DAYS_MAX
from fleet.serve.analytics.summary import compute_summary
from fleet.serve.api.models import AnalyticsSummary
from fleet.serve.auth import HTTP_AUTH
from fleet.state.paths import fleet_home as get_fleet_home

router = APIRouter(prefix="/api/analytics", dependencies=[HTTP_AUTH])


@router.get("/summary", response_model=AnalyticsSummary)
async def get_summary(
    days: int = Query(default=ANALYTICS_DAYS_DEFAULT, ge=1, le=ANALYTICS_DAYS_MAX),
) -> JSONResponse:
    """Aggregated analytics summary for the trailing *days*."""
    return JSONResponse(await asyncio.to_thread(compute_summary, get_fleet_home(), days))
