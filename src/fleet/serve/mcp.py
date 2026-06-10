"""fleet-ask MCP server — blocking Q&A protocol (FR-22, FR-23, FR-24, FR-25, FR-30)."""
from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.serve.stats import fleet_home as get_fleet_home
from fleet.serve.watcher import ConnectionManager

DEFAULT_ANSWER = "no answer provided"


@dataclass
class PendingQuestion:
    id: str
    task_id: str
    question: str
    choices: list[str] | None
    timeout_sec: int | None
    asked_at: datetime
    status: Literal["open", "answered", "timed_out", "deferred"]
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    answer: str | None = None


class PendingQuestionStore:
    def __init__(self, store_path: Path | None = None) -> None:
        self._questions: dict[str, PendingQuestion] = {}
        self._store_path = store_path
        if store_path is not None:
            self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if self._store_path is None:
            return
        data = [
            {
                "id": q.id,
                "task_id": q.task_id,
                "question": q.question,
                "choices": q.choices,
                "timeout_sec": q.timeout_sec,
                "asked_at": q.asked_at.isoformat(),
                "status": q.status,
                "answer": q.answer,
            }
            for q in self._questions.values()
        ]
        tmp = self._store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._store_path)

    def _load(self) -> None:
        if self._store_path is None or not self._store_path.exists():
            return
        try:
            items = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for item in items:
            try:
                q = PendingQuestion(
                    id=item["id"],
                    task_id=item["task_id"],
                    question=item["question"],
                    choices=item.get("choices"),
                    timeout_sec=item.get("timeout_sec"),
                    asked_at=datetime.fromisoformat(item["asked_at"]),
                    status=item["status"],
                    answer=item.get("answer"),
                )
                if q.status != "open":
                    q._event.set()
                self._questions[q.id] = q
            except (KeyError, ValueError):
                continue

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(
        self,
        task_id: str,
        question: str,
        choices: list[str] | None,
        timeout_sec: int | None,
    ) -> PendingQuestion:
        q = PendingQuestion(
            id=str(uuid.uuid4()),
            task_id=task_id,
            question=question,
            choices=choices,
            timeout_sec=timeout_sec,
            asked_at=datetime.now(tz=timezone.utc),
            status="open",
        )
        self._questions[q.id] = q
        self._save()
        return q

    def answer(self, question_id: str, answer: str) -> bool:
        q = self._questions.get(question_id)
        if q is None or q.status != "open":
            return False
        q.answer = answer
        q.status = "answered"
        q._event.set()
        self._save()
        return True

    def defer(self, question_id: str) -> bool | str:
        """Return True on success, False if not found/resolved, error string if bd fails."""
        q = self._questions.get(question_id)
        if q is None or q.status != "open":
            return False
        result = subprocess.run(
            ["bd", "update", q.task_id, "--status", "blocked"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return result.stderr.strip() or "bd update --status blocked failed"
        q.status = "deferred"
        q.answer = "__DEFERRED__"
        q._event.set()
        self._save()
        return True

    def mark_timed_out(self, question_id: str) -> None:
        q = self._questions.get(question_id)
        if q is not None:
            q.status = "timed_out"
            self._save()

    def list(self) -> list[PendingQuestion]:
        return sorted(self._questions.values(), key=lambda q: q.asked_at, reverse=True)


def _write_qa_block(task_dir: Path, question: PendingQuestion) -> None:
    """Append ## Q: block to artifacts/Q&A.md in back-compat format."""
    qa_file = task_dir / "artifacts" / "Q&A.md"
    if not qa_file.parent.exists():
        return
    ts = question.asked_at.strftime("%Y-%m-%d %H:%M")
    block = f"\n## Q: {question.question} — {ts}, fleet-ask\n"
    if question.choices:
        block += f"**Choices:** {', '.join(question.choices)}\n"
    with qa_file.open("a") as fh:
        fh.write(block)


def _emit_ask_human_event(
    task_dir: Path,
    question_id: str,
    question_text: str,
    choices: list[str] | None,
) -> None:
    """Append ask_human JSONL line to events.jsonl (kind stored in extra per spec)."""
    events_file = task_dir / "events.jsonl"
    ts = datetime.now(tz=timezone.utc).isoformat()
    event = {
        "ts": ts,
        "extra": {
            "kind": "ask_human",
            "question_id": question_id,
            "question": question_text,
            "choices": choices,
        },
    }
    with events_file.open("a") as fh:
        fh.write(json.dumps(event) + "\n")


def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


_ASK_HUMAN_TOOL = {
    "name": "ask_human",
    "description": "Ask the fleet operator a question and block until answered.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "choices": {"type": "array", "items": {"type": "string"}},
            "timeout_sec": {"type": "integer"},
        },
        "required": ["question"],
    },
}


async def _handle_ask_human(
    req_id: Any,
    args: dict,
    task_id: str,
    store: PendingQuestionStore,
    mgr: ConnectionManager,
) -> dict:
    question_text = args["question"]
    choices: list[str] | None = args.get("choices")
    timeout_sec: int | None = args.get("timeout_sec")

    q = store.add(task_id, question_text, choices, timeout_sec)

    task_dir = get_fleet_home() / "tasks" / task_id
    if task_dir.is_dir():
        _write_qa_block(task_dir, q)
        _emit_ask_human_event(task_dir, q.id, question_text, choices)

    await mgr.broadcast(
        task_id,
        {
            "kind": "ask_human",
            "ts": q.asked_at.isoformat(),
            "extra": {
                "question_id": q.id,
                "question": question_text,
                "choices": choices,
            },
        },
    )

    try:
        if timeout_sec is not None:
            await asyncio.wait_for(q._event.wait(), timeout=float(timeout_sec))
        else:
            await q._event.wait()
        answer = q.answer or DEFAULT_ANSWER
    except asyncio.TimeoutError:
        store.mark_timed_out(q.id)
        answer = DEFAULT_ANSWER

    return _ok(req_id, {"content": [{"type": "text", "text": answer}]})


def create_mcp_router(store: PendingQuestionStore, mgr: ConnectionManager) -> APIRouter:
    router = APIRouter()

    @router.post("/mcp")
    async def mcp_endpoint(request: Request) -> JSONResponse:
        body = await request.json()
        req_id = body.get("id")
        method = body.get("method", "")
        params = body.get("params", {})

        if method == "initialize":
            return JSONResponse(_ok(req_id, {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "fleet-ask", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            }))

        if method == "tools/list":
            return JSONResponse(_ok(req_id, {"tools": [_ASK_HUMAN_TOOL]}))

        if method == "tools/call":
            name = params.get("name")
            if name != "ask_human":
                return JSONResponse(_err(req_id, -32601, f"Unknown tool: {name}"))
            task_id = request.headers.get("X-Fleet-Task-ID", "unknown")
            result = await _handle_ask_human(
                req_id, params.get("arguments", {}), task_id, store, mgr
            )
            return JSONResponse(result)

        return JSONResponse(_err(req_id, -32601, f"Method not found: {method}"))

    return router


def create_qa_router(store: PendingQuestionStore) -> APIRouter:
    router = APIRouter(prefix="/api/qa")

    @router.post("/{question_id}/answer")
    async def answer_question(question_id: str, request: Request) -> JSONResponse:
        body = await request.json()
        answer_text: str = body.get("answer", DEFAULT_ANSWER)
        if store.answer(question_id, answer_text):
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "not found or already resolved"}, status_code=404)

    @router.post("/{question_id}/defer")
    async def defer_question(question_id: str) -> JSONResponse:
        result = store.defer(question_id)
        if result is True:
            return JSONResponse({"ok": True})
        if result is False:
            return JSONResponse({"error": "not found or already resolved"}, status_code=404)
        return JSONResponse({"error": result}, status_code=502)

    return router
