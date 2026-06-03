"""Chat tab — proxy to the ask_human SQLite DB."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

ASK_HUMAN_DB = Path(
    os.environ.get("ASK_HUMAN_DB")
    or (Path.home() / ".claude" / "ask_human" / "questions.db")
)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(ASK_HUMAN_DB), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _loads(value: object) -> object:
    if value is None:
        return None
    try:
        return json.loads(value)  # type: ignore[arg-type]
    except (TypeError, json.JSONDecodeError):
        return value


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("options", "default_answer"):
        if key in d:
            d[key] = _loads(d[key])
    d["multi_select"] = bool(d.get("multi_select", 0))
    return d


def create_chat_router() -> APIRouter:
    router = APIRouter(prefix="/api/chat")

    @router.get("/questions")
    async def list_questions() -> JSONResponse:
        if not ASK_HUMAN_DB.exists():
            return JSONResponse({"now": time.time(), "pending": []})
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT id, agent_id, session_id, prompt, options, multi_select, "
                "priority, created_at, timeout_s, default_answer "
                "FROM questions WHERE status='pending' "
                "ORDER BY priority DESC, created_at ASC LIMIT 200",
            ).fetchall()
        finally:
            conn.close()
        return JSONResponse({"now": time.time(), "pending": [_row_to_dict(r) for r in rows]})

    @router.post("/questions/{qid}/answer")
    async def answer_question(qid: str, request: Request) -> JSONResponse:
        if not ASK_HUMAN_DB.exists():
            return JSONResponse({"ok": False, "status": "missing"})
        body = await request.json()
        raw_answer = body.get("answer", "")
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT multi_select, status FROM questions WHERE id=?", (qid,)
            ).fetchone()
            if not row:
                return JSONResponse({"ok": False, "status": "missing"})
            if row["status"] != "pending":
                return JSONResponse({"ok": False, "status": row["status"]})
            # Mirror store.answer() exactly: json.dumps wraps the value
            stored = json.dumps(raw_answer)
            cur = conn.execute(
                "UPDATE questions SET status='answered', answer=?, answered_by=?, answered_at=? "
                "WHERE id=? AND status='pending'",
                (stored, "web", time.time(), qid),
            )
            conn.commit()
            ok = cur.rowcount > 0
        finally:
            conn.close()
        return JSONResponse({"ok": ok, "status": "answered" if ok else "conflict"})

    return router
