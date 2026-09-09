# fleet overview

This page is for someone who has never seen fleet before. It explains the
main parts, walks through one task from start to finish, and lists every
way a task can go stale and what fleet does about it. For deeper detail,
see the links at the end.

## What fleet is

- **beads** is the task database: every unit of work is a "bead" (a row)
  stored in a local database, managed by the `bd` command-line tool.
- **The supervisor** is the long-running Python process started by
  `fleet run`. It claims ready beads, spawns workers to do them, and
  reaps the result when a worker finishes.
- **A worker** is one attempt at one task: one subprocess run, from spawn
  to exit, that either finishes the task or reports how far it got.
- **A coder** is the command-line tool that actually talks to the model —
  `claude`, `opencode`, or `codex`. The worker launches a coder as a
  subprocess and reads its output.
- **The web UI** (`fleet serve`, at `http://localhost:7890`) is a
  dashboard for creating tasks, watching them run, reading logs, and
  answering questions from blocked tasks.

## Life of one task

```
claim -> spawn -> worker runs -> RESULT.json written -> reap -> (isolated: validate/merge)
```

1. **Claim** (the `Claim` service): the supervisor picks a ready bead, moves it from `open` to
   `in_progress`, and writes a lease (see the stale-task table below).
2. **Spawn**: the supervisor picks a coder and model, decides whether this
   is a fresh attempt or a continuation of a prior one, and — for tasks
   inside a git repo, unless isolation is turned off — creates an
   isolated git worktree so the task cannot collide with other work in
   the same repo (`orchestrator/spawn.py`, `orchestrator/worktree.py`).
3. **Worker steps**: the worker prepares its prompt (optionally compacting
   a long history first), then `workers/llm_session.py` runs the coder as
   a subprocess and streams its events (tool calls, tokens used, errors)
   while refreshing a heartbeat lease.
4. **RESULT.json**: before exiting, the worker writes
   `artifacts/RESULT.json` with a status of `done`, `partial`, or
   `blocked`.
5. **Reap** (the `Reap` service): once the subprocess exits, the supervisor's reap step reads
   the exit code and `RESULT.json` and decides the outcome: close the
   bead, re-queue it, block it, or (for a shutdown) release it for a free
   retry.
6. **Validate (isolated tasks only)**: if the task ran in its own
   worktree and finished successfully with committed changes, a
   validation step merges the branch back into the base repository and
   runs any configured post-merge check before the bead closes.

Everything for one task lives under `~/.fleet/tasks/<id>/`. A reader
poking around will find: `task.json` (title, status, lease info),
`attempts.jsonl` (one line per attempt, start and end), an `attempts/<n>/`
folder per attempt holding that attempt's raw logs and a snapshot of its
result, and `artifacts/` holding the worker's own working files
(`PLAN.md`, `HANDOFF.md`, `KNOWLEDGE.md`, `RESULT.json`, `outputs/`). The
full field-by-field layout is in `docs/ARCHITECTURE.md`, section
"Task directory contract".

## What "stale" means and what fleet does about it

Every number below is a default from `src/fleet/core/config.py` (a
`fleet.toml` file can override it) or a fixed constant in
`src/fleet/core/limits.py` / `src/fleet/core/retry_policy.py`.

| Situation | How fleet notices | What happens | Config key (default) |
|---|---|---|---|
| Coder subprocess is running but silent for a long time | The `StallWatch` service (`orchestrator/stall.py`) compares "now" to the last write in the attempt's `events.jsonl` | Past the warning threshold the task is logged as stalled; if the configured action is `kill`, the supervisor kills the coder subprocess | `stall_warning_minutes` (15), `stall_action` (kill) |
| Attempt runs longer than allowed | `workers/llm_session.py` tracks elapsed time against a budget | The coder subprocess is sent SIGTERM (then SIGKILL if needed) and the attempt ends with outcome `KILLED`, reason `timeout` | `max_attempt_minutes` (120) |
| Repeated stalls/timeouts on the same task | `core/retry_policy.py` counts consecutive `KILLED` outcomes with reason `stalled`/`timeout` as a "stall" streak | Each one is released for a fresh retry; once the streak reaches `STALL_MAX_ROUNDS` (a fixed constant, currently 2) the bead is blocked for human review | `stall_warning_minutes` (15) governs detection; the block threshold is the code constant `STALL_MAX_ROUNDS`, not the (currently unused) `stall_block_after` (2) key |
| Worker's context window fills up | `workers/llm_session.py` tracks token usage against the coder's context limit | Past the checkpoint percentage a checkpoint marker is written so the next attempt compacts; past the kill percentage the subprocess is killed with outcome `CONTEXT_PRESSURE`, and the next attempt resumes with compaction | `context_checkpoint_pct` (75), `context_kill_pct` (90) |
| Model API rate-limits the coder | The coder reports a `rate_limit` event, or a health probe (`coder.probe_health`) detects silence consistent with a provider error during a quiet period | The subprocess is stopped with outcome `RATE_LIMIT`; the attempt is released (not counted against any retry limit) and retried after a wait | outcome is `rate_limit`; probe timing uses `core/limits.py` `PROBE_SILENCE_SEC` (60) and `RATE_LIMIT_PROBE_SILENCE_SEC` (300) |
| The supervisor itself restarts or dies mid-attempt | Each attempt refreshes `heartbeat_at`/`lease_until` in `attempts/<n>/run.json`; on startup, and periodically, the `LeaseReconcile` service (`orchestrator/leases.py`) finds beads whose lease expired with no live process | The bead is released back to `open` for a fresh claim; this never counts as a failed round, so a restart cannot push a task into being blocked | lease cadence: `core/limits.py` `HEARTBEAT_SEC` (30), `LEASE_RECONCILE_INTERVAL_SEC` (60); outcome reason `supervisor_shutdown` |
| Worker exits with no `RESULT.json`, or exits with status `blocked` | Reap reads `artifacts/RESULT.json` after the process exits; a missing file with exit code 0 is treated as `SUCCESS` with no close reason ("noclose"); a file with `status: blocked` becomes outcome `BLOCKED_BY_CODER` | No `RESULT.json`: released for retry, blocked after repeated occurrences. `status: blocked`: the bead is blocked immediately with the worker's `blocked_reason` | no-close block threshold is the code constant `NOCLOSE_MAX_ROUNDS` (3) |
| Retries are exhausted | `core/retry_policy.py` counts consecutive same-outcome attempts (failure, partial, context-pressure, stall, noclose) from `attempts.jsonl` | Once a streak reaches its limit the bead is set to `blocked` with a reason explaining which limit was hit | failure limit is the code constant `FAILURE_MAX_ROUNDS` (3); partial limit `PARTIAL_MAX_ROUNDS` (5); context limit `CONTEXT_MAX_ROUNDS` (3) |
| A blocked bead is left alone | The `Triage` service (`orchestrator/triage.py`) — its own periodic service, not part of any other loop — runs on a schedule and asks one non-blocking question per blocked bead with a proposed fix | An operator answers via the UI or the `ask_human` integration; fleet applies the answer (retry, retry with a bigger model, close, or ignore for a while) on the next tick | `triage_interval_minutes` (15; 0 disables) |

A human can also unblock a task directly at any time: from the task page
in the UI, or `POST /api/tasks/<id>/unblock`.

## How to look at a running or stuck task

- Open the task's page in the web UI (`fleet serve`) to see live status,
  logs, and any pending question.
- `fleet show <id>` prints the bead's current status and metadata.
- `fleet task <id> log` prints the latest attempt's log; `plan`,
  `handoff`, `knowledge`, and `result` print the matching artifact
  instead of the log.
- Raw per-attempt logs live under `~/.fleet/tasks/<id>/attempts/<n>/`
  (`events.jsonl`, `log.jsonl`, `log.stderr`, `run.json`).
- `attempts.jsonl` at the task root has one line per attempt (start and
  end), so it shows the whole retry history at a glance.
- A blocked task can be unblocked from its UI page, or with
  `POST /api/tasks/<id>/unblock`, which releases it for another attempt.

## Where to read more

- `docs/ARCHITECTURE.md` — code layout and the full task directory
  contract.
- `docs/WORKER_CONTRACT.md` — the `RESULT.json` schema and launch modes
  (fresh vs. continue vs. compact) in detail.
- `docs/adr/` — the architecture decision records explaining why things
  are built this way.
