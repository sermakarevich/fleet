"""Behavioural constants: cadences, timeouts, retry bounds, API caps.

One home for every number nobody should tune blind (ADR 0006 rule 1).
``TUNABLE_DOCS`` gives each constant its one-line doc; ``render_tunables_table``
turns the table into the Tunables section of ``docs/CONFIG.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

LOG_ROOT = "logging"

# Daemon log rotation (see observability/daemon.py, state/journal.py): a
# daemon log (serve.daemon.log, supervisor.daemon.log, fleet-<date>.jsonl)
# is rotated when it reaches LOG_ROTATE_BYTES, keeping LOG_ROTATE_KEEP
# numbered backups (<name>.1 … <name>.N, oldest dropped). Daemon logs used
# to grow forever; 20 MiB x5 bounds a runaway log at ~120 MiB per file.
LOG_ROTATE_BYTES: int = 20 * 1024 * 1024
LOG_ROTATE_KEEP: int = 5

CONFIG_POLL_INTERVAL_SEC: int = 5
CLAIM_POLL_INTERVAL_SEC: int = 5
# Scheduler tick: cron resolution is one minute; 30 s keeps the worst-case delay under a minute.
SCHEDULER_TICK_SEC: int = 30
# Workflow refresh: fold bead statuses into open workflow runs so history
# stays correct even when nobody opens the UI (see ADR 0008).
WORKFLOW_REFRESH_SEC: int = 60
SHUTDOWN_GRACE_SEC: int = 30
RATE_LIMIT_DEFAULT_SLEEP_SEC: int = 300
STATUS_LOG_INTERVAL_SEC: int = 30
# Lease heartbeat: while a worker attempt runs, workers/llm_session.py
# rewrites run.json every HEARTBEAT_SEC with heartbeat_at/lease_until
# (lease_until = now + 3 * HEARTBEAT_SEC). A lease counts as stale only
# when it has been past for more than one full HEARTBEAT_SEC, so a single
# slow event-loop tick can never trigger a reclaim.
HEARTBEAT_SEC: int = 30
LEASE_RECONCILE_INTERVAL_SEC: int = 60
# Retention (gc) pass: archive closed tasks, purge old archives, drop
# stale worktrees. Runs once at supervisor startup, then on this cadence.
GC_INTERVAL_SEC: int = 86400
PROBE_INTERVAL_SEC: int = 30
PROBE_SILENCE_SEC: int = 60
# opencode retries provider rate limits itself with growing back-off; streaks
# almost always clear within ~90 s. Only give up on a rate-limited session after
# this much silence, otherwise the probe kills sessions that were about to recover.
# Retry-table rounds (consumed by core/retry_policy.py and core/triage_policy.py).
# "Max rounds" counts the current attempt too: round n means this outcome
# has ended n times in a row (trailing streak in history + 1).
FAILURE_MAX_ROUNDS: int = 3
STALL_MAX_ROUNDS: int = 2
CONTEXT_MAX_ROUNDS: int = 3
PARTIAL_MAX_ROUNDS: int = 5
NOCLOSE_MAX_ROUNDS: int = 3

RATE_LIMIT_PROBE_SILENCE_SEC: int = 300
# Subprocess ceiling for every `bd` CLI call (see beads/client.py::BdClient).
# A hung `bd` must fail fast as BdError, never hang the supervisor.
BD_TIMEOUT_SEC: int = 60
# Subprocess ceiling for every `git` call (see orchestrator/git.py::GitRepo).
# One place owns the timeout so no git invocation can hang a service loop.
GIT_TIMEOUT_SEC: int = 120
# Default ceiling for every other `subprocess.run` call (CLI helpers such as
# `just ui-build`, `claude mcp ...`, the `bd` passthrough). A hung child
# fails fast as a typed error, never hangs the caller forever.
SUBPROCESS_TIMEOUT_SEC: int = 60
# Serve query bounds (see serve/api/*): out-of-range values are rejected with
# 422 instead of being silently clamped, so callers learn the real limits.
# Whole-task event pages cap at 500 rows per request.
MAX_EVENT_PAGE: int = 500
# GET /api/tasks closed-task window: default 300 rows, at most 2000.
CLOSED_TASKS_DEFAULT: int = 300
CLOSED_TASKS_MAX: int = 2000
# GET /api/search result cap: default 20 hits, at most 100 per request.
SEARCH_LIMIT_DEFAULT: int = 20
SEARCH_LIMIT_MAX: int = 100
# GET /api/analytics/summary trailing window: default 7 days, at most 365.
ANALYTICS_DAYS_DEFAULT: int = 7
ANALYTICS_DAYS_MAX: int = 365
# Serve event-stream watcher: how often the task dirs are re-scanned
# (see serve/event_stream.py::FileWatcher).
SERVE_WATCH_INTERVAL_SEC: float = 0.2
# Serve question poller: idle tick between Telegram notify rounds, and the
# backoff ceiling after repeated Telegram failures (see serve/app.py).
QUESTION_POLL_SEC: float = 2.0
QUESTION_BACKOFF_MAX_SEC: float = 60.0
# Serve event-stream watcher: replay window for in-progress tasks on serve
# restart (see serve/event_stream.py::FileWatcher).
WS_REPLAY_LINES: int = 50


@dataclass(frozen=True, slots=True)
class TunableRow:
    """One behavioural constant: name, value, one-line doc."""

    name: str
    value: str
    doc: str


# One-line doc per constant above; docs/CONFIG.md renders this table.
# A test asserts every public UPPER_SNAKE constant in this module appears here.
TUNABLE_DOCS: dict[str, str] = {
    "LOG_ROOT": "Subdirectory of FLEET_HOME holding daemon logs.",
    "LOG_ROTATE_BYTES": "Rotate a daemon log once it reaches this size.",
    "LOG_ROTATE_KEEP": "Numbered backups kept per rotated daemon log.",
    "CONFIG_POLL_INTERVAL_SEC": "How often the supervisor re-reads runtime.toml.",
    "CLAIM_POLL_INTERVAL_SEC": "How often the claim service polls the queue.",
    "SCHEDULER_TICK_SEC": "Scheduler tick; cron resolution is one minute.",
    "WORKFLOW_REFRESH_SEC": "How often open workflow runs fold in bead statuses.",
    "SHUTDOWN_GRACE_SEC": "SIGTERM grace before shutdown escalates to SIGKILL.",
    "RATE_LIMIT_DEFAULT_SLEEP_SEC": "Wait before retrying a rate-limited attempt.",
    "STATUS_LOG_INTERVAL_SEC": "Heartbeat lines between supervisor status logs.",
    "HEARTBEAT_SEC": "Attempt lease heartbeat rewrite cadence.",
    "LEASE_RECONCILE_INTERVAL_SEC": "How often stale attempt leases are reclaimed.",
    "GC_INTERVAL_SEC": "Retention pass cadence after the startup pass.",
    "PROBE_INTERVAL_SEC": "Health-probe tick for running coder sessions.",
    "PROBE_SILENCE_SEC": "Silence that marks a session as possibly stuck.",
    "FAILURE_MAX_ROUNDS": "Consecutive failures before a task blocks.",
    "STALL_MAX_ROUNDS": "Consecutive stall kills before a task blocks.",
    "CONTEXT_MAX_ROUNDS": "Consecutive context-pressure ends before a task blocks.",
    "PARTIAL_MAX_ROUNDS": "Consecutive partial outcomes before a task blocks.",
    "NOCLOSE_MAX_ROUNDS": "Consecutive no-close exits before a task blocks.",
    "RATE_LIMIT_PROBE_SILENCE_SEC": "Silence giving up on a rate-limited session.",
    "BD_TIMEOUT_SEC": "Subprocess ceiling for every bd CLI call.",
    "GIT_TIMEOUT_SEC": "Subprocess ceiling for every git call.",
    "SUBPROCESS_TIMEOUT_SEC": "Default ceiling for other subprocess.run calls.",
    "MAX_EVENT_PAGE": "Row cap per whole-task event page request.",
    "CLOSED_TASKS_DEFAULT": "Default rows for the closed-tasks window.",
    "CLOSED_TASKS_MAX": "Max rows for the closed-tasks window.",
    "SEARCH_LIMIT_DEFAULT": "Default hits per search request.",
    "SEARCH_LIMIT_MAX": "Max hits per search request.",
    "ANALYTICS_DAYS_DEFAULT": "Default trailing window in days for analytics.",
    "ANALYTICS_DAYS_MAX": "Max trailing window in days for analytics.",
    "SERVE_WATCH_INTERVAL_SEC": "Task-dir rescan cadence of the event watcher.",
    "QUESTION_POLL_SEC": "Idle tick between Telegram notify rounds.",
    "QUESTION_BACKOFF_MAX_SEC": "Backoff ceiling after Telegram failures.",
    "WS_REPLAY_LINES": "Replay window for in-progress tasks on serve restart.",
}


def tunable_rows() -> list[TunableRow]:
    """Every TUNABLE_DOCS entry as a doc row with its live value."""
    here = globals()
    return [
        TunableRow(name=name, value=repr(here[name]), doc=doc) for name, doc in TUNABLE_DOCS.items()
    ]


def render_tunables_table() -> str:
    """Tunable rows as a Markdown table (docs/CONFIG.md region)."""
    lines = ["| Name | Value | Description |", "|---|---|---|"]
    for row in tunable_rows():
        lines.append(f"| `{row.name}` | `{row.value}` | {row.doc} |")
    return "\n".join(lines) + "\n"
