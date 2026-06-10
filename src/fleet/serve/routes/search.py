"""Full-text search route (FR-47)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from fleet.serve.stats import fleet_home as get_fleet_home


@dataclass
class SearchResult:
    task_id: str
    task_title: str
    source: str  # "title" | "description" | "qa" | "knowledge" | "plan"
    match_context: str  # ~120 char snippet


def _snippet(text: str, query: str) -> str:
    idx = text.lower().find(query)
    if idx == -1:
        return text[:120]
    start = max(0, idx - 40)
    return text[start : start + 120]


def search_tasks(fleet_home: Path, query: str) -> list[SearchResult]:
    """Scan task directories for query matches; return up to 20 results."""
    results: list[SearchResult] = []
    tasks_dir = fleet_home / "tasks"
    if not tasks_dir.is_dir() or not query.strip():
        return results
    q = query.lower()

    for task_dir in sorted(tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        task_file = task_dir / "task.json"
        if not task_file.exists():
            continue
        try:
            data = json.loads(task_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        task_id = data.get("id", task_dir.name)
        task_title = data.get("title", "")
        desc = data.get("description") or ""

        if q in task_title.lower():
            results.append(SearchResult(
                task_id=task_id,
                task_title=task_title,
                source="title",
                match_context=_snippet(task_title, q),
            ))

        if q in desc.lower():
            results.append(SearchResult(
                task_id=task_id,
                task_title=task_title,
                source="description",
                match_context=_snippet(desc, q),
            ))

        artifact_sources: list[tuple[str, str]] = [
            ("Q&A.md", "qa"),
            ("KNOWLEDGE.md", "knowledge"),
            ("PLAN_AND_STATUS.md", "plan"),
        ]
        for filename, source_label in artifact_sources:
            f = task_dir / "artifacts" / filename
            if not f.exists():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            if q in text.lower():
                results.append(SearchResult(
                    task_id=task_id,
                    task_title=task_title,
                    source=source_label,
                    match_context=_snippet(text, q),
                ))

        if len(results) >= 20:
            break

    return results[:20]


def create_search_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/search")
    async def search(q: str = Query(...)) -> JSONResponse:
        if not q.strip():
            return JSONResponse({"results": []})
        home = get_fleet_home()
        results = await asyncio.to_thread(search_tasks, home, q)
        return JSONResponse({
            "results": [
                {
                    "task_id": r.task_id,
                    "task_title": r.task_title,
                    "source": r.source,
                    "match_context": r.match_context,
                }
                for r in results
            ]
        })

    return router
