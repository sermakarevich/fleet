"""Full-text search route (FR-47)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from fleet.core.limits import SEARCH_LIMIT_DEFAULT, SEARCH_LIMIT_MAX
from fleet.serve.api.models import SearchResponse
from fleet.serve.auth import HTTP_AUTH
from fleet.state.legacy_task_dir import legacy_state_text
from fleet.state.paths import STATE_MD
from fleet.state.paths import fleet_home as get_fleet_home
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One match: which task, which field, and a snippet around the hit."""

    task_id: str
    task_title: str
    source: str  # "title" | "description" | "qa" | "state"
    match_context: str  # ~120 char snippet


def _snippet(text: str, query: str) -> str:
    idx = text.lower().find(query)
    if idx == -1:
        return text[:120]
    start = max(0, idx - 40)
    return text[start : start + 120]


def _state_text(task_dir: Path) -> str:
    """Current STATE.md, or the legacy view for old task dirs."""
    try:
        return (task_dir / STATE_MD).read_text(encoding="utf-8")
    except OSError:
        pass
    return legacy_state_text(task_dir) or ""


def search_tasks(
    fleet_home: Path, query: str, limit: int = SEARCH_LIMIT_DEFAULT
) -> list[SearchResult]:
    """Scan task directories for query matches; return up to *limit* results."""
    results: list[SearchResult] = []
    if not query.strip():
        return results
    needle = query.lower()
    index = TaskIndex(fleet_home)
    for task_dir, data in index.iter_meta():
        task_id = data.get("id", task_dir.name)
        task_title = data.get("title", "")
        desc = data.get("description") or ""
        if needle in task_title.lower():
            results.append(
                SearchResult(
                    task_id=task_id,
                    task_title=task_title,
                    source="title",
                    match_context=_snippet(task_title, needle),
                )
            )
        if needle in desc.lower():
            results.append(
                SearchResult(
                    task_id=task_id,
                    task_title=task_title,
                    source="description",
                    match_context=_snippet(desc, needle),
                )
            )
        state_text = _state_text(task_dir)
        if state_text and needle in state_text.lower():
            results.append(
                SearchResult(
                    task_id=task_id,
                    task_title=task_title,
                    source="state",
                    match_context=_snippet(state_text, needle),
                )
            )
        if len(results) >= limit:
            break
    return results[:limit]


@router.get("/search", response_model=SearchResponse)
async def search(
    query: str = Query(...),
    limit: int = Query(default=SEARCH_LIMIT_DEFAULT, ge=1, le=SEARCH_LIMIT_MAX),
) -> JSONResponse:
    """Full-text search over task titles, descriptions and STATE.md."""
    if not query.strip():
        return JSONResponse({"results": []})
    fleet_home = get_fleet_home()
    results = await asyncio.to_thread(search_tasks, fleet_home, query, limit)
    return JSONResponse(
        {
            "results": [
                {
                    "task_id": r.task_id,
                    "task_title": r.task_title,
                    "source": r.source,
                    "match_context": r.match_context,
                }
                for r in results
            ]
        }
    )
