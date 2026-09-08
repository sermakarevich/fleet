# fleet architecture

This document is the map of the code. Read it before editing.
It describes the **target** layout that the refactor beads move toward,
and how today's files map onto it. When the two disagree, this file wins
and the code is what still needs to move.

The layout follows one idea: **the tree is a wiki.** Every folder is one
concept. Every file inside it is one sub-concept. A reader (human or
agent) should be able to guess what a file contains from its path alone,
and find the single place where a concept is defined.

## Rules

1. **One concept, one home.** A fact about the system (where a task
   directory lives, how `bd` is called, how an outcome is handled) is
   defined in exactly one module. Everyone else imports it.
2. **Lower layers never import higher ones.** The order, low to high:
   `core` → `state` → `beads` → `workers` → `orchestrator` /
   `integrations` / `observability` → `serve` → `cli`.
   `coders` sits beside `workers` and is imported by it; `coders` never
   imports `workers`. See `docs/adr/0003-workers-as-step-pipelines.md` for
   why workers exist as a layer of their own.
   `serve` and `cli` are entry points. They hold no domain logic.
3. **Entry points are thin.** A route or a command parses input, calls a
   library function, formats output. If a helper in a route or command
   reads a file, runs a subprocess, or computes derived data, it belongs
   in a library module.
4. **Names say what is inside.** No stdlib shadowing (`logging.py`), no
   process-prefixed names (`supervisor_spawn.py`), no abbreviations
   (`BD.tsx`), no `core` / `utils` / `stats` catch-alls.
5. **Dead code is deleted, not kept for its tests.** A module nothing
   imports goes, along with its tests.
6. **Pure policy is a pure function.** Rules such as "what does fleet do
   after this outcome" take plain values and return a decision. I/O
   happens in the caller.

## Target layout (Python)

```
src/fleet/
  core/                  # domain types and constants. No I/O.
    task.py              # Task, Event, EventKind, TaskOutcome, TaskOutcomeRecord
    config.py            # RuntimeConfig dataclass, load/reload/write_atomic
    limits.py            # poll intervals, grace periods (retry limits live in core/retry_policy.py)
    retry_policy.py    # decide(record, history, status) -> Decision. Pure.

  state/                 # everything that touches a task directory on disk
    paths.py             # fleet_home(), tasks_root(), task_dir(id), file-name constants
    task_dir.py          # TaskDir: task.json, run.json, marker files (.kill, .worktree, ...)
    events.py            # THE events.jsonl reader + derived stats (context, last event, files touched)
    attempts.py          # attempts.jsonl (start/end journal, restart_count)
    validation_marker.py # .needs_validation marker (retry rounds come from attempts.jsonl)
    journal.py           # append_event, open_task_log, rotation  (was logging.py)
    archive.py           # move finished task dirs aside            (was gc.py)

  beads/                 # the one client for the bd CLI
    client.py            # run(), list_all(), show(), update(), comment(); BeadsError; envelope unwrap
    queue.py             # Queue ABC + BeadsQueue (claim/release/block/close) on top of client
    reconcile.py         # the one rule for merging bd status with task.json
    cache.py             # TTL cache for list_all                   (was serve/beads_info.py)

  workers/               # step pipelines: what runs for a task, as composable steps
    __init__.py          # select_worker(task, ctx) -> Worker; family routing by bead type / metadata
    base.py              # Step protocol, StepContext, StepResult, Worker, WorkerRun, run_worker()
    llm_session.py       # LlmSession step: spawn the coder subprocess, stream stdout, classify exit
    task.py              # PrepareArtifacts step, FreshTask worker, plan_task(ctx)

  orchestrator/          # the supervisor process, split by concern
    supervisor.py        # wires the loops below; owns in_flight; signal handling
    claim.py             # claim loop + per-coder concurrency caps (absorbs concurrency.py)
    spawn.py             # resolve coder/model, select_worker, build WorkerRun, record attempt start
    reap.py              # collect finished runners, call outcome_policy, apply the action
    stall.py             # stall detection and kill
    orphans.py           # startup reconciliation of run.json vs live pids
    worktree.py          # git worktree create/merge/validate       (merges worktree.py + supervisor_worktree.py)
    rate_gauge.py

  coders/                # unchanged: base.py + one file per coder + hooks/
                         # coder-specific config (opencode_*) moves into the coder module

  integrations/
    telegram/            # bot.py (polling, commands), notify.py, setup.py (wizard logic)
    ask_human/           # server.py, store.py  (ask_human_db.py merged into store.py)
    web_fetch/
    ollama_tunnel.py

  observability/
    redact.py
    tailview.py          # render events for a terminal
    daemon.py            # pid files, start/stop, code fingerprint

  serve/
    app.py               # FastAPI app factory, router registration
    auth.py              # bearer-token middleware + websocket check
    state.py             # AppState: queue, connection_manager, caches (injected, not module globals)
    watcher.py
    api/                 # thin routers, one file per resource
      tasks.py  beads.py  supervisor.py  config.py  chat.py  search.py  analytics.py
    analytics/           # aggregation moved out of the route
      records.py         # per-task record from state.events
      summary.py         # the /summary aggregator

  cli/
    main.py              # typer app, registers groups
    tasks.py             # init, ready, show, tasks, task, kill, gc, tail, log
    beads.py             # `fleet bd` passthrough + create-argv rewriting (uses beads.client)
    daemons.py           # run / serve start|stop|restart|status
    config.py
    telegram.py          # prompts only; logic in integrations.telegram.setup
    ask_human.py
    format.py            # table formatters shared by the commands
```

## Target layout (UI)

```
src/fleet/ui/src/
  app/                   # App.tsx (routes only), NavBar.tsx, GlobalEvents.tsx, queryClient.ts
  shared/
    api.ts  types.ts     # single source of API types; must match serve/api
    hooks/               # useApi.ts (every endpoint has a hook), useWebSocket.ts, ...
    format.ts            # fmtTs, fmtDuration, fmtTokens  (one copy)
    status.ts            # status -> color/label         (one copy)
    ui/                  # StatusDot, Sparkline, Toast, small primitives
    styles/              # tokens.ts, global.css        (one styling approach)
  features/
    tasks/               # TasksPage.tsx, TaskRow.tsx, TaskCard.tsx, NewTaskPanel.tsx
    task-detail/         # TaskDetailPage.tsx, Header.tsx, tabs/*.tsx
    beads/               # BeadsPage.tsx (was BD.tsx), BeadRow.tsx, BeadDrawer.tsx
    chat/                # ChatPage.tsx + hooks/useChat.ts (React Query, shared toast)
    analytics/           # AnalyticsPage.tsx, charts/*, chartTheme.ts (was panel.ts), timeBuckets.ts
    config/
    command-palette/
```

## Where today's code goes

| Today | Target |
|---|---|
| `schemas.py` | `core/task.py` + `core/limits.py` |
| `config.py` | `core/config.py` |
| `supervisor.py::_apply_outcome` | `core/retry_policy.py` (pure) + `orchestrator/reap.py` (applies) |
| `serve/stats.py::fleet_home, task_dir` | `state/paths.py` |
| `serve/stats.py` scanners, `serve/analytics_core.py::_build_record`, `routes/analytics.py::_scan_events`, `routes/tasks.py::_extract_file_ops` | `state/events.py` |
| `failures.py` | `state/counters.py` |
| `logging.py` | `state/journal.py` |
| `gc.py` | `state/archive.py` |
| `queue.py::_bd`, `routes/beads.py::_run_bd`, `beads_info.py`, `routes/tasks.py` bd calls, `cli.py` bd calls | `beads/client.py` |
| `routes/tasks.py` and `routes/analytics.py` beads-status merge | `beads/reconcile.py` |
| `supervisor.py` (rest), `supervisor_spawn.py` (delete), `concurrency.py` | `orchestrator/*` |
| `runner.py` | `workers/llm_session.py` (LlmSession step), minus queue calls |
| `worktree.py` + `supervisor_worktree.py` | `orchestrator/worktree.py` |
| `telegram.py`, `cli.py` telegram wizard | `integrations/telegram/` |
| `ask_human_db.py` + `ask_human/store.py` | `integrations/ask_human/store.py` |
| `routes/analytics.py::_compute_*` | `serve/analytics/summary.py`; deprecated endpoints deleted |
| `cli.py` | `cli/*.py` |
| `ui/pages/Dashboard.tsx`, `RunningTable.tsx`, `NeedsYouPanel.tsx`, `RecentOutcomes.tsx` | deleted (not routed) |

## Task directory contract

`state/task_dir.py` is the only module allowed to know these names:

```
$FLEET_HOME/tasks/<id>/
   task.json          # id, title, description, status, cwd, coder, model, blocked_reason, blocked_at, retry_after
  attempts.jsonl     # start/end per worker attempt, append-only (task-level, unchanged)
  attempts/<n>/      # n = attempt number from state.attempts.record_start
    run.json         # pid, started_at, worker name, per-step status of this attempt
    events.jsonl      log.jsonl   log.stderr
    launch.json      # {"mode": "fresh|continue", "pack_bytes": n, "kind": "work"}, written at spawn
    RESULT.json       # snapshot of artifacts/RESULT.json at reap time (if present)
    HANDOFF.md        # snapshot of artifacts/HANDOFF.md at reap time
    SUMMARY.md        # deterministic, no-LLM summary generated after the attempt ends
  .needs_validation .kill .worktree .context_pressure
  artifacts/
    RESULT.json      # worker's declared outcome for the last attempt
    RESULT.prev.json # previous attempt's RESULT.json, rotated aside before each spawn
    PLAN.md          # restatement + plan; written once, updated rarely
    HANDOFF.md       # overwritten every attempt, hard cap 2 KB
    KNOWLEDGE.md     # curated durable facts, rewritten when stale (~4 KB cap)
    outputs/         # real deliverables (reports, data) referenced from RESULT.json
```

`run.json`, `events.jsonl`, `log.jsonl`, `log.stderr` moved from the task
root into each attempt's own folder so that per-attempt slicing (tailing,
stall detection, the attempts timeline) doesn't have to guess where one
attempt ends and the next begins. `state/paths.py::attempt_dir_path`,
`state/attempts.py::attempt_dir` / `latest_attempt_dir` are the only
places allowed to build these paths; everyone else (stall, orphans,
cli `--log`/`--stderr`, the websocket tail) calls those helpers instead
of hardcoding "the latest attempt". `state/events.py::iter_events`
still reads across every attempt, oldest first, so history spans the
whole task. `.kill`, `.worktree`, `.context_pressure` stay at the task
directory root (they gate the *next* spawn, not one attempt).
The RESULT.json schema and what fleet does with each `status` value are
documented once in `docs/WORKER_CONTRACT.md`; cite that file rather than
duplicating the contract elsewhere. Launch-mode planning (fresh vs.
continue) is documented in `docs/WORKER_CONTRACT.md`'s "Launch modes"
section.

## Testing layout

`tests/` mirrors `src/fleet/` folder for folder. A test for
`state/events.py` lives in `tests/state/test_events.py`. Integration
tests stay in `tests/integration/`.
