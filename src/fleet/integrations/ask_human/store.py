"""SQLite-backed question store for the ask_human MCP server.

The single owner of the questions database: every reader and writer goes
through ``QuestionStore`` (agents asking via the MCP server in
``server.py``, operators answering via the serve/chat API, the Telegram
bot, the triage loop, the job gate). Callers receive an injected instance
(``serve/state.py::AppState.question_store``); nothing reads a module
global. The MCP child-process env var (``ASK_HUMAN_DB``, owned by
``integrations/mcp_servers.py``) tells the *server* process where the DB
is — a different concern from this module.

Concurrency-safe: WAL journal mode + a generous ``busy_timeout`` let many
agent writers and operator readers/writers coexist without "database is
locked" errors. Answering is a single conditional
``UPDATE ... WHERE status='pending'`` so the first responder wins and two
operators can never double-answer.

Values that may be structured (``options``, ``answer``, ``default_answer``)
are stored as JSON text and decoded on read.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fleet.core.errors import Json, QuestionNotFound


def _default_db_path() -> Path:
    """DB location when the caller passes no path (MCP server default)."""
    return Path(
        os.environ.get("ASK_HUMAN_DB") or (Path.home() / ".claude" / "ask_human" / "questions.db")
    )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id             TEXT PRIMARY KEY,
    agent_id       TEXT,
    session_id     TEXT,
    prompt         TEXT NOT NULL,
    options        TEXT,  -- JSON string array, or NULL for free text
    multi_select   INTEGER NOT NULL DEFAULT 0,
    priority       INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | answered | expired | cancelled
    answer         TEXT,  -- JSON answer; NULL when answered via `note` alone
    note           TEXT,  -- free-text note; always allowed alongside `options`
    default_answer TEXT,  -- JSON; returned on timeout
    timeout_s      REAL,
    answered_by    TEXT,
    created_at     REAL NOT NULL,
    answered_at    REAL,
    task_id        TEXT,  -- bead this question is about, or NULL
    context        TEXT   -- disambiguator, e.g. blocked_at; digest id-lists
);
CREATE INDEX IF NOT EXISTS idx_questions_open
    ON questions(status, priority DESC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_questions_task
    ON questions(task_id, context, status);
"""

# Statuses that mean the question is no longer waiting for a human.
_RESOLVED = ("answered", "expired", "cancelled")


def _dumps(value: Any) -> str | None:
    """Encode a structured value as JSON text, or None when absent."""
    return None if value is None else json.dumps(value)


def _loads(value: Any) -> Json:
    """Decode a stored JSON text value, passing through plain text."""
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


@dataclass(frozen=True, slots=True)
class Question:
    """One ask_human question row, decoded from the SQLite store."""

    id: str
    prompt: str = ""
    status: str = "pending"
    agent_id: str | None = None
    session_id: str | None = None
    options: Json = None
    multi_select: bool = False
    priority: int = 0
    answer: Json = None
    note: str | None = None
    default_answer: Json = None
    timeout_s: float | None = None
    answered_by: str | None = None
    created_at: float = 0.0
    answered_at: float | None = None
    task_id: str | None = None
    context: str | None = None

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style read so existing callers keep working."""
        return getattr(self, key, default) if hasattr(self, key) else default

    def __getitem__(self, key: str) -> Any:
        """Dict-style index so existing callers keep working."""
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key) from None

    def to_dict(self) -> dict:
        """Plain dict for JSON API edges."""
        return asdict(self)


def _row_to_question(row: sqlite3.Row) -> Question:
    d = dict(row)
    for key in ("options", "answer", "default_answer"):
        if key in d:
            d[key] = _loads(d[key])
    return Question(
        id=str(d.get("id", "")),
        prompt=str(d.get("prompt") or ""),
        status=str(d.get("status") or "pending"),
        agent_id=d.get("agent_id"),
        session_id=d.get("session_id"),
        options=d.get("options"),
        multi_select=bool(d.get("multi_select", 0)),
        priority=int(d.get("priority") or 0),
        answer=d.get("answer"),
        note=d.get("note"),
        default_answer=d.get("default_answer"),
        timeout_s=d.get("timeout_s"),
        answered_by=d.get("answered_by"),
        created_at=float(d.get("created_at") or 0.0),
        answered_at=d.get("answered_at"),
        task_id=d.get("task_id"),
        context=d.get("context"),
    )


def _row_to_dict(row: sqlite3.Row) -> dict:
    return _row_to_question(row).to_dict()


class QuestionStore:
    """Thread- and process-safe question queue backed by a single SQLite file.

    A fresh connection is opened per operation, so instances are safe to share
    across threads and to use from independent processes (MCP server + each
    operator frontend) pointing at the same ``db_path``.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            # Pre-existing DB from before some columns existed: the
            # CREATE TABLE went through but a later statement (index on
            # a not-yet-migrated column) failed. _migrate below adds the
            # missing columns and re-creates the indexes.
            with suppress(sqlite3.OperationalError):
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
            # Another process (server + CLI start together) may add it first.
            with suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE questions ADD COLUMN note TEXT")
        if "task_id" not in cols:
            with suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE questions ADD COLUMN task_id TEXT")
        if "context" not in cols:
            with suppress(sqlite3.OperationalError):
                conn.execute("ALTER TABLE questions ADD COLUMN context TEXT")
        # Index for the triage pending lookup (task_id + blocked_at); harmless
        # to re-run on a DB that already has it.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_questions_task ON questions(task_id, context, status)"
        )

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

    def ask(
        self,
        prompt: str,
        options: list[str] | None = None,
        *,
        task_id: str | None = None,
        context: str | None = None,
        agent_id: str = "triage",
        priority: int = 0,
        multi_select: bool = False,
    ) -> str:
        """Post a non-blocking question about a fleet bead; return its id.

        Insert-only: unlike the MCP server's ask-and-wait flow this never
        blocks — the supervisor's triage loop (and the future job worker's
        human gate) collect answers on a later tick via
        ``fetch_pending_for_task`` / ``fetch_answered_triage``. ``context``
        disambiguates repeat questions about the same bead (triage stores
        task.json ``blocked_at`` there).
        """
        return self._insert(
            prompt,
            options,
            multi_select=multi_select,
            agent_id=agent_id,
            priority=priority,
            task_id=task_id,
            context=context,
        )

    def _insert(  # noqa: PLR0913  # ADR 0006 bead 11
        self,
        prompt: str,
        options: list[str] | None,
        *,
        multi_select: bool = False,
        agent_id: str | None = None,
        session_id: str | None = None,
        timeout_s: float | None = None,
        default_answer: Json = None,
        priority: int = 0,
        task_id: str | None = None,
        context: str | None = None,
    ) -> str:
        qid = uuid.uuid4().hex[:12]
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO questions (id, agent_id, session_id, prompt, options, "
                "multi_select, priority, status, default_answer, timeout_s, created_at, "
                "task_id, context) "
                "VALUES (?,?,?,?,?,?,?, 'pending', ?,?,?,?,?)",
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
                    task_id,
                    context,
                ),
            )
        return qid

    def create(
        self,
        prompt: str,
        options: list[str] | None = None,
        multi_select: bool = False,
        agent_id: str | None = None,
        session_id: str | None = None,
        timeout_s: float | None = None,
        default_answer: Json = None,
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

    def fetch_pending_for_task(self, task_id: str, context: str | None = None) -> list[Question]:
        """Pending questions about one bead, optionally for one context.

        Triage passes the bead's ``blocked_at`` as context so a re-blocked
        task (new blocked_at) gets a fresh question while the old block's
        question is still pending.
        """
        with self._conn() as conn:
            if context is None:
                rows = conn.execute(
                    "SELECT * FROM questions WHERE status='pending' AND task_id=? "
                    "ORDER BY created_at ASC",
                    (task_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM questions WHERE status='pending' AND task_id=? "
                    "AND context=? ORDER BY created_at ASC",
                    (task_id, context),
                ).fetchall()
        return [_row_to_question(r) for r in rows]

    def fetch_answered_triage(self, limit: int = 100) -> list[Question]:
        """Answered triage questions (agent_id='triage'), oldest first.

        The triage loop applies each answer once: applying changes the bead
        (release/close/ignore), so an already-applied question no longer
        matches its bead's live blocked state and is skipped naturally.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE status='answered' AND agent_id='triage' "
                "ORDER BY answered_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_question(r) for r in rows]

    def fetch_answered_for_task(self, task_id: str, context: str | None = None) -> list[Question]:
        """Answered questions about one bead, oldest first (job gate lookup).

        The job worker's gate step asks with ``context="job_gate"`` and
        applies the latest answered row once: applying moves the job forward
        (APPROVED marker, tasks.json deleted, or bead blocked), so an
        already-applied question no longer matches the live gate state and
        is skipped naturally.
        """
        with self._conn() as conn:
            if context is None:
                rows = conn.execute(
                    "SELECT * FROM questions WHERE status='answered' AND task_id=? "
                    "ORDER BY answered_at ASC",
                    (task_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM questions WHERE status='answered' AND task_id=? "
                    "AND context=? ORDER BY answered_at ASC",
                    (task_id, context),
                ).fetchall()
        return [_row_to_question(r) for r in rows]

    def answer(
        self,
        qid: str,
        answer: Json,
        note: str | None = None,
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

    def expire_if_pending(self, qid: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE questions SET status='expired', answered_at=?, "
                "answer=COALESCE(answer, default_answer) "
                "WHERE id=? AND status='pending'",
                (time.time(), qid),
            )

    # -- reads ----------------------------------------------------------------

    def get(self, qid: str) -> Question | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        return _row_to_question(row) if row is not None else None

    def list_pending(self, limit: int = 100) -> list[Question]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE status='pending' "
                "ORDER BY priority DESC, created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_question(r) for r in rows]

    def fetch_pending(self, limit: int = 200) -> list[Question]:
        """Pending questions, highest priority first (chat tab + telegram)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE status='pending' "
                "ORDER BY priority DESC, created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_question(r) for r in rows]

    def fetch_new(self, since: float, limit: int = 100) -> list[Question]:
        """Pending questions created after ``since`` (poll for new arrivals)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE status='pending' AND created_at > ? "
                "ORDER BY created_at ASC LIMIT ?",
                (since, limit),
            ).fetchall()
        return [_row_to_question(r) for r in rows]

    def max_created_at(self) -> float:
        """Newest question timestamp, 0.0 on an empty store (poll watermark)."""
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(created_at) FROM questions").fetchone()
        return float(row[0]) if row[0] is not None else 0.0

    def count_pending(self) -> int:
        """Number of questions still waiting for a human."""
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM questions WHERE status='pending'").fetchone()
        return int(row[0]) if row else 0

    def answer_result(
        self,
        qid: str,
        answer: Json,
        *,
        answered_by: str,
        note: str | None = None,
    ) -> dict:
        """Answer like ``answer`` but report ``{"ok", "status"}`` for frontends."""
        with self._conn() as conn:
            row = conn.execute("SELECT status FROM questions WHERE id=?", (qid,)).fetchone()
            if row is None:
                return {"ok": False, "status": "missing"}
            if row["status"] != "pending":
                return {"ok": False, "status": row["status"]}
            cur = conn.execute(
                "UPDATE questions SET status='answered', answer=?, note=?, answered_by=?, "
                "answered_at=? WHERE id=? AND status='pending'",
                (_dumps(answer), note, answered_by, time.time(), qid),
            )
            ok = cur.rowcount > 0
        return {"ok": ok, "status": "answered" if ok else "conflict"}

    def resolve_id(self, prefix: str) -> str | None:
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

    def wait(self, qid: str, poll_interval: float = 0.5) -> Question:
        """Block until the question is resolved, then return its final row.

        Honors the question's ``timeout_s`` (measured from creation). On timeout
        the question is marked ``expired`` and its ``default_answer`` (if any)
        becomes the answer, so callers never block forever when a timeout is set.
        """
        q = self.get(qid)
        if q is None:
            raise QuestionNotFound(qid, self.db_path)
        deadline = (q["created_at"] + q["timeout_s"]) if q["timeout_s"] else None
        while q["status"] == "pending":
            if deadline is not None and time.time() >= deadline:
                self.expire_if_pending(qid)
                q = self.get(qid)
                if q is None:
                    raise QuestionNotFound(qid, self.db_path)
                return q
            time.sleep(poll_interval)
            q = self.get(qid)
            if q is None:
                raise QuestionNotFound(qid, self.db_path)
        return q
