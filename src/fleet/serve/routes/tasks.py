"""Task CRUD + actions REST routes (FR-07, FR-11..FR-21, FR-31..FR-34)."""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.coders import get_coder, list_coders as _list_coders
from fleet.daemon import _pid_alive
from fleet.queue import BeadsError
from fleet.serve.beads_info import (
    get_beads_status_map,
)
from fleet.serve.stats import fleet_home as get_fleet_home, task_runtime_info_cached


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
    extra = {
        k: v
        for k, v in row.items()
        if k not in ("timestamp", "ts", "level", "event", "message")
    }
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


def _coder_context_limit(coder_name: str | None, model: str | None = None) -> int:
    if not coder_name:
        return 200_000
    try:
        return get_coder(coder_name).context_limit_for(model)
    except ValueError:
        return 200_000


def _build_task_summary(data: dict, home: Path) -> dict:
    task_id = data.get("id", "")
    info = task_runtime_info_cached(home / "tasks" / task_id)

    now = datetime.now(tz=timezone.utc)
    started_at = info.started_at
    elapsed_sec: float | None = (
        (now - started_at).total_seconds() if started_at else None
    )
    idle_sec: float | None = (
        (now - info.last_event_at).total_seconds() if info.last_event_at else None
    )
    context_tokens = info.context_tokens
    context_pct: float | None = None
    if context_tokens is not None:
        limit = _coder_context_limit(data.get("coder"), data.get("model"))
        context_pct = context_tokens / limit * 100

    status = data.get("status", "")
    ended_at = (
        info.last_event_at.isoformat()
        if status in ("closed", "failed") and info.last_event_at
        else None
    )

    return {
        "id": task_id,
        "title": data.get("title"),
        "description": data.get("description"),
        "status": status,
        "cwd": data.get("cwd"),
        "coder": data.get("coder"),
        "model": data.get("model"),
        "priority": data.get("priority"),
        "depends_on": data.get("depends_on") or [],
        "created_at": data.get("created_at"),
        "started_at": started_at.isoformat() if started_at else None,
        "ended_at": ended_at,
        "elapsed_sec": elapsed_sec,
        "idle_sec": idle_sec,
        "events": info.events,
        "context_tokens": context_tokens,
        "context_pct": context_pct,
        "last_event_kind": info.last_event_kind,
        "last_event_detail": info.last_event_detail,
    }


def _build_all_summaries(tasks: list[dict], home: Path) -> list[dict]:
    return [_build_task_summary(d, home) for d in tasks]


def _sync_remove_assignee(task_id: str, home: Path) -> tuple[bool, str]:
    """Clear assignee in both beads DB and task.json (if present)."""
    try:
        result = subprocess.run(
            ["bd", "update", task_id, "--assignee", ""],
            capture_output=True,
            text=True,
            cwd=home,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or "bd update failed"
    except FileNotFoundError:
        return False, "bd executable not found"
    task_file = home / "tasks" / task_id / "task.json"
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
        result = subprocess.run(
            ["bd", "show", task_id, "--json"],
            capture_output=True,
            text=True,
            cwd=home,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        data = json.loads(result.stdout)
        body = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(body, list):
            body = body[0] if body else None
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
                if task_id in beads_map:
                    bead_info = beads_map[task_id]
                    data = {
                        **data,
                        "status": bead_info["status"],
                        "created_at": bead_info.get("created_at"),
                        "priority": bead_info.get("priority"),
                    }
                else:
                    data = {**data, "status": "closed"}
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
        task_file = home / "tasks" / task_id / "task.json"
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
        return JSONResponse(_build_task_summary(data, home))

    @router.post("/tasks/{task_id}/kill")
    async def kill_task(task_id: str, request: Request) -> JSONResponse:
        home = get_fleet_home()
        task_dir = home / "tasks" / task_id
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

    @router.post("/tasks/{task_id}/close")
    async def close_task(task_id: str, request: Request) -> JSONResponse:
        home = get_fleet_home()
        if not (home / "tasks" / task_id / "task.json").exists():
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
        if not (home / "tasks" / task_id / "task.json").exists():
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
        if not (home / "tasks" / task_id / "task.json").exists():
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
        return home / "tasks" / task_id / "artifacts" / filename

    @router.get("/tasks/{task_id}/artifacts/plan")
    async def get_artifact_plan(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = _artifact_path(task_id, "PLAN_AND_STATUS.md", home)
        if not f.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(
            {
                "content": f.read_text(encoding="utf-8"),
                "mtime": f.stat().st_mtime,
                "path": str(f.resolve()),
            }
        )

    @router.get("/tasks/{task_id}/artifacts/knowledge")
    async def get_artifact_knowledge(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = _artifact_path(task_id, "KNOWLEDGE.md", home)
        if not f.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(
            {
                "content": f.read_text(encoding="utf-8"),
                "mtime": f.stat().st_mtime,
                "path": str(f.resolve()),
            }
        )

    @router.get("/tasks/{task_id}/artifacts/qa")
    async def get_artifact_qa(task_id: str) -> JSONResponse:
        home = get_fleet_home()
        f = _artifact_path(task_id, "Q&A.md", home)
        if not f.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(
            {"content": f.read_text(encoding="utf-8"), "mtime": f.stat().st_mtime}
        )

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
                "git",
                "-C",
                cwd,
                "diff",
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

    def _event_summary(kind: str, raw: dict, tool_name: str | None = None) -> str:
        """Derive a ~200-char one-line summary from a raw event dict."""
        if kind == "assistant_text":
            text = None
            part = raw.get("part")
            if isinstance(part, dict):
                t = part.get("text")
                if t is not None:
                    text = str(t)
            if text is None and isinstance(raw, dict):
                t = raw.get("text")
                if t is not None:
                    text = str(t)
            if text:
                return " ".join(text.split())[:200]
            usage = raw.get("usage", {})
            if isinstance(usage, dict):
                in_t = usage.get("input_tokens")
                out_t = usage.get("output_tokens")
                parts = []
                if in_t is not None:
                    parts.append(f"in={in_t}")
                if out_t is not None:
                    parts.append(f"out={out_t}")
                if parts:
                    return "Tokens: " + ", ".join(parts)
            return ""
        if kind == "tool_use":
            tool = tool_name or raw.get("tool", "") or ""
            inp = None
            state = raw.get("state")
            if isinstance(state, dict):
                inp = state.get("input")
            if inp is None:
                part = raw.get("part")
                if isinstance(part, dict):
                    ps = part.get("state", {})
                    if isinstance(ps, dict):
                        inp = ps.get("input")
            if isinstance(inp, dict) or isinstance(inp, list):
                return json.dumps(
                    {"tool": tool, "input": inp},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )[:200]
            if inp is not None:
                return tool + " " + str(inp)[:200]
            return tool
        if kind == "tool_result":
            tool = tool_name or raw.get("tool", "") or ""
            state = raw.get("state", {})
            out_str = ""
            if isinstance(state, dict):
                out = state.get("output")
                if out is not None:
                    if isinstance(out, str):
                        out_str = out[:200]
                    else:
                        out_str = str(out)[:200]
            if out_str:
                return tool + " " + out_str
            return tool
        if kind == "error":
            err = None
            part = raw.get("part")
            if isinstance(part, dict):
                st = part.get("state", {})
                if isinstance(st, dict):
                    err = st.get("error")
            if err is None and isinstance(raw, dict):
                err = raw.get("error") or raw.get("message")
            display_tool = tool_name or raw.get("tool", "") or ""
            if display_tool:
                if err is not None:
                    return display_tool + ": " + str(err)[:200]
                return display_tool + ": " + json.dumps(raw, ensure_ascii=False)[:200]
            if err is not None:
                return "Error: " + str(err)[:200]
            return "Error: " + json.dumps(raw, ensure_ascii=False)[:200]
        if kind == "session_started":
            sid = raw.get("sessionID", "") or raw.get("session_id", "") or ""
            last8 = str(sid)[-8:] if sid else "?"
            return "Step start (session " + last8 + ")"
        if kind == "session_ended":
            tokens = raw.get("tokens", {})
            if isinstance(tokens, dict):
                in_t = tokens.get("input")
                out_t = tokens.get("output")
                parts = []
                if in_t is not None:
                    parts.append(f"in={in_t}")
                if out_t is not None:
                    parts.append(f"out={out_t}")
                if parts:
                    return "Session end (" + ", ".join(parts) + ")"
            return "Session end"
        return ""

    @router.get("/tasks/{task_id}/events")
    async def get_task_events(
        task_id: str,
        offset: int | None = None,
        limit: int = 100,
        kind: str | None = None,
    ) -> JSONResponse:
        home = get_fleet_home()
        task_dir = home / "tasks" / task_id
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
