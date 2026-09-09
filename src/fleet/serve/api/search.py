"""Full-text search route (FR-47)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from fleet.serve.api.models import SearchResponse
from fleet.state.legacy import legacy_state_text
from fleet.state.paths import STATE_MD
from fleet.state.paths import fleet_home as get_fleet_home
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api")

_MAX_RESULTS = 20  # search stops collecting and truncates here


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


def search_tasks(fleet_home: Path, query: str) -> list[SearchResult]:
    """Scan task directories for query matches; return up to _MAX_RESULTS results."""
    results: list[SearchResult] = []
    if not query.strip():
        return results
    q = query.lower()
    index = TaskIndex(fleet_home)
    for task_dir, data in index.iter_meta():
        task_id = data.get("id", task_dir.name)
        task_title = data.get("title", "")
        desc = data.get("description") or ""
        if q in task_title.lower():
            results.append(
                SearchResult(
                    task_id=task_id,
                    task_title=task_title,
                    source="title",
                    match_context=_snippet(task_title, q),
                )
            )
        if q in desc.lower():
            results.append(
                SearchResult(
                    task_id=task_id,
                    task_title=task_title,
                    source="description",
                    match_context=_snippet(desc, q),
                )
            )
        state_text = _state_text(task_dir)
        if state_text and q in state_text.lower():
            results.append(
                SearchResult(
                    task_id=task_id,
                    task_title=task_title,
                    source="state",
                    match_context=_snippet(state_text, q),
                )
            )
        if len(results) >= _MAX_RESULTS:
            break
    return results[:_MAX_RESULTS]


@router.get("/search", response_model=SearchResponse)
async def search(q: str = Query(...)) -> JSONResponse:
    """Full-text search over task titles, descriptions and STATE.md."""
    if not q.strip():
        return JSONResponse({"results": []})
    home = get_fleet_home()
    results = await asyncio.to_thread(search_tasks, home, q)
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
