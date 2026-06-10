"""Chat tab — proxy to the ask_human SQLite DB."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import fleet.ask_human_db as _ahdb
from fleet.ask_human_db import ASK_HUMAN_DB  # re-exported; tests monkeypatch this


def _get_conn():
    return _ahdb.get_conn(db_path=ASK_HUMAN_DB)


def _row_to_dict(row):
    return _ahdb.row_to_dict(row)


def _fetch_pending_questions() -> list[dict]:
    return _ahdb.fetch_pending_questions(db_path=ASK_HUMAN_DB)


def _do_answer_question(qid: str, raw_answer: object) -> dict:
    return _ahdb.answer_question(qid, raw_answer, "web", db_path=ASK_HUMAN_DB)


def create_chat_router() -> APIRouter:
    router = APIRouter(prefix="/api/chat")

    @router.get("/questions")
    async def list_questions() -> JSONResponse:
        pending = await asyncio.to_thread(_fetch_pending_questions)
        return JSONResponse({"now": time.time(), "pending": pending})

    @router.post("/questions/{qid}/answer")
    async def answer_question(qid: str, request: Request) -> JSONResponse:
        body = await request.json()
        raw_answer = body.get("answer", "")
        result = await asyncio.to_thread(_do_answer_question, qid, raw_answer)
        return JSONResponse(result)

    return router
