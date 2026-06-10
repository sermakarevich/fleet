"""Shared SQLite helper for the ask_human question DB."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

ASK_HUMAN_DB = Path(
    os.environ.get("ASK_HUMAN_DB")
    or (Path.home() / ".claude" / "ask_human" / "questions.db")
)


def get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path if db_path is not None else ASK_HUMAN_DB
    conn = sqlite3.connect(str(path), timeout=5.0)
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


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("options", "default_answer"):
        if key in d:
            d[key] = _loads(d[key])
    d["multi_select"] = bool(d.get("multi_select", 0))
    return d


def fetch_pending_questions(limit: int = 200, *, db_path: Path | None = None) -> list[dict]:
    path = db_path if db_path is not None else ASK_HUMAN_DB
    if not path.exists():
        return []
    conn = get_conn(path)
    try:
        rows = conn.execute(
            "SELECT id, agent_id, session_id, prompt, options, multi_select, "
            "priority, created_at, timeout_s, default_answer "
            "FROM questions WHERE status='pending' "
            "ORDER BY priority DESC, created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [row_to_dict(r) for r in rows]
    finally:
        conn.close()


def fetch_new_questions(since: float, *, db_path: Path | None = None) -> list[dict]:
    path = db_path if db_path is not None else ASK_HUMAN_DB
    if not path.exists():
        return []
    conn = get_conn(path)
    try:
        rows = conn.execute(
            "SELECT id, agent_id, session_id, prompt, options, multi_select, "
            "priority, created_at, timeout_s, default_answer "
            "FROM questions WHERE status='pending' AND created_at > ? "
            "ORDER BY created_at ASC LIMIT 100",
            (since,),
        ).fetchall()
        return [row_to_dict(r) for r in rows]
    finally:
        conn.close()


def max_created_at(*, db_path: Path | None = None) -> float:
    path = db_path if db_path is not None else ASK_HUMAN_DB
    if not path.exists():
        return 0.0
    conn = get_conn(path)
    try:
        row = conn.execute("SELECT MAX(created_at) FROM questions").fetchone()
        return float(row[0]) if row[0] is not None else 0.0
    finally:
        conn.close()


def get_question(qid: str, *, db_path: Path | None = None) -> dict | None:
    path = db_path if db_path is not None else ASK_HUMAN_DB
    if not path.exists():
        return None
    conn = get_conn(path)
    try:
        row = conn.execute(
            "SELECT id, agent_id, session_id, prompt, options, multi_select, "
            "priority, created_at, timeout_s, default_answer, status, answer, answered_by, answered_at "
            "FROM questions WHERE id=?",
            (qid,),
        ).fetchone()
        if row is None:
            return None
        return row_to_dict(row)
    finally:
        conn.close()


def count_pending(*, db_path: Path | None = None) -> int:
    path = db_path if db_path is not None else ASK_HUMAN_DB
    if not path.exists():
        return 0
    conn = get_conn(path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM questions WHERE status='pending'").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def answer_question(qid: str, raw_answer: object, answered_by: str, *, db_path: Path | None = None) -> dict:
    path = db_path if db_path is not None else ASK_HUMAN_DB
    if not path.exists():
        return {"ok": False, "status": "missing"}
    conn = get_conn(path)
    try:
        row = conn.execute(
            "SELECT multi_select, status FROM questions WHERE id=?", (qid,)
        ).fetchone()
        if not row:
            return {"ok": False, "status": "missing"}
        if row["status"] != "pending":
            return {"ok": False, "status": row["status"]}
        stored = json.dumps(raw_answer)
        cur = conn.execute(
            "UPDATE questions SET status='answered', answer=?, answered_by=?, answered_at=? "
            "WHERE id=? AND status='pending'",
            (stored, answered_by, time.time(), qid),
        )
        conn.commit()
        ok = cur.rowcount > 0
    finally:
        conn.close()
    return {"ok": ok, "status": "answered" if ok else "conflict"}
