"""Chat tab — pending ask_human questions from the injected store."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fleet.serve.api.models import AnswerResponse, QuestionListResponse
from fleet.serve.state import StateDep

router = APIRouter(prefix="/api/chat")


@router.get("/questions", response_model=QuestionListResponse)
async def list_questions(state: StateDep) -> JSONResponse:
    """Pending ask_human questions for the chat tab."""
    pending = await asyncio.to_thread(state.question_store.fetch_pending)
    return JSONResponse({"now": time.time(), "pending": [q.to_dict() for q in pending]})


@router.post("/questions/{qid}/answer", response_model=AnswerResponse)
async def answer_question(qid: str, request: Request, state: StateDep) -> JSONResponse:
    """Record the operator's answer to one question."""
    body = await request.json()
    raw_answer = body.get("answer", "")
    result = await asyncio.to_thread(
        state.question_store.answer_result, qid, raw_answer, answered_by="web"
    )
    return JSONResponse(result)
