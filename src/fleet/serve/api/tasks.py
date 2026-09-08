"""Task CRUD + actions REST routes (FR-07, FR-11..FR-21, FR-31..FR-34)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.beads import client as beads_client
from fleet.beads.cache import get_beads_status_map
from fleet.beads.client import BeadsError
from fleet.beads.reconcile import merge_status
from fleet.coders import get_coder
from fleet.coders import list_coders as _list_coders
from fleet.observability.daemon import _pid_alive
from fleet.observability.tailview import event_summary as _event_summary
from fleet.state import attempts
from fleet.state.counters import (
    clear_needs_validation,
    reset_failure,
    reset_noclose,
    reset_stall,
)
from fleet.state.events import scan_cached
from fleet.state.paths import fleet_home as get_fleet_home
from fleet.state.paths import task_dir as _task_dir
from fleet.state.paths import tasks_root
from fleet.state.task_summary import build_task_summary


@dataclass
class LogEntry:
    ts: str
    level: str
    message: str
    extra: dict = field(default_factory=dict)


def _parse_log_line(line: str) -> LogEntry | None:
    try:
        row = json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    ts = row.get("timestamp") or row.get("ts") or ""
    level = row.get("level") or "info"
    message = row.get("event") or row.get("message") or ""
    extra = {
        k: v
        for k, v in row.items()
        if k not in ("timestamp", "ts", "level", "event", "message")
    }
    return LogEntry(ts=str(ts), level=str(level), message=str(message), extra=extra)


def _read_task_jsons(home: Path) -> list[dict]:
    tasks_dir = tasks_root(home)
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


def _build_all_summaries(tasks: list[dict], home: Path) -> list[dict]:
    return [build_task_summary(_task_dir(home, d.get("id", "")), d, home) for d in tasks]


def _sync_remove_assignee(task_id: str, home: Path) -> tuple[bool, str]:
    """Clear assignee in both beads DB and task.json (if present)."""
    try:
        beads_client.update(task_id, home, assignee="")
    except BeadsError as exc:
        return False, str(exc) or "bd update failed"
    task_file = _task_dir(home, task_id) / "task.json"
    if task_file.exists():
        try:
            data = json.loads(task_file.read_text(encoding="utf-8"))
            data["coder"] = None
            task_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError) as exc:
            return False, str(exc)
    return True, ""


def _get_beads_task_status(task_id: str, home: Path) -> str | None:
    """Return the beads status for a single task, or None if unavailable."""
    info = _get_beads_task_info(task_id, home)
    return info.get("status") if info is not None else None


def _get_beads_task_info(task_id: str, home: Path) -> dict | None:
    """Return {status, priority, depends_on} from bd show, or None if unavailable."""
    try:
        body = beads_client.show(task_id, home)
        if not isinstance(body, dict):
            return None
        depends_on = [
            d["id"]
            for d in (body.get("dependencies") or [])
            if isinstance(d, dict) and d.get("id")
        ]
        return {
            "status": body.get("status"),
            "priority": body.get("priority"),
            "depends_on": depends_on,
        }
    except Exception:
        pass
    return None


def _supervisor_alive(home: Path) -> bool:
    pid_file = home / ".supervisor.pid"
    if not pid_file.exists():
        return False
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
        try:
            data = json.loads(text)
            pid = int(data.get("pid", 0)) or None
        except (ValueError, json.JSONDecodeError):
            pid = int(text) if text.isdigit() else None
        return pid is not None and _pid_alive(pid)
    except OSError:
        return False


def create_tasks_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    def _recency_key(data: dict) -> str:
        """Return a string that sorts by recency descending (latest first).

        Uses ended_at > started_at > created_at — ISO strings compare correctly.
        None values are mapped to the empty string which sorts before any ISO date
        when we reverse (i.e. they fall to the bottom).
        """
        data.get("ended_at") or ""
        data.get("started_at") or ""
        data.get("created_at") or ""
        # ended_at is only set in the summary, not the raw data, so fall through
        # to started_at / created_at which are always on the raw task.json data.
        for key in ("ended_at", "started_at", "created_at"):
            val = data.get(key)
            if val:
                return val
        return ""

    @router.get("/tasks")
    async def list_tasks(
        closed_limit: int = 300,
    ) -> JSONResponse:
        home = get_fleet_home()
        task_jsons = _read_task_jsons(home)

        # Reconcile status against beads (authoritative source of truth).
        # Tasks in beads get beads' status; tasks not in beads at all are orphaned
        # (completed before the current beads DB, or from a reset) and shown as closed.
        # Falls back to raw task.json status if beads is unavailable.
        beads_map = await asyncio.to_thread(get_beads_status_map, home)
        reconciled: list[dict] = []
        for data in task_jsons:
            task_id = data.get("id", "")
            if beads_map is not None and task_id:
                data = merge_status(data, beads_map.get(task_id))
            reconciled.append(data)

        closed_limit = max(0, min(closed_limit, 2000))

        active: list[dict] = []
        closed: list[dict] = []
        for data in reconciled:
            if data.get("status") in ("closed", "failed"):
                closed.append(data)
            else:
                active.append(data)

        # Sort closed tasks by recency descending
        closed.sort(key=_recency_key, reverse=True)

        if closed_limit > 0:
            closed = closed[:closed_limit]

        selected = active + closed
        summaries = await asyncio.to_thread(_build_all_summaries, selected, home)

        # Sort all summaries by recency descending
        summaries.sort(key=lambda s: _recency_key(s) or "", reverse=True)

        return JSONResponse({"tasks": summaries})

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        task_file = _task_dir(home, task_id) / "task.json"
        if not task_file.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            data = json.loads(task_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return JSONResponse({"error": "not found"}, status_code=404)
        beads_info = await asyncio.to_thread(_get_beads_task_info, task_id, home)
        if beads_info is not None:
            data = {
                **data,
                "status": beads_info["status"],
                "priority": beads_info["priority"],
                "depends_on": beads_info["depends_on"],
            }
        summary = build_task_summary(_task_dir(home, task_id), data, home)
        summary["attempts"] = attempts.load_attempts(_task_dir(home, task_id))
        return JSONResponse(summary)

    @router.post("/tasks/{task_id}/kill")
    async def kill_task(task_id: str, request: Request) -> JSONResponse:
        home = get_fleet_home()
        task_dir = _task_dir(home, task_id)
        if not (task_dir / "task.json").exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            data = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return JSONResponse({"error": "not found"}, status_code=404)
        beads_status = await asyncio.to_thread(_get_beads_task_status, task_id, home)
        status = beads_status if beads_status is not None else data.get("status", "")
        if status == "in_progress":
            (task_dir / ".kill").touch()
            if not _supervisor_alive(home):
                return JSONResponse({"ok": True, "result": "supervisor-not-running"})
            return JSONResponse({"ok": True, "result": "killing"})
        if status in ("open", "ready", "blocked"):
            queue = request.app.state.queue
            try:
                await asyncio.to_thread(queue.close, task_id, "killed")
            except BeadsError as exc:
                return JSONResponse({"error": str(exc)}, status_code=422)
            return JSONResponse({"ok": True, "result": "closed"})
        return JSONResponse({"ok": True, "result": "no-op"})

    @router.post("/tasks/{task_id}/requeue")
    async def requeue_task(task_id: str, request: Request) -> JSONResponse:
        queue = request.app.state.queue
        try:
            await asyncio.to_thread(queue.release, task_id)
        except BeadsError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"ok": True})

    @router.post("/tasks/{task_id}/unblock")
    async def unblock_task(task_id: str, request: Request) -> JSONResponse:
        home = get_fleet_home()
        task_dir = _task_dir(home, task_id)
        if not (task_dir / "task.json").exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        note: str | None = None
        try:
            body = await request.json()
            if isinstance(body, dict):
                note = body.get("note")
        except (json.JSONDecodeError, ValueError):
            pass
        reason = "[fleet] unblocked from UI"
        if note:
            reason += f": {note}"
        queue = request.app.state.queue
        try:
            await asyncio.to_thread(queue.release, task_id, reason)
        except BeadsError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        reset_failure(task_dir)
        reset_noclose(task_dir)
        reset_stall(task_dir)
        clear_needs_validation(task_dir)
        return JSONResponse({"ok": True})

    @router.post("/tasks/{task_id}/close")
    async def close_task(task_id: str, request: Request) -> JSONResponse:
        home = get_fleet_home()
        if not (_task_dir(home, task_id) / "task.json").exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        queue = request.app.state.queue
        try:
            await asyncio.to_thread(queue.close, task_id)
        except BeadsError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"ok": True})

    @router.delete("/tasks/{task_id}")
    async def delete_task(task_id: str, request: Request) -> JSONResponse:
        home = get_fleet_home()
        if not (_task_dir(home, task_id) / "task.json").exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        queue = request.app.state.queue
        try:
            await asyncio.to_thread(queue.delete, task_id)
        except BeadsError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"ok": True})

    @router.post("/tasks/{task_id}/remove-assignee")
    async def remove_assignee(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        if not (_task_dir(home, task_id) / "task.json").exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        ok, err = await asyncio.to_thread(_sync_remove_assignee, task_id, home)
        if not ok:
            return JSONResponse({"error": err}, status_code=422)
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
                body.get("args"),
            )
        except BeadsError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"id": task.id}, status_code=201)

    # ------------------------------------------------------------------
    # Artifact endpoints (FR-11..FR-20)
    # ------------------------------------------------------------------

    def _artifact_path(task_id: str, filename: str, home: Path) -> Path:
        return _task_dir(home, task_id) / "artifacts" / filename

    def _artifact_file_response(f: Path) -> JSONResponse:
        return JSONResponse(
            {
                "content": f.read_text(encoding="utf-8"),
                "mtime": f.stat().st_mtime,
                "path": str(f.resolve()),
            }
        )

    @router.get("/tasks/{task_id}/artifacts/plan")
    async def get_artifact_plan(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = _artifact_path(task_id, "PLAN.md", home)
        if not f.exists():
            # Fall back to the pre-worker-1 combined file for old tasks.
            f = _artifact_path(task_id, "PLAN_AND_STATUS.md", home)
        if not f.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return _artifact_file_response(f)

    @router.get("/tasks/{task_id}/artifacts/handoff")
    async def get_artifact_handoff(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = _artifact_path(task_id, "HANDOFF.md", home)
        if not f.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return _artifact_file_response(f)

    @router.get("/tasks/{task_id}/artifacts/knowledge")
    async def get_artifact_knowledge(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = _artifact_path(task_id, "KNOWLEDGE.md", home)
        if not f.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return _artifact_file_response(f)

    @router.get("/tasks/{task_id}/artifacts/result")
    async def get_artifact_result(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = _artifact_path(task_id, "RESULT.json", home)
        if not f.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return _artifact_file_response(f)

    @router.get("/tasks/{task_id}/logs")
    async def get_task_logs(task_id: str, level: str | None = None) -> JSONResponse:
        home = get_fleet_home()
        log_file = _task_dir(home, task_id) / "log.jsonl"
        entries: list[dict] = []
        if log_file.exists():
            try:
                for raw in log_file.read_text(encoding="utf-8").splitlines():
                    entry = _parse_log_line(raw)
                    if entry is None:
                        continue
                    if level and entry.level != level:
                        continue
                    entries.append(
                        {
                            "ts": entry.ts,
                            "level": entry.level,
                            "message": entry.message,
                            "extra": entry.extra,
                        }
                    )
            except OSError:
                pass
        return JSONResponse({"lines": entries})

    @router.get("/tasks/{task_id}/stderr")
    async def get_task_stderr(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = _task_dir(home, task_id) / "log.stderr"
        content = f.read_text(encoding="utf-8") if f.exists() else ""
        return JSONResponse({"content": content})

    @router.get("/tasks/{task_id}/diff")
    async def get_task_diff(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        task_file = _task_dir(home, task_id) / "task.json"
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
                "git",
                "-C",
                cwd,
                "diff",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            diff_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        except (TimeoutError, OSError):
            diff_text = ""
        return JSONResponse({"diff": diff_text})

    @router.get("/tasks/{task_id}/files")
    async def get_task_files(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        counts = scan_cached(_task_dir(home, task_id)).files_touched
        files = [
            {"path": path, "read": fc.read, "edit": fc.edit, "write": fc.write}
            for path, fc in sorted(counts.items())
        ]
        return JSONResponse({"files": files})

    @router.get("/tasks/{task_id}/events")
    async def get_task_events(
        task_id: str,
        offset: int | None = None,
        limit: int = 100,
        kind: str | None = None,
    ) -> JSONResponse:
        home = get_fleet_home()
        task_dir = _task_dir(home, task_id)
        if not task_dir.is_dir():
            return JSONResponse({"error": "not found"}, status_code=404)
        events_file = task_dir / "events.jsonl"
        if not events_file.exists():
            return JSONResponse({"total": 0, "offset": 0, "events": []})
        # Read and parse
        allow_kinds: set[str] | None = None
        if kind:
            allow_kinds = {k.strip() for k in kind.split(",") if k.strip()}
        all_events: list[dict] = []
        raw_total = 0
        try:
            with events_file.open("r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    raw_total += 1
                    row_kind = row.get("kind", "")
                    if allow_kinds is not None and row_kind not in allow_kinds:
                        continue
                    raw_data = row.get("raw", {})
                    if isinstance(raw_data, str):
                        try:
                            raw_data = json.loads(raw_data)
                        except (json.JSONDecodeError, ValueError):
                            raw_data = {}
                    evt = {
                        "i": 0,
                        "ts": row.get("ts", ""),
                        "kind": row_kind,
                        "session_id": row.get("session_id", row.get("sessionID")),
                        "tool_name": row.get("tool_name"),
                        "usage": row.get("usage"),
                        "summary": _event_summary(
                            row_kind,
                            raw_data if isinstance(raw_data, dict) else {},
                            row.get("tool_name"),
                        ),
                        "raw": raw_data if isinstance(raw_data, dict) else {},
                    }
                    all_events.append(evt)
        except OSError:
            pass
        filtered = all_events
        total = len(filtered)
        if offset is None:
            # Return tail (last `limit` events)
            start = max(0, total - limit)
            offset = start
        else:
            offset = max(0, offset)
        page = filtered[offset : offset + limit]
        for idx, evt in enumerate(page):
            evt["i"] = offset + idx
        return JSONResponse({"total": total, "offset": offset, "events": page})

    @router.get("/coders")
    async def list_coders() -> JSONResponse:
        return JSONResponse({"coders": _list_coders()})

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
