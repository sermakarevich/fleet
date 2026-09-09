# fleet architecture

This document is the map of the code. Read it before editing.
It describes the layout as it is: every section below is generated from
the real tree (`find src/fleet -name '*.py' | sort`). If code and docs
disagree, the code wins and this file needs an update.

The layout follows one idea: **the tree is a wiki.** Every folder is one
concept. Every file inside it is one sub-concept. A reader (human or
agent) should be able to guess what a file contains from its path alone,
and find the single place where a concept is defined.

## Rules (ADR 0006 — Accepted)

Four rules, applied to every package. A test enforces the ones a test
can enforce.

### Rule 1 — one owner per file, record and process fact

Every file under `~/.fleet` has exactly one module that writes it and one
typed reader. The owners live in `state/`:

| File / fact | Owner module | Type |
|---|---|---|
| `task.json` | `state/task_meta.py` | `TaskMeta` |
| `attempts.jsonl` | `state/attempt_journal.py` | `AttemptJournal` (read once, answer `max_n`, `current_n`, `rows`) |
| `attempts/<n>/run.json` | `state/run_file.py` | `RunRecord` |
| `STATE.md`, `RESULT.json` | `state/artifacts.py` | `StateFile`, `ResultFile` |
| walk of `tasks/*` | `state/task_index.py` | `TaskIndex` |
| runtime.toml I/O | `state/config_file.py` | `RuntimeConfig` stays pure in `core/config.py` |
| questions db | `integrations/ask_human/store.py::QuestionStore` only | injected, never a module global |
| pid files, `.pause`, code fingerprint | `observability/process.py` | `ServiceRegistry`, `service_status(name)` |

`beads/queue.py` only talks to `bd`. `serve` handlers call
`state/task_actions.py` (`unblock`, `kill`, `remove_assignee`) instead of
editing files. One `write_text_atomic` (`state/atomic.py`), one `iso.py`
clock helper, one `terminate_group` (in `workers/session/process.py`), one
`effective_coder_model` (`core/effective.py`).

### Rule 2 — one level of abstraction per function; policy as data

- No function over ~40 lines except a literal table.
- A dispatch over kinds is a dict (dictionary mapping keys to handlers)
  or a list of rules, not an if-chain: `RetryTable` for
  `retry_policy.decide`, rule list for `triage_policy`, `EVENT_MAP` per
  coder, `MODE_TEMPLATES` for prompt assembly, one event-description table
  (`observability/event_render.py`) shared by the terminal renderer and
  the API.
- A long loop with many accumulators becomes a list of small visitors
  (`state/events.py::VISITORS`), and a long aggregator becomes a registry
  of metric functions (`serve/analytics/metrics/*` + `SUMMARY_SECTIONS`).
- Long-running work is a set of small objects with a shared hook shape:
  the coder session is `CoderProcess` + `EventStream` + ordered monitors
  (`ContextGauge`, `AttemptBudget`, `HealthProbe`, `LeaseHeartbeat` in
  `workers/session/monitors.py`) + a pure `classify_exit`
  (`workers/session/classify.py`).

### Rule 3 — explicit registries, not hand-picked calls

Every "list of X" lives in exactly one named table. When you need to add
a kind, add a row — do not add a call site.

| Registry | Lives in | Lists |
|---|---|---|
| `ROUTERS` | `serve/api/__init__.py` | every API router mounted on the app |
| `SUMMARY_SECTIONS` | `serve/analytics/summary.py` | every analytics metric section |
| `DEFAULT_CHECKS` (the startup-checks list) | `orchestrator/checks.py` | every supervisor startup check |
| `MODE_TEMPLATES` | `prompts/__init__.py` | prompt template sets per launch mode |
| `_FLAGS` | `beads/create_args.py` | every `bd create` flag fleet rewrites |
| `COMMANDS` | `integrations/telegram/commands.py` | every inbound Telegram command |
| `EVENT_MAP` (one per coder) | `coders/claude.py`, `coders/codex.py`, `coders/agy.py`, `coders/opencode.py`, `coders/pi.py` | raw stdout line kinds → normalized events |
| `RETRY_TABLE` | `core/retry_policy.py` | every retry rule: streak kind → decision |
| `TRIAGE_RULES` | `core/triage_policy.py` | every blocked-task fix proposal |
| `VISITORS` | `state/events.py` | every per-event accumulator for stats |
| `WORKERS` | `workers/__init__.py` | every worker family (task, job, observer) |

`cli/main.py` (typer command registration) is the model: commands are
registered, not hand-wired.

### Rule 4 — layers are checked, names are one per concept

`tests/test_layering.py` asserts the import direction below by parsing
every file's imports. It fails on any new violation, and it fails if a
listed `KNOWN_VIOLATIONS` entry no longer occurs (so fixed entries get
removed). The `ALLOWED` dict, copied verbatim from the test:

```python
ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "state": {"core"},
    "beads": {"core", "state"},
    "schedules": {"core", "state", "beads", "workflows"},
    "workflows": {"core", "state", "beads"},
    "coders": {"core", "state"},
    "workers": {"core", "state", "beads", "coders"},
    "orchestrator": {
        "core", "state", "beads", "schedules", "workflows",
        "coders", "workers", "observability", "integrations",
    },
    "observability": {"core", "state"},
    "integrations": {"core", "state", "beads", "observability"},
    "serve": {
        "core", "state", "beads", "schedules", "workflows",
        "coders", "workers", "orchestrator", "observability",
        "integrations",
    },
    "cli": {
        "core", "state", "beads", "schedules", "workflows",
        "coders", "workers", "orchestrator", "observability",
        "integrations", "serve",
    },
}
```

In words, low to high: `core` → `state` → `beads` / `schedules` /
`workflows` → `workers` (+ `coders` beside it) → `orchestrator` /
`integrations` / `observability` → `serve` → `cli`. Lower layers never
import higher ones. `serve` and `cli` are entry points; they hold no
domain logic.

Vocabulary for all code: **task** (never bead/issue outside `beads/` and
the `fleet bd` passthrough), **attempt** (the file stays `run.json` for
compatibility but the type is `RunRecord`), **coder** (the CLI tool that
talks to the model) vs **worker** (the step list that runs it),
**outcome** (`TaskOutcome`) vs **result** (`RESULT.json` from the worker)
vs **decision** (retry policy).

## What "green" means

`just check` is the only definition of green: `ruff check`, `ruff format
--check`, `mypy`, config-docs drift check, UI types drift check, UI check
(when node deps are installed), then the unit suite (`pytest tests`,
excluding `tests/integration`). `just check-all` is `just check` plus the
integration suite (`tests/integration`). `just ui-types` regenerates the
UI's typed API client from the serve OpenAPI schema; `just ui-check`
typechecks, lints and unit-tests the web UI.

## Package layout

One line per module: what it owns, and who calls it. (Docstring first
lines; `__init__.py` files with no docstring are plain package markers.)

```
src/fleet/
  beads/                   # the one client for the bd CLI
    client.py              # subprocess calls to bd + envelope unwrap
    create_args.py         # _FLAGS: rewriting for `bd create` / `bd new` argv
    queue.py               # Beads-backed queue: the orchestrator's view of bd
    reconcile.py           # the one rule merging bd status into on-disk metadata
    status_cache.py        # TTL-cached map of beads status by task id
    task_store.py          # task.json access inside beads/ (state/ owns the file)

  cli/                     # thin commands: parse input, call a library, format output
    ask_human.py           # `fleet ask-human` question broker commands
    beads.py               # `fleet bd` passthrough with create-argv rewriting
    bootstrap.py           # the one place CLI commands get their dependencies
    config.py              # `fleet config` show/set
    daemons.py             # `fleet run` / `fleet serve` daemon management + `fleet tunnel`
    errors.py              # the one CLI error path: distinct exit codes
    main.py                # typer app: registers every command group (the registry model)
    options.py             # shared typer option aliases + serve endpoint resolution
    render.py              # all CLI printing: tables, status lines, log tails
    schedule.py            # `fleet schedule` recurring-worker commands
    workflow.py            # `fleet workflow` saved-workflow and run commands
    subproc.py             # the one way CLI commands spawn a child process
    tasks.py               # task commands: init, ready, show, tasks, task, kill, gc, job
    telegram.py            # `fleet telegram` status/test
    telegram_setup.py      # `fleet telegram setup` wizard

  coders/                  # one file per coder CLI + shared helpers; beside workers
    __init__.py            # lazy coder registry: names to implementations
    agy.py                 # agy coder + its EVENT_MAP
    base.py                # Coder contract + Workspace every coder runs in
    claude.py              # claude coder + its EVENT_MAP
    codex.py               # codex coder + its EVENT_MAP
    env.py                 # shared env overlays every coder composes into its spawn env
    mcp.py                 # Claude --mcp-config writer: which file, what goes in it
    model_ref.py           # one model-reference parser for the Ollama-routed coders
    ollama.py              # shared Ollama routing URL for the opencode/pi coders
    opencode.py            # opencode coder + its EVENT_MAP
    pi.py                  # pi coder + its EVENT_MAP
    settings.py            # env-derived knobs + per-coder settings records

  core/                    # domain types and constants. No I/O.
    clock.py               # one clock: real time in prod, fake time in tests
    compaction.py          # bounded inputs for a STATE.md compaction prompt
    compaction_fallback.py # deterministic compaction fallback without a model
    config.py              # RuntimeConfig: pure parse/render of runtime.toml data
    context_window.py      # per-model context windows: the one denominator for UI + supervisor
    effective.py           # effective coder/model resolution: the one rule
    errors.py              # typed domain errors: one exception per failure meaning
    git_status.py          # pure git-output classifiers: text in, facts out
    iso.py                 # one clock + one timestamp parser for the codebase
    isolation.py           # one reader for git-isolation info
    job_phase.py           # job worker phase policy (pure)
    job_plan.py            # job planning policy for observer/job workers (pure)
    job_ready.py           # epic readiness: is an epic's child set done enough to validate
    job_snapshot.py        # job worker phase snapshot (pure)
    launch_policy.py       # launch-mode policy: fresh vs continue + the continue pack (pure)
    leases.py              # pure lease policy: values in, verdict out
    limits.py              # behavioural constants: cadences, timeouts, retry bounds, API caps
    plan_input.py          # the narrow input every worker-family planner reads
    process.py             # process liveness probe shared by every layer
    redact.py              # credential redaction before events are stored/broadcast
    result.py              # RESULT.json contract: the worker's outcome declaration
    retry_policy.py        # RETRY_TABLE: retry policy as data (pure)
    task.py                # Task, Event, EventKind, TaskOutcome core types
    triage_policy.py       # TRIAGE_RULES: fix proposals for blocked tasks (pure)

  integrations/            # channels in and out of fleet
    ask_human/             # human-in-the-loop question broker (MCP server + SQLite store)
      server.py            # MCP server: agents ask, then block for the answer
      store.py             # QuestionStore: the only owner of the questions db
    mcp_servers.py         # the one source of truth for fleet-provided MCP servers
    ollama_tunnel.py       # SSH tunnel keeping the GPU-box Ollama reachable locally
    telegram/              # Telegram channel
      api.py               # Bot HTTP client, sync + async
      commands.py          # COMMANDS: inbound command handlers + answer routing
      listener.py          # inbound poll loop: fetch, filter senders, dispatch
      messages.py          # owner of the Telegram bookkeeping files under FLEET_HOME
      notify.py            # outbound notifications for new ask_human questions
      setup.py             # non-interactive logic behind `fleet telegram setup`
    web_fetch/             # fetch-a-URL-and-distill MCP server
      server.py            # the web_fetch MCP server

  observability/           # fleet watching itself
    daemon.py              # POSIX PID-file daemon manager for long-lived services
    event_render.py        # one table rendering worker events for humans (terminal + API share it)
    pidfile.py             # typed PID-file record for managed daemons
    process.py             # process facts for managed services: ServiceRegistry, service_status
    tailview.py            # human-readable events.jsonl rendering for the terminal

  orchestrator/            # the supervisor process, split by concern (ADR 0005)
    checks.py              # DEFAULT_CHECKS: startup checks run once before serving
    claim.py               # Claim service: poll the queue, enforce coder caps, spawn
    config_reload.py       # ConfigReload service: hot-reload runtime.toml on change
    git.py                 # GitRepo: the one place that shells out to git
    kill_sentinel.py       # KillSentinel service: honour .kill files promptly
    leases.py              # LeaseReconcile service: reclaim attempts whose heartbeat stopped
    merge_validation.py    # MergeValidation service: merge validated worktrees into base ref
    pause.py               # pause gate: the one owner of "is the supervisor paused"
    rate_gauge.py          # in-memory rate-limit usage gauge feeding the status line
    reap.py                # Reap service: collect finished runners, apply outcome policy
    retention_gc.py        # RetentionGc service: archive tasks, purge archives, drop worktrees
    scheduler.py           # Scheduler service: open beads for due schedules
    service.py             # Service / PeriodicService base types + emit
    spawn.py               # spawn claimed tasks: resolve coder, isolate, start the run
    stall.py               # StallWatch service: warn/kill silent runners, owns its sets
    state.py               # SupervisorState + RunningWorker: the shared blackboard
    status_log.py          # StatusLog service: periodic supervisor_status heartbeat
    supervisor.py          # lifecycle runner: checks, on_start, serve, on_stop, shutdown
    triage.py              # Triage service: one question per blocked bead, own cadence
                           # (+ repair-worker spawn for merge-conflict blocks)
    worktree.py            # git worktree create/sweep/remove helpers

  prompts/                 # prompt assembly for coder launches
    __init__.py            # MODE_TEMPLATES: template sets per launch mode
  templates/
    MERGE_REPAIR.md        # merge-conflict repair worker instructions (rendered by orchestrator/triage.py)

  schedules/               # recurring workers (ADR 0007)
    cron.py                # five-field cron parsing + next-firing math (pure)
    firing.py              # firing policy: what is due, overlap, opening the task
    model.py               # Schedule / ScheduleRun records
    store.py               # on-disk store for schedules + run history (only file-layout owner)

  serve/                   # FastAPI server; thin routes over state/ + core/
    analytics/             # aggregation moved out of the routes
      metrics/             # one file per metric section behind SUMMARY_SECTIONS
        attention.py       # tasks needing a look + raw rate-limit events
        context.py         # context-pressure histogram
        cost.py            # token-cost series + totals
        outcomes.py        # headline KPIs + per-model/per-project tables
        throughput.py      # completions per time bucket by outcome
        timing.py          # run/activity durations, waits, heatmap
        tools.py           # merged tool-call counts
      records.py           # one typed analytics row per task directory
      summary.py           # SUMMARY_SECTIONS registry + thin entry point
      window.py            # the time window every metric computes against
    api/                   # thin routers, one file per resource (all in ROUTERS)
      analytics.py         # analytics REST routes
      artifact_files.py    # artifact file reads for the task artifact routes
      beads.py             # beads portal REST routes
      chat.py              # chat tab: pending ask_human questions from the injected store
      config.py            # config read/write REST routes
      models.py            # pydantic models for every API request/response body
      schedules.py         # schedule CRUD + run-now + history routes
      search.py            # full-text search route
      stream_reads.py      # thread helpers for the task stream routes
      supervisor.py        # supervisor status + pause/resume routes
      system.py            # health + event websocket routes
      task_summary.py      # task view helpers shared by the routers
      tasks_actions.py     # task mutations: kill, requeue, unblock, remove-assignee
      tasks_artifacts.py   # task artifacts: STATE/RESULT snapshots, outputs, research, design
      tasks_attempts.py    # per-attempt routes via one artifact table
      tasks_detail.py      # single task: detail, children, attempts index
      tasks_list.py        # task collection: list, create, coders, templates
      tasks_stream.py      # task streams: logs, stderr, touched files, events
    app.py                 # FastAPI app factory + router registration
    auth.py                # bearer-token middleware + websocket check
    errors.py              # one JSON shape for every HTTP failure
    event_stream.py        # websocket event streaming pipeline
    openapi_dump.py        # dump the OpenAPI schema as JSON (feeds `just ui-types`)
    state.py               # injected serve state (queue, sockets, caches — never globals)

  state/                   # everything that touches a task directory on disk
    archive.py             # archive closed task dirs older than a retention window
    artifact_locator.py    # the one resolver of task artifact paths
    artifacts.py           # StateFile/ResultFile: owners of STATE.md + RESULT.json
    atomic.py              # write_text_atomic: the one atomic file write
    attempt_journal.py     # AttemptJournal: the one owner of attempts.jsonl
    attempt_summary.py     # deterministic per-attempt summary, derived on demand
    attempts.py            # thin call sites over attempt_journal
    config_file.py         # runtime.toml file I/O (pure parse/render stays in core/config)
    events.py              # the one events.jsonl reader + VISITORS derived-stats
    incremental_read.py    # read bytes appended to a growing file since an offset
    journal.py             # append_event, open_task_log, rotation
    legacy_task_dir.py     # read-only fallback for pre-STATE.md task directories
    paths.py               # the only module allowed to know task-dir file names
    run_file.py            # RunRecord: the one owner of attempts/<n>/run.json
    runtime_stats.py       # task runtime stats: log started_at + events scan
    task_actions.py        # file edits behind task moderation endpoints (unblock/kill/...)
    task_index.py          # TaskIndex: the one walker of tasks/*
    task_meta.py           # TaskMeta: the one owner of task.json
    task_summary.py        # the one task-summary dict shared by `fleet tasks` and GET /api/tasks
    validation_marker.py   # .needs_validation marker for isolated tasks needing a merge check

  workers/                 # step pipelines: what runs for a task, as composable steps
    __init__.py            # WORKERS: family routing (task, job, observer) by bead shape
    base.py                # Step protocol, StepContext, StepResult, Worker, run_worker
    child_env.py           # the one place a coder child environment is assembled
    compact.py             # compaction step: shrink STATE.md before a continue launch
    job.py                 # job family: research, design, gate, spawn, then observe
    llm_session.py         # LlmSession step: runs the coder session package below
    observe.py             # observer family: validate a finished epic, open follow-ups
    session/               # the coder-subprocess runner, split by concern
      classify.py          # pure exit classification for a finished session
      monitors.py          # ordered monitors: ContextGauge, AttemptBudget, HealthProbe, LeaseHeartbeat
      process.py           # CoderProcess: the one owner of the coder subprocess + group
      stream.py            # EventStream: live event feed from the coder's stdout
    task_family.py         # task family: fresh vs continue launch, decided in Python

  workflows/               # saved workflows: ordered stages planned onto the beads queue
    model.py               # saved definitions, runs, stage/needs rules
    planning.py            # pure run planning: order, labels, metadata, status table
    runs.py                # run engine: the one place that opens workflow beads
    store.py               # SQLite store for workflows, runs, step runs
    templates.py           # step text templates: fill run/task ids into titles
    yaml_io.py             # YAML import/export: one file per workflow
```

## Target layout (UI)

Four tabs (ADR 0009): Workers, Workflows, Inbox, Settings.

```
src/fleet/ui/src/
  app/                   # App.tsx (routes + legacy redirects), NavBar.tsx, GlobalEvents.tsx, queryClient.ts
  shared/
    api.ts  types.ts     # single source of API types; must match serve/api
    hooks/               # useApi.ts (every endpoint has a hook with a UI caller), useWebSocket.ts, ...
    format.ts            # fmtTs, fmtDuration, fmtTokens  (one copy)
    status.ts            # status -> color/label         (one copy)
    ui/                  # DataList, FilterBar, Confirm, EmptyState, StatusDot, Sparkline, Toast, small primitives
    styles/              # tokens.ts, recipes.ts, global.css (one styling approach; rem units)
  features/
    workers/             # WorkersPage.tsx (Runs + Scheduled sub-tabs, NeedsAttentionStrip), detail/TaskDetailPage.tsx, NewWorkerPanel.tsx
    triggers/            # shared schedule module parameterised by target (task | workflow): one form, one row, one drawer
    workflows/           # WorkflowsPage.tsx (Definitions, Runs, Scheduled), WorkflowRunPage.tsx, editor
    inbox/               # InboxPage.tsx, InboxDetailPage.tsx (pending ask_human questions; count badge in the tab)
    settings/            # SettingsPage.tsx (every RuntimeConfig field, grouped) + SupervisorSection.tsx
    command-palette/     # CommandPalette.tsx (entries only for live routes/actions)
```

## Schedules

Recurring workers live in `src/fleet/schedules/` (`cron.py` pure cron math,
`model.py` the `Schedule`/`ScheduleRun` records, `store.py` the one owner of
the files). Definitions are stored as `$FLEET_HOME/schedules/<id>.json`,
written by `serve`/`cli` on create/edit/delete; run history is the
append-only `$FLEET_HOME/schedules/<id>.runs.jsonl`, with one line per run
written by whoever fires it (the supervisor's scheduler for cron runs, the
API/CLI for manual runs). See ADR 0007.

## Task directory contract

`state/paths.py` is the only module allowed to know these names (old
task directories are read through the read-only `state/legacy_task_dir.py`
fallback; nothing writes the old layout):

```
$FLEET_HOME/tasks/<id>/
    task.json          # id, title, description, status, cwd, coder, model, blocked_reason, blocked_at, retry_after
                       # + triage ignore (ignore_until: ISO timestamp or "forever")
                       # + merge-conflict strand (merge_conflict, repair_task_id)
                       # + isolation opt-out (isolation) and, when isolated,
                      # repo_root, base_ref, worktree_path (replaces the old .worktree marker)
   attempts.jsonl     # start/end per worker attempt, append-only (task-level, unchanged)
   STATE.md           # worker memory: ## Plan, ## Done, ## In flight, ## Next, ## Facts
    RESULT.json        # completion contract, present only between worker exit and reap
    outputs.json       # workflow step outputs: flat string map for later steps (ADR 0010)
    outputs/           # real deliverables (reports, data) referenced from RESULT.json
   .kill .needs_validation                      # signals, not artifacts
   attempts/<n>/
     run.json         # identity, lease, launch {mode, pack_bytes, kind}, steps, exit metrics
     prompt.md        # the rendered prompt as sent
     mcp.json         # coder input (claude only)
     events.jsonl  log.jsonl  log.stderr
     STATE.md  RESULT.json                      # snapshots taken at reap
     .checkpoint_requested .checkpoint_sent .compacted   # signals
```

Signals (not artifacts): `.kill`, `.needs_validation`,
`.checkpoint_requested`, `.checkpoint_sent`, `.compacted` coordinate the
supervisor and hooks; the UI never reads them.

Beyond per-task dirs, the fleet home holds top-level state with one owner
per directory: `schedules/` holds recurring-worker definitions
(`<id>.json`) and their append-only run history (`<id>.runs.jsonl`),
owned by `schedules/store.py` (see "Schedules" above); `workflows.db`
holds saved workflow definitions, runs, and step runs, owned by
`workflows/store.py` (`WorkflowStore`, SQLite in WAL mode with ordered
migrations under `PRAGMA user_version`); `tasks/`,
`archive/tasks/`, `worktrees/`, and `logging/` hold task dirs, retained
archives, isolated worktrees, and supervisor logs.

`run.json`, `events.jsonl`, `log.jsonl`, `log.stderr` moved from the task
root into each attempt's own folder so that per-attempt slicing (tailing,
stall detection, the attempts timeline) doesn't have to guess where one
attempt ends and the next begins. `state/paths.py::attempt_dir`,
`state/attempts.py::attempt_dir` / `latest_attempt_dir` are the only
places allowed to build these paths; everyone else (stall, orphans,
cli `--log`/`--stderr`, the websocket tail) calls those helpers instead
of hardcoding "the latest attempt". `state/events.py::iter_events`
still reads across every attempt, oldest first, so history spans the
  whole task. `.kill` stays at the task
  directory root (it gates the *next* spawn, not one attempt).
  Context-pressure state is outcome-driven from `attempts.jsonl`
  (`outcome=context_pressure`); there is no `.context_pressure` marker file.
The RESULT.json schema and what fleet does with each `status` value are
documented once in `docs/WORKER_CONTRACT.md`; cite that file rather than
duplicating the contract elsewhere. Launch-mode planning (fresh vs.
continue) is documented in `docs/WORKER_CONTRACT.md`'s "Launch modes"
section.

## Testing layout

`tests/` mirrors `src/fleet/` folder for folder. A test for
`state/events.py` lives in `tests/state/test_events.py`. Integration
tests stay in `tests/integration/`.
