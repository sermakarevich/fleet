"""SQLite store for saved workflows, their runs, and step runs.

The single owner of `$FLEET_HOME/workflows.db`: every reader and writer
goes through ``WorkflowStore`` (later the run engine, the serve API, and
the CLI). Schema changes are ordered ``MIGRATIONS`` applied under
``PRAGMA user_version``; each thread holds exactly one connection, and
WAL mode plus ``busy_timeout`` let readers and writers coexist.
"""

from __future__ import annotations

import builtins
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fleet.core.errors import WorkflowNameTaken
from fleet.state.paths import fleet_home, workflows_db_path
from fleet.workflows.model import (
    RunStatus,
    StepRun,
    Trigger,
    Workflow,
    WorkflowRun,
)

_SCHEMA_BASE = """
CREATE TABLE IF NOT EXISTS workflows (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    spec_json   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_runs (
    id          TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    n           INTEGER NOT NULL,
    trigger     TEXT NOT NULL,
    schedule_id TEXT,
    spec_json   TEXT NOT NULL,
    status      TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    started_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS workflow_run_steps (
    run_id      TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    step_name   TEXT NOT NULL,
    stage_index INTEGER NOT NULL,
    task_id     TEXT NOT NULL,
    task_status TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, step_name)
);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow
    ON workflow_runs(workflow_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_schedule
    ON workflow_runs(schedule_id);
CREATE INDEX IF NOT EXISTS idx_workflow_run_steps_run
    ON workflow_run_steps(run_id);
"""

# Ordered schema steps after the base tables above, applied under
# PRAGMA user_version. Each statement adds exactly one column; the column
# name is parsed back out (see _migration_column) so a half-applied schema
# (version stamp ahead of its columns) is detected and repaired.
MIGRATIONS: list[str] = [
    "ALTER TABLE workflow_runs ADD COLUMN inputs_json TEXT NOT NULL DEFAULT '{}'",
]

#: Schema level of a fully migrated database: the number of MIGRATIONS.
SCHEMA_VERSION = len(MIGRATIONS)


def _migration_column(statement: str) -> str:
    """Column name added by an ``ALTER TABLE ... ADD COLUMN <name> ...`` step."""
    parts = statement.split()
    return parts[parts.index("COLUMN") + 1]


def _user_version(conn: sqlite3.Connection) -> int:
    """Schema level stamped on the database (0 when never migrated)."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    """Live column names of one table."""
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn: sqlite3.Connection, statement: str, table: str, column: str) -> None:
    """Run one ALTER TABLE step, tolerating a concurrent migrator winning the race."""
    try:
        conn.execute(statement)
    except sqlite3.OperationalError:
        if column not in _column_names(conn, table):
            raise


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Bring the on-disk schema to SCHEMA_VERSION, in MIGRATIONS order.

    Fresh databases get the base tables plus every step; old ones get the
    missing steps; a database stamped ahead of its columns gets the steps
    it is actually missing. The version stamp is written last.
    """
    conn.executescript(_SCHEMA_BASE)
    columns = _column_names(conn, "workflow_runs")
    for statement in MIGRATIONS:
        column = _migration_column(statement)
        if column in columns:
            continue
        _add_column(conn, statement, "workflow_runs", column)
        columns.add(column)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def _row_to_workflow(row: sqlite3.Row) -> Workflow:
    """Decode one workflows row (the spec_json column holds the definition)."""
    return Workflow.from_dict(json.loads(str(row["spec_json"])))


def _row_to_run(row: sqlite3.Row) -> WorkflowRun:
    """Decode one workflow_runs row (spec_json holds the frozen definition)."""
    data: dict[str, Any] = dict(row)
    data["spec"] = json.loads(str(data["spec_json"]))
    data["inputs"] = _decode_inputs(data.get("inputs_json"))
    return WorkflowRun.from_dict(data)


def _decode_inputs(raw: Any) -> dict[str, str]:
    """Decoded inputs map; corrupt or missing JSON means no inputs."""
    if not raw:
        return {}
    try:
        decoded = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {str(key): str(value) for key, value in decoded.items()}


def _row_to_step_run(row: sqlite3.Row) -> StepRun:
    """Decode one workflow_run_steps row."""
    return StepRun(
        run_id=str(row["run_id"]),
        step_name=str(row["step_name"]),
        stage_index=int(row["stage_index"]),
        task_id=str(row["task_id"]),
        task_status=str(row["task_status"]),
        updated_at=str(row["updated_at"]),
    )


class WorkflowStore:
    """Thread-safe workflows database backed by a single SQLite file.

    Each thread holds exactly one connection (opened on first use, PRAGMAs
    set once), so instances are safe to share across threads; separate
    processes still get their own connections and coordinate through WAL.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Point the store at a database file (default: under FLEET_HOME)."""
        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            self.db_path = workflows_db_path(fleet_home())
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

    # -- workflows ----------------------------------------------------------

    def save(self, workflow: Workflow) -> None:
        """Insert or replace a workflow by id; duplicate names raise."""
        with self._conn() as conn:
            clash = conn.execute(
                "SELECT id FROM workflows WHERE name=?", (workflow.name,)
            ).fetchone()
            if clash is not None and str(clash["id"]) != workflow.id:
                raise WorkflowNameTaken(workflow.name)
            conn.execute(
                "INSERT OR REPLACE INTO workflows "
                "(id, name, description, spec_json, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    workflow.id,
                    workflow.name,
                    workflow.description,
                    json.dumps(workflow.to_dict()),
                    workflow.created_at,
                    workflow.updated_at,
                ),
            )

    def get(self, workflow_id: str) -> Workflow | None:
        """One workflow by id, or None when unknown."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        return _row_to_workflow(row) if row is not None else None

    def get_by_name(self, name: str) -> Workflow | None:
        """One workflow by its unique name, or None when unknown."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE name=?", (name,)).fetchone()
        return _row_to_workflow(row) if row is not None else None

    def list(self) -> builtins.list[Workflow]:
        """All workflows, ordered by name."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM workflows ORDER BY name ASC").fetchall()
        return [_row_to_workflow(row) for row in rows]

    def delete(self, workflow_id: str) -> bool:
        """Remove a workflow with its runs and step runs; False when missing."""
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM workflow_run_steps WHERE run_id IN "
                "(SELECT id FROM workflow_runs WHERE workflow_id=?)",
                (workflow_id,),
            )
            conn.execute("DELETE FROM workflow_runs WHERE workflow_id=?", (workflow_id,))
            cur = conn.execute("DELETE FROM workflows WHERE id=?", (workflow_id,))
            return cur.rowcount > 0

    # -- runs ---------------------------------------------------------------

    def save_run(self, run: WorkflowRun) -> None:
        """Insert or replace one run by id (the spec is frozen at start)."""
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO workflow_runs (id, workflow_id, n, trigger, "
                "schedule_id, spec_json, status, reason, started_at, finished_at, "
                "inputs_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run.id,
                    run.workflow_id,
                    run.n,
                    run.trigger.value,
                    run.schedule_id,
                    json.dumps(run.spec.to_dict()),
                    run.status.value,
                    run.reason,
                    run.started_at,
                    run.finished_at,
                    json.dumps(run.inputs),
                ),
            )

    def get_run(self, run_id: str) -> WorkflowRun | None:
        """One run by id, or None when unknown."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
        return _row_to_run(row) if row is not None else None

    def list_runs(
        self,
        workflow_id: str | None = None,
        schedule_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[WorkflowRun]:
        """Runs newest first, optionally filtered, with limit/offset paging."""
        clauses: list[str] = []
        args: list[Any] = []
        if workflow_id is not None:
            clauses.append("workflow_id=?")
            args.append(workflow_id)
        if schedule_id is not None:
            clauses.append("schedule_id=?")
            args.append(schedule_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_runs "
                f"{where} ORDER BY started_at DESC, n DESC, id DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return [_row_to_run(row) for row in rows]

    def last_run(self, workflow_id: str, trigger: Trigger | None = None) -> WorkflowRun | None:
        """Newest run of a workflow, optionally only of one trigger kind."""
        clause = "AND trigger=?" if trigger is not None else ""
        args: list[Any] = [workflow_id] + ([trigger.value] if trigger is not None else [])
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE workflow_id=? "
                f"{clause} ORDER BY started_at DESC, n DESC, id DESC LIMIT 1",
                args,
            ).fetchone()
        return _row_to_run(row) if row is not None else None

    def run_count(self, workflow_id: str) -> int:
        """Number of runs stored for a workflow."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM workflow_runs WHERE workflow_id=?", (workflow_id,)
            ).fetchone()
        return int(row[0]) if row else 0

    def finish_run(self, run_id: str, status: RunStatus, reason: str, finished_at: str) -> bool:
        """Close a run with its final status; False when the run is unknown."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE workflow_runs SET status=?, reason=?, finished_at=? WHERE id=?",
                (status.value, reason, finished_at, run_id),
            )
            return cur.rowcount > 0

    # -- step runs ----------------------------------------------------------

    def save_step_runs(self, steps: builtins.list[StepRun]) -> None:
        """Insert or replace one run's step rows, keyed by (run_id, step_name)."""
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO workflow_run_steps "
                "(run_id, step_name, stage_index, task_id, task_status, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                [
                    (
                        item.run_id,
                        item.step_name,
                        item.stage_index,
                        item.task_id,
                        item.task_status,
                        item.updated_at,
                    )
                    for item in steps
                ],
            )

    def step_runs(self, run_id: str) -> builtins.list[StepRun]:
        """One run's step rows, in stage then name order."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_run_steps WHERE run_id=? "
                "ORDER BY stage_index ASC, step_name ASC",
                (run_id,),
            ).fetchall()
        return [_row_to_step_run(row) for row in rows]

    def update_step_status(
        self, run_id: str, step_name: str, task_status: str, updated_at: str
    ) -> bool:
        """Refresh one step's task status; False when the step row is unknown."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE workflow_run_steps SET task_status=?, updated_at=? "
                "WHERE run_id=? AND step_name=?",
                (task_status, updated_at, run_id, step_name),
            )
            return cur.rowcount > 0
