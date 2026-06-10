"""SQLite-backed question store for the ask_human MCP server.

Vendored from the standalone agent-chat project (~/git/claude/mcp/ask_human);
keep behavior-identical so the two stay easy to diff. ``fleet.ask_human_db``
is the serve process's lightweight reader/answerer over the same DB file.

This is the single source of truth shared by the MCP server (writers: agents
asking questions) and the operator frontends (CLI / web, which read
pending questions and write answers). It is concurrency-safe:

* WAL journal mode + a generous ``busy_timeout`` let many agent writers and
  operator readers/writers coexist without "database is locked" errors.
* Answering is a single conditional ``UPDATE ... WHERE status='pending'`` so
  the first responder wins and two operators can never double-answer.

Values that may be structured (``options``, ``answer``, ``default_answer``)
are stored as JSON text and decoded on read.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

DEFAULT_DB_PATH = Path(
    os.environ.get("ASK_HUMAN_DB")
    or (Path.home() / ".claude" / "ask_human" / "questions.db")
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id             TEXT PRIMARY KEY,
    agent_id       TEXT,
    session_id     TEXT,
    prompt         TEXT NOT NULL,
    options        TEXT,                              -- JSON array of strings, or NULL for free text
    multi_select   INTEGER NOT NULL DEFAULT 0,
    priority       INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'pending',   -- pending | answered | expired | cancelled
    answer         TEXT,                              -- JSON (list if multi_select, else string); may be NULL when the operator answers via `note` alone
    note           TEXT,                              -- operator's free-text note/correction; always allowed, even when `options` are offered
    default_answer TEXT,                              -- JSON; returned on timeout
    timeout_s      REAL,
    answered_by    TEXT,
    created_at     REAL NOT NULL,
    answered_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_questions_open
    ON questions(status, priority DESC, created_at ASC);
"""

# Statuses that mean the question is no longer waiting for a human.
_RESOLVED = ("answered", "expired", "cancelled")


def _dumps(value: Any) -> Optional[str]:
    return None if value is None else json.dumps(value)


def _loads(value: Any) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    d = dict(row)
    for key in ("options", "answer", "default_answer"):
        if key in d:
            d[key] = _loads(d[key])
    d["multi_select"] = bool(d.get("multi_select", 0))
    return d


class QuestionStore:
    """Thread- and process-safe question queue backed by a single SQLite file.

    A fresh connection is opened per operation, so instances are safe to share
    across threads and to use from independent processes (MCP server + each
    operator frontend) pointing at the same ``db_path``.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Bring an older on-disk schema up to date in place.

        ``_SCHEMA`` only runs on a *fresh* DB (``CREATE TABLE IF NOT EXISTS``),
        so columns added after a DB was first created must be patched in here.
        Each step is guarded by ``PRAGMA table_info`` so it's a no-op on a DB
        that already has the column (and never collides with the fresh schema).
        """
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(questions)")}
        if "note" not in cols:
            try:
                conn.execute("ALTER TABLE questions ADD COLUMN note TEXT")
            except sqlite3.OperationalError:
                pass  # another process (server + CLI start together) added it first

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- writes ---------------------------------------------------------------

    def create(
        self,
        prompt: str,
        options: Optional[list[str]] = None,
        multi_select: bool = False,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        timeout_s: Optional[float] = None,
        default_answer: Any = None,
        priority: int = 0,
    ) -> str:
        """Insert a new pending question and return its id."""
        qid = uuid.uuid4().hex[:12]
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO questions (id, agent_id, session_id, prompt, options, "
                "multi_select, priority, status, default_answer, timeout_s, created_at) "
                "VALUES (?,?,?,?,?,?,?, 'pending', ?,?,?)",
                (
                    qid,
                    agent_id,
                    session_id,
                    prompt,
                    _dumps(options),
                    int(multi_select),
                    priority,
                    _dumps(default_answer),
                    timeout_s,
                    now,
                ),
            )
        return qid

    def answer(
        self,
        qid: str,
        answer: Any,
        note: Optional[str] = None,
        answered_by: str = "operator",
    ) -> bool:
        """Answer a pending question. Returns False if it was already resolved.

        ``note`` is the operator's optional free-text message — always allowed,
        even on a question that offered ``options``. It may *supplement* the
        selected option(s) (extra context) or *replace* them entirely (when the
        operator picked nothing because none of the options fit, or to correct a
        wrong premise). ``answer`` is then ``None`` / ``[]`` and the substance
        lives in ``note``.
        """
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE questions SET status='answered', answer=?, note=?, answered_by=?, "
                "answered_at=? WHERE id=? AND status='pending'",
                (_dumps(answer), note or None, answered_by, time.time(), qid),
            )
            return cur.rowcount > 0

    def cancel(self, qid: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE questions SET status='cancelled', answered_at=? "
                "WHERE id=? AND status='pending'",
                (time.time(), qid),
            )
            return cur.rowcount > 0

    def _expire_if_pending(self, qid: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE questions SET status='expired', answered_at=?, "
                "answer=COALESCE(answer, default_answer) "
                "WHERE id=? AND status='pending'",
                (time.time(), qid),
            )

    # -- reads ----------------------------------------------------------------

    def get(self, qid: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM questions WHERE id=?", (qid,)
            ).fetchone()
        return _row_to_dict(row)

    def list_pending(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE status='pending' "
                "ORDER BY priority DESC, created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def resolve_id(self, prefix: str) -> Optional[str]:
        """Resolve a (possibly shortened) id prefix to a full id.

        Returns None if nothing matches; raises ValueError if ambiguous.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM questions WHERE id LIKE ?", (prefix + "%",)
            ).fetchall()
        ids = [r["id"] for r in rows]
        if not ids:
            return None
        if len(ids) > 1:
            raise ValueError(f"id prefix '{prefix}' is ambiguous ({len(ids)} matches)")
        return ids[0]

    # -- blocking wait --------------------------------------------------------

    def wait(self, qid: str, poll_interval: float = 0.5) -> dict:
        """Block until the question is resolved, then return its final row.

        Honors the question's ``timeout_s`` (measured from creation). On timeout
        the question is marked ``expired`` and its ``default_answer`` (if any)
        becomes the answer, so callers never block forever when a timeout is set.
        """
        q = self.get(qid)
        if q is None:
            raise KeyError(qid)
        deadline = (q["created_at"] + q["timeout_s"]) if q["timeout_s"] else None
        while q["status"] == "pending":
            if deadline is not None and time.time() >= deadline:
                self._expire_if_pending(qid)
                return self.get(qid)
            time.sleep(poll_interval)
            q = self.get(qid)
        return q
