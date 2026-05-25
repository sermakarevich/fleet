"""Q&A list REST route (FR-30)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.serve.mcp import PendingQuestion, PendingQuestionStore
from fleet.serve.stats import fleet_home as get_fleet_home


def _question_to_dict(q: PendingQuestion, home: Path) -> dict:
    task_title = ""
    task_cwd = None
    task_file = home / "tasks" / q.task_id / "task.json"
    if task_file.exists():
        try:
            data = json.loads(task_file.read_text(encoding="utf-8"))
            task_title = data.get("title", "")
            task_cwd = data.get("cwd") or None
        except (OSError, json.JSONDecodeError):
            pass

    now = datetime.now(tz=timezone.utc)
    elapsed_sec = (now - q.asked_at).total_seconds()

    return {
        "id": q.id,
        "task_id": q.task_id,
        "task_title": task_title,
        "task_cwd": task_cwd,
        "question": q.question,
        "choices": q.choices,
        "asked_at": q.asked_at.isoformat(),
        "elapsed_sec": elapsed_sec,
        "status": q.status,
        "answer": q.answer,
    }


def create_qa_list_router() -> APIRouter:
    router = APIRouter(prefix="/api/qa")

    @router.get("")
    async def list_questions(
        request: Request,
        status: Optional[str] = None,
    ) -> JSONResponse:
        store: PendingQuestionStore = request.app.state.pending_questions
        home = get_fleet_home()
        questions = store.list()
        if status is not None:
            questions = [q for q in questions if q.status == status]
        return JSONResponse({
            "questions": [_question_to_dict(q, home) for q in questions]
        })

    return router
