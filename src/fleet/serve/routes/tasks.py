"""Task CRUD + actions REST routes (FR-07, FR-31, FR-32, FR-33, FR-34)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.coders import _REGISTRY, get_coder
from fleet.queue import BeadsError
from fleet.serve.stats import fleet_home as get_fleet_home, task_runtime_stats


def _read_task_jsons(home: Path) -> list[dict]:
    tasks_dir = home / "tasks"
    if not tasks_dir.is_dir():
        return []
    results = []
    for task_dir in sorted(tasks_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        task_file = task_dir / "task.json"
        if not task_file.exists():
            continue
        try:
            data = json.loads(task_file.read_text(encoding="utf-8"))
            results.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return results


def _coder_context_limit(coder_name: str | None) -> int:
    if not coder_name:
        return 200_000
    try:
        return get_coder(coder_name).context_limit
    except ValueError:
        return 200_000


def _last_event_info(task_id: str, home: Path) -> tuple[str | None, str | None]:
    events_file = home / "tasks" / task_id / "events.jsonl"
    if not events_file.exists():
        return None, None
    last_kind: str | None = None
    last_detail: str | None = None
    try:
        with events_file.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = row.get("kind")
                if kind:
                    last_kind = kind
                    extra = row.get("extra") or {}
                    tool = row.get("tool_name") or extra.get("tool_name")
                    last_detail = str(tool) if tool else None
    except OSError:
        pass
    return last_kind, last_detail


def _build_task_summary(data: dict, home: Path) -> dict:
    task_id = data.get("id", "")
    stats = task_runtime_stats(task_id)

    now = datetime.now(tz=timezone.utc)
    started_at = stats.started_at
    elapsed_sec: float | None = (now - started_at).total_seconds() if started_at else None
    idle_sec: float | None = (
        (now - stats.last_event_at).total_seconds() if stats.last_event_at else None
    )
    context_tokens = stats.context_tokens
    context_pct: float | None = None
    if context_tokens is not None:
        limit = _coder_context_limit(data.get("coder"))
        context_pct = context_tokens / limit * 100

    last_kind, last_detail = _last_event_info(task_id, home)

    return {
        "id": task_id,
        "title": data.get("title"),
        "status": data.get("status"),
        "cwd": data.get("cwd"),
        "coder": data.get("coder"),
        "model": data.get("model"),
        "started_at": started_at.isoformat() if started_at else None,
        "elapsed_sec": elapsed_sec,
        "idle_sec": idle_sec,
        "events": stats.events,
        "context_tokens": context_tokens,
        "context_pct": context_pct,
        "last_event_kind": last_kind,
        "last_event_detail": last_detail,
    }


def create_tasks_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/tasks")
    async def list_tasks() -> JSONResponse:
        home = get_fleet_home()
        task_jsons = _read_task_jsons(home)

        active: list[dict] = []
        closed: list[dict] = []
        for data in task_jsons:
            if data.get("status") == "closed":
                closed.append(data)
            else:
                active.append(data)

        selected = active + closed[-20:]
        summaries = [_build_task_summary(d, home) for d in selected]
        return JSONResponse({"tasks": summaries})

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        task_file = home / "tasks" / task_id / "task.json"
        if not task_file.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            data = json.loads(task_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(_build_task_summary(data, home))

    @router.post("/tasks/{task_id}/kill")
    async def kill_task(task_id: str, request: Request) -> JSONResponse:
        home = get_fleet_home()
        if not (home / "tasks" / task_id / "task.json").exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        queue = request.app.state.queue
        try:
            await asyncio.to_thread(queue.release, task_id)
        except BeadsError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"ok": True})

    @router.post("/tasks/{task_id}/requeue")
    async def requeue_task(task_id: str, request: Request) -> JSONResponse:
        queue = request.app.state.queue
        try:
            await asyncio.to_thread(queue.release, task_id)
        except BeadsError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"ok": True})

    @router.post("/tasks")
    async def create_task(request: Request) -> JSONResponse:
        body = await request.json()
        title: str = body.get("title", "").strip()
        if not title:
            return JSONResponse({"error": "title is required"}, status_code=422)
        coder: str | None = body.get("coder")
        if coder:
            try:
                get_coder(coder)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=422)
        queue = request.app.state.queue
        try:
            task = await asyncio.to_thread(
                queue.create_task,
                title,
                body.get("description"),
                body.get("dependencies"),
                None,
                body.get("cwd"),
                coder,
                body.get("model"),
            )
        except BeadsError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"id": task.id}, status_code=201)

    @router.get("/coders")
    async def list_coders() -> JSONResponse:
        return JSONResponse({"coders": list(_REGISTRY.keys())})

    @router.get("/templates")
    async def list_templates() -> JSONResponse:
        home = get_fleet_home()
        templates_dir = home / "templates"
        if not templates_dir.is_dir():
            return JSONResponse({"templates": []})
        templates = []
        for f in sorted(templates_dir.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8")
                templates.append({"name": f.stem, "content": content})
            except OSError:
                continue
        return JSONResponse({"templates": templates})

    @router.get("/search")
    async def search_tasks(q: str) -> JSONResponse:
        home = get_fleet_home()
        results = []
        tasks_dir = home / "tasks"
        if not tasks_dir.is_dir() or not q.strip():
            return JSONResponse({"results": results})
        query = q.lower()
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

            # Search in title and description
            for source, text in [("title", task_title), ("description", desc)]:
                if query in text.lower():
                    ctx_start = max(0, text.lower().find(query) - 40)
                    results.append({
                        "task_id": task_id,
                        "task_title": task_title,
                        "match_context": text[ctx_start:ctx_start + 120],
                        "source": source,
                    })

            # Search in Q&A.md
            qa_file = task_dir / "artifacts" / "Q&A.md"
            if qa_file.exists():
                try:
                    qa_text = qa_file.read_text(encoding="utf-8")
                    if query in qa_text.lower():
                        idx = qa_text.lower().find(query)
                        ctx_start = max(0, idx - 40)
                        results.append({
                            "task_id": task_id,
                            "task_title": task_title,
                            "match_context": qa_text[ctx_start:ctx_start + 120],
                            "source": "qa",
                        })
                except OSError:
                    pass

            # Search in KNOWLEDGE.md
            kb_file = task_dir / "artifacts" / "KNOWLEDGE.md"
            if kb_file.exists():
                try:
                    kb_text = kb_file.read_text(encoding="utf-8")
                    if query in kb_text.lower():
                        idx = kb_text.lower().find(query)
                        ctx_start = max(0, idx - 40)
                        results.append({
                            "task_id": task_id,
                            "task_title": task_title,
                            "match_context": kb_text[ctx_start:ctx_start + 120],
                            "source": "knowledge",
                        })
                except OSError:
                    pass

        return JSONResponse({"results": results})

    return router
