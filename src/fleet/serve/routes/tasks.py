"""Task CRUD + actions REST routes (FR-07, FR-11..FR-21, FR-31..FR-34)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.coders import _REGISTRY, get_coder
from fleet.queue import BeadsError
from fleet.serve.stats import fleet_home as get_fleet_home, task_runtime_stats


@dataclass
class LogEntry:
    ts: str
    level: str
    message: str
    extra: dict = field(default_factory=dict)


@dataclass
class FileCounts:
    read: int = 0
    edit: int = 0
    write: int = 0


def _parse_log_line(line: str) -> LogEntry | None:
    try:
        row = json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    ts = row.get("timestamp") or row.get("ts") or ""
    level = row.get("level") or "info"
    message = row.get("event") or row.get("message") or ""
    extra = {k: v for k, v in row.items() if k not in ("timestamp", "ts", "level", "event", "message")}
    return LogEntry(ts=str(ts), level=str(level), message=str(message), extra=extra)


def _extract_file_ops(events_path: Path) -> dict[str, FileCounts]:
    counts: dict[str, FileCounts] = {}
    if not events_path.exists():
        return counts
    _tool_map = {"Read": "read", "Edit": "edit", "Write": "write"}
    try:
        with events_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("kind") != "tool_use":
                    continue
                tool = row.get("tool_name") or ""
                op = _tool_map.get(tool)
                if not op:
                    continue
                raw_data = row.get("raw") or {}
                inp = raw_data.get("input") or {}
                path = inp.get("file_path") or inp.get("path")
                if not path:
                    continue
                if path not in counts:
                    counts[path] = FileCounts()
                setattr(counts[path], op, getattr(counts[path], op) + 1)
    except OSError:
        pass
    return counts


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
        "priority": data.get("priority"),
        "depends_on": data.get("depends_on") or [],
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

    # ------------------------------------------------------------------
    # Artifact endpoints (FR-11..FR-20)
    # ------------------------------------------------------------------

    def _artifact_path(task_id: str, filename: str, home: Path) -> Path:
        return home / "tasks" / task_id / "artifacts" / filename

    @router.get("/tasks/{task_id}/artifacts/plan")
    async def get_artifact_plan(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = _artifact_path(task_id, "PLAN_AND_STATUS.md", home)
        if not f.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"content": f.read_text(encoding="utf-8"), "mtime": f.stat().st_mtime, "path": str(f.resolve())})

    @router.get("/tasks/{task_id}/artifacts/knowledge")
    async def get_artifact_knowledge(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = _artifact_path(task_id, "KNOWLEDGE.md", home)
        if not f.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"content": f.read_text(encoding="utf-8"), "mtime": f.stat().st_mtime, "path": str(f.resolve())})

    @router.get("/tasks/{task_id}/artifacts/qa")
    async def get_artifact_qa(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = _artifact_path(task_id, "Q&A.md", home)
        if not f.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"content": f.read_text(encoding="utf-8"), "mtime": f.stat().st_mtime})

    @router.get("/tasks/{task_id}/logs")
    async def get_task_logs(task_id: str, level: str | None = None) -> JSONResponse:
        home = get_fleet_home()
        log_file = home / "tasks" / task_id / "log.jsonl"
        entries: list[dict] = []
        if log_file.exists():
            try:
                for raw in log_file.read_text(encoding="utf-8").splitlines():
                    entry = _parse_log_line(raw)
                    if entry is None:
                        continue
                    if level and entry.level != level:
                        continue
                    entries.append({"ts": entry.ts, "level": entry.level, "message": entry.message, "extra": entry.extra})
            except OSError:
                pass
        return JSONResponse({"lines": entries})

    @router.get("/tasks/{task_id}/stderr")
    async def get_task_stderr(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = home / "tasks" / task_id / "log.stderr"
        content = f.read_text(encoding="utf-8") if f.exists() else ""
        return JSONResponse({"content": content})

    @router.get("/tasks/{task_id}/diff")
    async def get_task_diff(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        task_file = home / "tasks" / task_id / "task.json"
        if not task_file.exists():
            return JSONResponse({"diff": ""})
        try:
            data = json.loads(task_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return JSONResponse({"diff": ""})
        cwd = data.get("cwd")
        if not cwd:
            return JSONResponse({"diff": ""})
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", cwd, "diff",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            diff_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        except (OSError, asyncio.TimeoutError):
            diff_text = ""
        return JSONResponse({"diff": diff_text})

    @router.get("/tasks/{task_id}/files")
    async def get_task_files(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        events_path = home / "tasks" / task_id / "events.jsonl"
        counts = _extract_file_ops(events_path)
        files = [
            {"path": path, "read": fc.read, "edit": fc.edit, "write": fc.write}
            for path, fc in sorted(counts.items())
        ]
        return JSONResponse({"files": files})

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

    return router
