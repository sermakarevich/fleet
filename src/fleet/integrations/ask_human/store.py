"""SQLite-backed question store for the ask_human MCP server.

The single owner of the questions database: every reader and writer goes
through ``QuestionStore`` (agents asking via the MCP server in
``server.py``, operators answering via the serve/chat API, the Telegram
bot, the triage loop, the job gate). Callers receive an injected instance
(``serve/state.py::AppState.question_store``); nothing reads a module
global. The MCP child-process env var (``ASK_HUMAN_DB``, owned by
``integrations/mcp_servers.py``) tells the *server* process where the DB
is — the default path below delegates to that same module, so there is
exactly one place that knows where the database lives.

Schema changes are ordered ``MIGRATIONS`` applied under
``PRAGMA user_version``: a fresh database is created at the latest version,
an old one is migrated step by step, and a database whose version stamp
claims more than its columns deliver (a half-applied schema) is repaired
instead of silently obeyed.

Concurrency-safe: WAL journal mode + a generous ``busy_timeout`` let many
agent writers and operator readers/writers coexist without "database is
locked" errors. Each thread holds exactly one connection (created once,
PRAGMAs set once); separate processes still get separate connections.
Answering is a single conditional
``UPDATE ... WHERE status='pending'`` so the first responder wins and two
operators can never double-answer.

Values that may be structured (``options``, ``answer``, ``default_answer``)
are stored as JSON text and decoded on read.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fleet.core.errors import Json, QuestionNotFound
from fleet.integrations.mcp_servers import ASK_HUMAN_DB_ENV, ask_human_db_path
from fleet.state.paths import fleet_home


def _default_db_path() -> Path:
    """DB location when the caller passes no path.

    ``ASK_HUMAN_DB`` (set by ``mcp_servers`` for the MCP server child)
    wins; otherwise the shared file under FLEET_HOME. Never a personal
    ``~/.claude`` directory.
    """
    override = os.environ.get(ASK_HUMAN_DB_ENV)
    if override:
        return Path(override)
    return ask_human_db_path(fleet_home())


_SCHEMA_BASE = """
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
    default_answer TEXT,  -- JSON; returned on timeout
    timeout_s      REAL,
    answered_by    TEXT,
    created_at     REAL NOT NULL,
    answered_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_questions_open
    ON questions(status, priority DESC, created_at ASC);
"""

# Ordered schema steps after the base table above, applied under
# PRAGMA user_version. Each statement adds exactly one column; the column
# name is parsed back out (see _migration_column) so a half-applied schema
# (version stamp ahead of its columns) is detected and repaired.
MIGRATIONS: list[str] = [
    "ALTER TABLE questions ADD COLUMN note TEXT",
    "ALTER TABLE questions ADD COLUMN task_id TEXT",
    "ALTER TABLE questions ADD COLUMN context TEXT",
]

#: Schema level of a fully migrated database: the number of MIGRATIONS.
SCHEMA_VERSION = len(MIGRATIONS)

_TASK_INDEX = "CREATE INDEX IF NOT EXISTS idx_questions_task ON questions(task_id, context, status)"

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


def _migration_column(statement: str) -> str:
    """Column name added by an ``ALTER TABLE ... ADD COLUMN <name> ...`` step."""
    parts = statement.split()
    return parts[parts.index("COLUMN") + 1]


def _user_version(conn: sqlite3.Connection) -> int:
    """Schema level stamped on the database (0 when never migrated)."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _column_names(conn: sqlite3.Connection) -> set[str]:
    """Live column names of the questions table."""
    return {row["name"] for row in conn.execute("PRAGMA table_info(questions)")}


def _add_column(conn: sqlite3.Connection, statement: str, column: str) -> None:
    """Run one ALTER TABLE step, tolerating a concurrent migrator winning the race."""
    try:
        conn.execute(statement)
    except sqlite3.OperationalError:
        if column not in _column_names(conn):
            raise


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Bring the on-disk schema to SCHEMA_VERSION, in MIGRATIONS order.

    Fresh databases get the base table plus every step; old ones get the
    missing steps; a database stamped ahead of its columns gets the steps
    it is actually missing. The version stamp is written last.
    """
    conn.executescript(_SCHEMA_BASE)
    columns = _column_names(conn)
    for statement in MIGRATIONS:
        column = _migration_column(statement)
        if column in columns:
            continue
        _add_column(conn, statement, column)
        columns.add(column)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.execute(_TASK_INDEX)


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


# Blocking-wait cadence shared by QuestionStore.wait and the async MCP
# server: poll every second, slowing to every five seconds after a minute.
_POLL_BASE_S = 1.0
_POLL_SLOW_S = 5.0
_BACKOFF_AFTER_S = 60.0


def _poll_interval(elapsed_s: float, base_s: float) -> float:
    """Wait cadence: base rate for the first minute, then the slow rate."""
    if elapsed_s < _BACKOFF_AFTER_S:
        return base_s
    return max(base_s, _POLL_SLOW_S)


def wait_for_answer(
    store: QuestionStore,
    qid: str,
    *,
    poll_interval: float = _POLL_BASE_S,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> Question:
    """Block until the question resolves, then return its final row.

    The one blocking-wait implementation: ``QuestionStore.wait`` calls it
    directly and the async MCP server runs it in a worker thread (see
    ``server._await_answer``). Honors the question's ``timeout_s``
    (measured from creation): on timeout the question is marked
    ``expired`` and its ``default_answer`` (if any) becomes the answer.
    ``clock``/``sleep`` are injectable so tests never wait on wall time.
    """
    question = store.get(qid)
    if question is None:
        raise QuestionNotFound(qid, store.db_path)
    start = clock()
    deadline = (question.created_at + question.timeout_s) if question.timeout_s else None
    while question.status == "pending":
        if deadline is not None and clock() >= deadline:
            store.expire_if_pending(qid)
            resolved = store.get(qid)
            if resolved is None:
                raise QuestionNotFound(qid, store.db_path)
            return resolved
        sleep(_poll_interval(clock() - start, poll_interval))
        question = store.get(qid)
        if question is None:
            raise QuestionNotFound(qid, store.db_path)
    return question


class QuestionStore:
    """Thread- and process-safe question queue backed by a single SQLite file.

    Each thread holds exactly one connection (opened on first use, PRAGMAs
    set once), so instances are safe to share across threads; separate
    processes (MCP server + each operator frontend) still get their own
    connections to the same ``db_path`` and coordinate through WAL mode.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self._conn() as conn:
            _apply_migrations(conn)

    def _connect(self) -> sqlite3.Connection:
        """Open a fresh connection with the store PRAGMAs set exactly once."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Yield the calling thread's single connection, committing on success."""
        try:
            conn = self._local.connection
        except AttributeError:
            conn = self._connect()
            self._local.connection = conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        """Close the calling thread's connection, if it has one."""
        try:
            conn = self._local.connection
        except AttributeError:
            return
        del self._local.connection
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
        """Cancel a pending question; False when already resolved."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE questions SET status='cancelled', answered_at=? "
                "WHERE id=? AND status='pending'",
                (time.time(), qid),
            )
            return cur.rowcount > 0

    def expire_if_pending(self, qid: str) -> None:
        """Mark a pending question expired, falling back to its default answer."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE questions SET status='expired', answered_at=?, "
                "answer=COALESCE(answer, default_answer) "
                "WHERE id=? AND status='pending'",
                (time.time(), qid),
            )

    # -- reads ----------------------------------------------------------------

    def get(self, qid: str) -> Question | None:
        """One question by id, or None when unknown."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        return _row_to_question(row) if row is not None else None

    def list_pending(self, limit: int = 100) -> list[Question]:
        """Pending questions, highest priority first."""
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

    def wait(self, qid: str, poll_interval: float = _POLL_BASE_S) -> Question:
        """Block until the question is resolved, then return its final row.

        Honors the question's ``timeout_s`` (measured from creation). On timeout
        the question is marked ``expired`` and its ``default_answer`` (if any)
        becomes the answer, so callers never block forever when a timeout is set.
        See ``wait_for_answer`` for the shared implementation.
        """
        return wait_for_answer(self, qid, poll_interval=poll_interval)
