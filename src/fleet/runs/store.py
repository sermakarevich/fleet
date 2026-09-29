"""SQLite run store for Fleet 2 flows (docs/27_sep_upgrade/DESIGN.md §3.4).

The single owner of `$FLEET_HOME/runs.db`: every reader and writer goes
through ``RunStore``. The status rows are the status — nothing is cached
from anywhere else. The schema is created once and stamped under
``PRAGMA user_version``; each thread holds exactly one connection, and WAL
mode plus ``busy_timeout`` let readers and writers coexist.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCHEMA_BASE = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    flow        TEXT NOT NULL,
    status      TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    reason      TEXT NOT NULL DEFAULT '',
    start_key   TEXT
);
CREATE TABLE IF NOT EXISTS step_runs (
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step        TEXT NOT NULL,
    item_index  INTEGER NOT NULL,
    status      TEXT NOT NULL,
    key         TEXT,
    after_json  TEXT NOT NULL DEFAULT '[]',
    attempt     INTEGER NOT NULL DEFAULT 0,
    started_at  TEXT,
    finished_at TEXT,
    reason      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, step, item_index)
);
CREATE INDEX IF NOT EXISTS idx_runs_flow_started
    ON runs(flow, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_flow_start_key
    ON runs(flow, start_key, status);
CREATE INDEX IF NOT EXISTS idx_step_runs_status
    ON step_runs(status);
"""

#: Schema level of a fully migrated database.
SCHEMA_VERSION = 2


class RunStatus(str, Enum):  # noqa: UP042
    """Lifecycle state of one flow run."""

    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class StepStatus(str, Enum):  # noqa: UP042
    """Lifecycle state of one step run (one step, or one for_each item)."""

    pending = "pending"
    ready = "ready"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"


#: Run states that end a run (they stamp ``finished_at``); anything else is live.
RUN_FINISHED: frozenset[RunStatus] = frozenset(
    {
        RunStatus.succeeded,
        RunStatus.failed,
        RunStatus.cancelled,
    }
)

#: Step states that end a step run (they stamp ``finished_at``).
FINISHED: frozenset[StepStatus] = frozenset(
    {
        StepStatus.succeeded,
        StepStatus.failed,
        StepStatus.skipped,
        StepStatus.cancelled,
    }
)


@dataclass(frozen=True)
class Run:
    """One execution of a flow: its inputs plus a frozen status row."""

    id: str
    flow: str
    status: RunStatus
    inputs: dict[str, Any]
    started_at: str  # ISO 8601
    finished_at: str | None = None
    reason: str = ""
    start_key: str | None = None  # the tool item key that started it, else None


@dataclass(frozen=True)
class StepRun:
    """One step run: a step, or one for_each item of a step."""

    run_id: str
    step: str
    item_index: int  # -1 when the step is not a for_each item
    status: StepStatus
    key: str | None = None  # for_each item key (DESIGN §3.2 `key`)
    after: tuple[str, ...] = ()  # item keys this item waits for
    attempt: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    reason: str = ""


def runs_db_path(fleet_home: Path) -> Path:
    """Database file holding run state under a fleet home directory."""
    return fleet_home / "runs.db"


def _user_version(conn: sqlite3.Connection) -> int:
    """Schema level stamped on the database (0 when never migrated)."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Create the schema at SCHEMA_VERSION, stamping the version last."""
    version = _user_version(conn)
    if 0 < version < SCHEMA_VERSION:
        # v2 widened idx_runs_flow_start_key with the status column: the old
        # index under the same name would otherwise survive untouched.
        conn.execute("DROP INDEX IF EXISTS idx_runs_flow_start_key")
    conn.executescript(_SCHEMA_BASE)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def _row_to_run(row: sqlite3.Row) -> Run:
    """Decode one runs row (inputs_json holds the run inputs)."""
    finished = row["finished_at"]
    start_key = row["start_key"]
    return Run(
        id=str(row["id"]),
        flow=str(row["flow"]),
        status=RunStatus(str(row["status"])),
        inputs=dict(json.loads(str(row["inputs_json"]))),
        started_at=str(row["started_at"]),
        finished_at=str(finished) if finished is not None else None,
        reason=str(row["reason"]),
        start_key=str(start_key) if start_key is not None else None,
    )


def _row_to_step_run(row: sqlite3.Row) -> StepRun:
    """Decode one step_runs row (after_json holds the waited-for item keys)."""
    key = row["key"]
    started = row["started_at"]
    finished = row["finished_at"]
    return StepRun(
        run_id=str(row["run_id"]),
        step=str(row["step"]),
        item_index=int(row["item_index"]),
        status=StepStatus(str(row["status"])),
        key=str(key) if key is not None else None,
        after=tuple(json.loads(str(row["after_json"]))),
        attempt=int(row["attempt"]),
        started_at=str(started) if started is not None else None,
        finished_at=str(finished) if finished is not None else None,
        reason=str(row["reason"]),
    )


class RunStore:
    """Thread-safe runs database backed by a single SQLite file.

    Each thread holds exactly one connection (opened on first use, PRAGMAs
    set once), so instances are safe to share across threads; separate
    processes still get their own connections and coordinate through WAL.
    """

    def __init__(self, db_path: Path) -> None:
        """Point the store at a database file, creating it when missing."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self._conn() as conn:
            _apply_migrations(conn)

    def _connect(self) -> sqlite3.Connection:
        """Open a fresh connection with the store PRAGMAs set exactly once."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
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

    def schema_version(self) -> int:
        """Schema level stamped on the open database."""
        with self._conn() as conn:
            return _user_version(conn)

    def create_run(self, run: Run) -> None:
        """Insert one run row."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO runs (id, flow, status, inputs_json, started_at, "
                "finished_at, reason, start_key) VALUES (?,?,?,?,?,?,?,?)",
                (
                    run.id,
                    run.flow,
                    run.status.value,
                    json.dumps(run.inputs),
                    run.started_at,
                    run.finished_at,
                    run.reason,
                    run.start_key,
                ),
            )

    def get_run(self, run_id: str) -> Run | None:
        """One run by id, or None when unknown."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return _row_to_run(row) if row is not None else None

    def list_runs(
        self,
        flow: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
    ) -> list[Run]:
        """Runs newest first, optionally filtered by flow and status."""
        clauses: list[str] = []
        args: list[Any] = []
        if flow is not None:
            clauses.append("flow=?")
            args.append(flow)
        if status is not None:
            clauses.append("status=?")
            args.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM runs {where} ORDER BY started_at DESC, id DESC LIMIT ?",
                (*args, limit),
            ).fetchall()
        return [_row_to_run(row) for row in rows]

    def finish_run(self, run_id: str, status: RunStatus, reason: str, finished_at: str) -> bool:
        """Close a run with its final status; False when the run is unknown."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE runs SET status=?, reason=?, finished_at=? WHERE id=?",
                (status.value, reason, finished_at, run_id),
            )
            return cur.rowcount > 0

    def has_start_key(self, flow: str, start_key: str, *, live_only: bool = True) -> bool:
        """Whether a run of *flow* was already started by *start_key*.

        With *live_only* (the default) only a still-``running`` run counts,
        so a key may start again once its previous run has finished; with
        ``live_only=False`` any run ever started by the key counts.
        """
        with self._conn() as conn:
            if live_only:
                row = conn.execute(
                    "SELECT 1 FROM runs WHERE flow=? AND start_key=? AND status=? LIMIT 1",
                    (flow, start_key, RunStatus.running.value),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM runs WHERE flow=? AND start_key=? LIMIT 1",
                    (flow, start_key),
                ).fetchone()
        return row is not None

    def last_finished_at(self, flow: str, start_key: str) -> str | None:
        """Newest ``finished_at`` of a finished run of *flow* started by *start_key*.

        None when no finished run exists for the key (never started, or only
        live runs). The ISO 8601 string compares with ``datetime.fromisoformat``.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(finished_at) AS last FROM runs "
                "WHERE flow=? AND start_key=? AND status IN (?,?,?) "
                "AND finished_at IS NOT NULL",
                (
                    flow,
                    start_key,
                    RunStatus.succeeded.value,
                    RunStatus.failed.value,
                    RunStatus.cancelled.value,
                ),
            ).fetchone()
        if row is None or row["last"] is None:
            return None
        return str(row["last"])

    def add_step_runs(self, step_runs: Sequence[StepRun]) -> None:
        """Insert step rows, ignoring ones already present."""
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO step_runs (run_id, step, item_index, status, "
                "key, after_json, attempt, started_at, finished_at, reason) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        item.run_id,
                        item.step,
                        item.item_index,
                        item.status.value,
                        item.key,
                        json.dumps(list(item.after)),
                        item.attempt,
                        item.started_at,
                        item.finished_at,
                        item.reason,
                    )
                    for item in step_runs
                ],
            )

    def step_runs(self, run_id: str) -> list[StepRun]:
        """One run's step rows, ordered by step then item index."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM step_runs WHERE run_id=? ORDER BY step ASC, item_index ASC",
                (run_id,),
            ).fetchall()
        return [_row_to_step_run(row) for row in rows]

    def get_step_run(self, run_id: str, step: str, item_index: int) -> StepRun | None:
        """One step row by key, or None when unknown."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM step_runs WHERE run_id=? AND step=? AND item_index=?",
                (run_id, step, item_index),
            ).fetchone()
        return _row_to_step_run(row) if row is not None else None

    def set_step_status(
        self,
        run_id: str,
        step: str,
        item_index: int,
        status: StepStatus,
        at: str,
        reason: str = "",
    ) -> bool:
        """Move one step row to *status*; False when the row is unknown.

        Entering ``running`` stamps ``started_at`` when still NULL; entering
        a ``FINISHED`` state stamps ``finished_at``.
        """
        with self._conn() as conn:
            if status is StepStatus.running:
                cur = conn.execute(
                    "UPDATE step_runs SET status=?, reason=?, "
                    "started_at=COALESCE(started_at, ?) "
                    "WHERE run_id=? AND step=? AND item_index=?",
                    (status.value, reason, at, run_id, step, item_index),
                )
            elif status in FINISHED:
                cur = conn.execute(
                    "UPDATE step_runs SET status=?, reason=?, finished_at=? "
                    "WHERE run_id=? AND step=? AND item_index=?",
                    (status.value, reason, at, run_id, step, item_index),
                )
            else:
                cur = conn.execute(
                    "UPDATE step_runs SET status=?, reason=? "
                    "WHERE run_id=? AND step=? AND item_index=?",
                    (status.value, reason, run_id, step, item_index),
                )
            return cur.rowcount > 0

    def bump_attempt(self, run_id: str, step: str, item_index: int) -> int:
        """Increment one step row's attempt counter, returning the new value."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE step_runs SET attempt=attempt+1 WHERE run_id=? AND step=? AND item_index=?",
                (run_id, step, item_index),
            )
            row = conn.execute(
                "SELECT attempt FROM step_runs WHERE run_id=? AND step=? AND item_index=?",
                (run_id, step, item_index),
            ).fetchone()
        return int(row["attempt"]) if row is not None else 0

    def ready_step_runs(self, limit: int = 100) -> list[StepRun]:
        """Ready step rows across runs, oldest run first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT s.* FROM step_runs s JOIN runs r ON r.id = s.run_id "
                "WHERE s.status=? "
                "ORDER BY r.started_at ASC, r.id ASC, s.step ASC, s.item_index ASC "
                "LIMIT ?",
                (StepStatus.ready.value, limit),
            ).fetchall()
        return [_row_to_step_run(row) for row in rows]

    def running_step_runs(self) -> list[StepRun]:
        """Running step rows across runs."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM step_runs WHERE status=? "
                "ORDER BY run_id ASC, step ASC, item_index ASC",
                (StepStatus.running.value,),
            ).fetchall()
        return [_row_to_step_run(row) for row in rows]
