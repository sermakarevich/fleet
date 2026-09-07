# ADR 0001: Fleet's Own SQLite Store Becomes Authoritative; Beads Becomes an Adapter

## Status

Proposed

## Date

2026-09-07

## Context

Fleet keeps task state in four places at once, and nothing reconciles them.

First, the beads issue tracker holds status, assignee, and priority.
`src/fleet/queue.py` shells out to the `bd` command for every operation
(`_bd` runs `subprocess.run`, see `src/fleet/queue.py`), so each claim,
release, block, close, and comment is a separate child process with no
shared transaction.

Second, `task.json` in each task directory holds a copy of the same facts
plus fleet-only fields (`cwd`, `coder`, `model`). `src/fleet/queue.py`
reads it with `_load_meta` and writes it with `_write_meta`, and merges
beads data with file data in `_snapshot_meta` and `_task_from_dict`.

Third, a set of dot-files in each task directory holds counters and flags:
`.failures`, `.noclose`, and stall counters managed by
`src/fleet/failures.py`; the `.needs_validation` marker set in
`src/fleet/supervisor.py` after a clean worktree commit; the `.kill`
sentinel created and polled in `src/fleet/supervisor.py`; the `.worktree`
marker that records the isolated worktree path in
`src/fleet/supervisor.py`.

Fourth, live state exists only in memory: the `Supervisor.in_flight` dict,
the `_runners` dict, and per-task `run.json` files (pid, start time) that
`src/fleet/runner.py` writes at spawn and `src/fleet/supervisor.py` reads
back during orphan reconciliation.

Fifth, history lives in append-only flat files: `events.jsonl` written by
`append_event` in `src/fleet/logging.py`, plus `log.jsonl` and `log.stderr`
opened by `open_task_log` in `src/fleet/logging.py`.

This split causes real failures documented in `docs/PRODUCT_PLAN.md`:
claim is two separate writes (`bd update --claim` then `task.json`, see
`src/fleet/queue.py`), so a crash leaves beads and `task.json` disagreeing;
`_bead_in_progress` in `src/fleet/supervisor.py` swallows all errors; stall
detection in `src/fleet/supervisor.py` only warns; completion is inferred
from exit code 0 in `src/fleet/runner.py` instead of being signaled.

This record is an ADR (Architecture Decision Record): a short dated note
that captures one important decision, why it was made, and what follows.

## Decision

Fleet will own a single SQLite database, and that database will be the one
source of truth for task state. Beads becomes an optional adapter that
mirrors state outward and imports new issues inward. It is no longer read
in the hot path.

Concretely: introduce a `LocalQueue` over SQLite with a transactional
claim (one transaction, not two writes). Keep `BeadsQueue` in
`src/fleet/queue.py` only as a sync adapter. Replace every dot-file with a
column or a row (see Migration outline). Replace the 160-line outcome match
block in `src/fleet/supervisor.py` with an explicit state machine whose
every transition appends one `run_events` row, so a restart can replay
history. Use WAL (Write-Ahead Logging: SQLite writes changes to a separate
log file first, so readers never block writers) mode from day one, and
access the database through SQLAlchemy with Alembic migrations, so moving
to Postgres later is a configuration change, not a rewrite.

## Consequences

### Positive

- One atomic claim: no more beads-versus-`task.json` disagreement after a
  crash, because the claim in `src/fleet/queue.py` becomes one transaction.
- Restart safety: the supervisor can be killed mid-run and reconcile every
  task from the store plus persisted PIDs, instead of the partial sweep in
  `src/fleet/supervisor.py` that only handles worktrees and `run.json`.
- No subprocess per queue call: logic becomes unit-testable without `bd`,
  unlike today's `subprocess.run` calls in `src/fleet/queue.py`.
- Bounded disk: retention and archiving apply to tables, replacing the
  unbounded `events.jsonl` growth noted against `src/fleet/logging.py`.

### Negative

- Migration work: the one-shot import of ~2,500 task directories plus the
  beads export must be written, tested, and run once.
- Two-way sync complexity: while the adapter lives, mapping conflicts
  (edited on both sides) need a documented rule.
- SQLite write ceiling: a single writer fits one node well, but very high
  concurrency will eventually need Postgres.

### Neutral

- The CLI and UI keep working through the change; views switch from
  re-reading directories to reading the database.
- Agents stop running `fleet bd close`; they emit a structured result that
  the state machine consumes (Phase 2 work, outcome handling stays in
  `src/fleet/supervisor.py` until then).

## Alternatives considered

1. Keep beads as the store. Rejected: it keeps the subprocess-per-call
   cost in `src/fleet/queue.py`, the non-atomic claim, the second copy of
   state in `task.json`, and the 1.5 GB Dolt database called out in
   `docs/PRODUCT_PLAN.md`. Nothing about crash recovery improves.
2. Postgres from day one. Rejected: it adds operations burden (server,
   backups, credentials) for single-node installs that SQLite serves with
   zero setup. SQLAlchemy plus migrations keeps the Postgres door open
   without paying the price now.
3. Flat files with locking. Rejected: file locks do not compose across the
   claim, counter increments in `src/fleet/failures.py`, event appends in
   `src/fleet/logging.py`, and outcome handling in
   `src/fleet/supervisor.py`. We would rebuild a weak database by hand.

## Migration outline

New tables: `tasks`, `runs`, `run_events`, `schedules`, `questions`,
`audit_log`. (`schedules` and `questions` start mostly empty; runs and
events carry the history.)

Field-by-field mapping from today's files to the new store:

- `task.json` `id`, `title`, `description`, `status` (built in
  `src/fleet/queue.py` by `_snapshot_meta`) become `tasks.id`,
  `tasks.title`, `tasks.description`, `tasks.status`.
- `task.json` `priority`, `depends_on` (same builder in
  `src/fleet/queue.py`) become `tasks.priority` and a dependency edge
  table (or `tasks.depends_on` JSON column for the first cut), which lets
  fleet compute the ready set over its own DAG (directed acyclic graph: a
  set of tasks linked by depends-on arrows with no cycles) instead of
  delegating to `bd ready`.
- `task.json` `cwd`, `coder`, `model` (written by `set_cwd`,
  `set_overrides`, and `freeze_coder_model` in `src/fleet/queue.py` at
  spawn time in `src/fleet/supervisor.py`) become `tasks.cwd`,
  `tasks.coder`, `tasks.model`, frozen at first run.
- `.failures` counter (incremented in `src/fleet/failures.py`, consumed by
  the FAILURE branch in `src/fleet/supervisor.py`) becomes
  `tasks.failure_count` (integer column).
- `.noclose` counter (incremented in `src/fleet/failures.py` when exit 0
  arrives with the bead still open, see `src/fleet/supervisor.py`) becomes
  `tasks.noclose_count` (integer column).
- Stall kills (incremented in `src/fleet/failures.py`, handled in the
  KILLED branch of `src/fleet/supervisor.py`) become
  `tasks.stall_count` (integer column).
- `.needs_validation` marker (set after a clean isolated commit and
  consumed one-per-tick in `src/fleet/supervisor.py`) becomes
  `tasks.needs_validation` (boolean column).
- `.kill` sentinel (deleted at spawn and polled in the kill loop in
  `src/fleet/supervisor.py`, acted on by `kill`/`cancel` in
  `src/fleet/runner.py`) becomes `runs.kill_requested` (boolean column on
  the live run row), checked by the worker pool loop.
- `.worktree` marker (path written at spawn in `src/fleet/supervisor.py`)
  becomes `runs.worktree_path` (nullable text column on the run row).
- `run.json` (`pid`, `pgid`, start/end times written in
  `src/fleet/runner.py`) becomes the `runs` row itself: `runs.pid`,
  `runs.pgid`, `runs.started_at`, `runs.ended_at`, `runs.exit_code`,
  `runs.outcome`, `runs.coder`.
- `.context_pressure` flag (checked in `src/fleet/runner.py` to classify
  CONTEXT_PRESSURE) becomes `runs.outcome = 'context_pressure'` plus a
  `run_events` row with the reason.
- `events.jsonl` (one normalized event per line appended by
  `src/fleet/logging.py`) becomes `run_events` rows (`run_id`, `kind`,
  `ts`, `tool_name`, `usage`, `rate_info`, `raw`), append-only, replayable
  on restart.
- `log.jsonl` / `log.stderr` stay as files for now (cheap, large); the
  store keeps their paths, and retention archives them by age.

One-shot migration tool: import each task directory plus the beads export,
create one `tasks` row and one `runs` row per historical attempt where
recoverable, bulk-load `events.jsonl` into `run_events`, then apply a
retention policy (archive closed runs older than N days, compress old
event payloads).

## Open questions

1. Do we keep two-way beads sync in Phase 1, or import-only with export
   added later?
2. Where does the SQLite file live, and what is the backup story for it?
3. How long do we keep `run_events` rows before archiving, and where do
   archived payloads go?
4. Should tenants, projects, and employees get real tables now, or stay
   single-row placeholders until Phase 4 and Phase 6?
5. What is the exact conflict rule when a task is edited in beads and in
   fleet between syncs?
6. What retention applies to `log.jsonl` and `log.stderr` once runs are in
   the store?
