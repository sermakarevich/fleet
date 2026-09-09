# ADR 0006: One Owner, One Level, One Registry — the Codebase-Wide Clean Code Program

## Status

Accepted

## Outcome (2026-09-09, all 30 beads + docs bead done)

The program shipped. The five files named in Consequences changed shape
as follows (`wc -l`, before = audit-time size from Context above, after =
today; "before" for the two split files is the single function/closure
that dominated them):

| File | Before | After |
|---|---|---|
| `workers/llm_session.py` (`LlmSession.run`, 370 lines, 9 responsibilities) | ~370 in one function | `llm_session.py` 299 total, delegating to `workers/session/` (`process.py` 148, `stream.py` 102, `monitors.py` 397, `classify.py` 165) |
| `serve/analytics/summary.py` (`compute_summary`, 466 lines) | 466 in one function | 78: `SUMMARY_SECTIONS` registry over `metrics/*` |
| the old tasks.py router (`create_tasks_router`, 567-line closure, 25 routes) | 567 in one closure | split into 6 routers, 581 lines total (`tasks_list.py`, `tasks_detail.py`, `tasks_actions.py`, `tasks_artifacts.py`, `tasks_attempts.py`, `tasks_stream.py`, all in `ROUTERS`) |
| the old telegram bot.py (`inbound_listener`, 7 deep) | one file | split into 7 modules, 693 lines total (`api.py`, `commands.py`, `listener.py`, `messages.py`, `notify.py`, `setup.py`, `COMMANDS` registry) |
| `core/retry_policy.py` (`decide`, 129-line switch) | 129 in one switch | 468: the explicit `RETRY_TABLE` plus per-rule detail |
| `beads/queue.py` | oversized, talked raw `bd` everywhere | 452, talks to `bd` only via `beads/client.py`, `_FLAGS` registry in `beads/create_args.py` |

Final module names where they differ from the Rule 1 table: none — every
owner landed under the name the ADR proposed (`state/task_meta.py`,
`state/attempt_journal.py`, `state/run_file.py`, `state/artifacts.py`,
`state/task_index.py`, `state/config_file.py`,
`integrations/ask_human/store.py::QuestionStore`,
`observability/process.py`). The startup-checks registry of Rule 3 is
`DEFAULT_CHECKS` in `orchestrator/checks.py`. `just check` is green on
the merge commit.

## Date

2026-09-08

## Context

ADR 0005 rebuilt the supervisor as a runner of ordered services. An audit of
every other package on 2026-09-08 (core, state, beads, workers, coders,
serve, integrations, observability, cli, ui, tests, tooling) found the same
four problems repeated everywhere. Numbers below are from that audit.

**1. Files and records have no single owner.**
`task.json` is written by `beads/queue.py` and rewritten directly by
the old tasks router (now split — see Outcome); it is parsed in eight
modules. `STATE.md` and
`RESULT.json` have no writer inside `state/` at all (written by
the task worker module (now `workers/task_family.py`),
`workers/compact.py`, `workers/job.py`, snapshotted by
`orchestrator/reap.py`). `run.json` is read-merge-written in `workers/base.py`
and parsed in three other modules with no dataclass. The
`ask_human` question database is reached through a class and six module
functions that resolve the path from a mutable global.

**2. One function does many jobs at many levels.**
`workers/llm_session.py::LlmSession.run` is 370 lines with nine
responsibilities. `serve/analytics/summary.py::compute_summary` is 466 lines.
the old tasks router's `create_tasks_router` was a 567-line closure holding 25
routes. `core/retry_policy.py::decide` is a 129-line switch over a table
that exists only in comments. the old telegram bot's `inbound_listener`
nests seven deep.

**3. The same helper exists many times.**
Atomic file write: 5 copies. ISO timestamp parsing: 4. Walk the tasks
directory and parse `task.json`: 4. Pid liveness: 3. Pid-file parsing: 4.
Fingerprint staleness: 4. SIGTERM→wait→SIGKILL: 6 copies inside one file.
Effective coder/model rule: 4. Log-dir resolution: 2 identical bodies.
Dependency-cycle check: 2. Worktree resolution: 2. The FLEET_* env dict: 5.

**4. Layers leak.**
`state/task_summary.py` imports `beads`, `serve` and `coders`. `state/journal.py`
imports `observability`. `core/config.py` does file I/O. `orchestrator/supervisor.py`
and `cli/tasks.py` import the old stats module (now
`state/runtime_stats.py`), a file that is state-layer code.
the old telegram bot reached into FastAPI `app.state`. Nothing
checks the import direction, so every violation is silent.

Vocabulary drifts with the code: task / bead / issue; attempt / run / round;
coder / worker; outcome / status / result / decision; `fleet_home` / `home`
/ `tdir`.

## Decision

Four rules, applied to every package, with a test that enforces the ones a
test can enforce.

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

`beads/queue.py` shrinks to talking to `bd`. `serve` handlers call
`state/task_actions.py` (`unblock`, `kill`, `remove_assignee`) instead of
editing files. One `write_text_atomic`, one `iso.py` clock helper, one
`terminate_group`, one `effective_coder_model`.

### Rule 2 — one level of abstraction per function; policy as data

- No function over ~40 lines except a literal table.
- A dispatch over kinds is a dict or a list of rules, not an if-chain:
  `RetryTable` for `retry_policy.decide`, rule list for `triage_policy`,
  `EVENT_MAP` per coder, `MODE_TEMPLATES` for prompt assembly, one
  event-description table shared by the terminal renderer and the API.
- A long loop with many accumulators becomes a list of small visitors
  (`state/events.scan_rows`), and a long aggregator becomes a registry of
  metric functions (`serve/analytics/metrics/*` + `SUMMARY_SECTIONS`).
- Long-running work is a set of small objects with a shared hook shape, as
  in ADR 0005: `LlmSession` becomes `CoderProcess` + `EventStream` + ordered
  monitors (`ContextGauge`, `AttemptBudget`, `HealthProbe`, `LeaseHeartbeat`)
  + a pure `classify_exit`. `Compact` reuses the same process wrapper
  instead of its own streamer.

### Rule 3 — explicit registries, not hand-picked calls

`ROUTERS` in `serve/api/__init__.py`; `SUMMARY_SECTIONS`; `STARTUP_CHECKS`
(ADR 0005); `MODE_TEMPLATES`; `_FLAGS` for `bd create` rewriting; telegram
`COMMANDS`; `ServiceRegistry` for daemons; `cli/main.py` already does this
and is the model.

### Rule 4 — layers are checked, names are one per concept

- `tests/test_layering.py` asserts the import direction
  `core < state < beads < workers < orchestrator | serve | cli`, `coders`
  beside `workers`, `observability` and `integrations` importable from
  `state` upward only for `redact` (which moves to `core/redact.py`). The
  test fails on any new violation.
- Vocabulary: **task** (never bead/issue outside `beads/` and the `fleet bd`
  passthrough), **attempt** (the file stays `run.json` for compatibility
  but the type is `RunRecord` of an attempt), **coder** (the CLI tool) vs
  **worker** (the step list), **outcome** (`TaskOutcome`) vs **result**
  (`RESULT.json` from the worker) vs **decision** (retry policy). New code
  uses these; renames of existing public names happen only inside the
  bead that touches that module.
- Errors: `except Exception` is allowed only where it converts to a typed
  result (`StepResult(fail)`, HTTP 5xx) **and** logs with the exception.
  Never `except ...: pass` around a write that a later reader depends on
  (`state/attempts.set_worker`, `beads/queue.create_child` dep add,
  `coders/claude.build_argv` mcp write).
- Tooling: `just check` = `ruff check` (no `--exit-zero`), `ruff format
  --check`, `mypy`, `pytest`; CI runs it. API responses get pydantic
  models and the UI types are generated from OpenAPI, so drift between
  `shared/types.ts` and the backend fails the build.

## Consequences

- About 3,000 lines move; behaviour does not change. Each bead keeps the
  suite green and is reviewable alone.
- `beads/queue.py`, the tasks routers, `llm_session.py`, `summary.py`,
  the telegram bot each lose more than half their length.
- New contributors can answer "who writes this file" and "where is the
  list of X" by opening one module.
- Cost: one serial chain of 31 beads after the ADR 0005 chain (15 structural beads, then a second batch of 15 from the composition/typing/naming/runtime audits, then the docs bead) (same working
  tree, shared files, so serial). UI work is the last two beads because
  generated types need the pydantic models first.
- Risk: renames break external scripts that import private names. The
  layering test and `ruff` catch internal breakage; `bin/` scripts are
  checked by hand in the tooling bead.

## Chain (one bead each; each spec names its files, tests and DoD)

Beads 1–15 come from the first structural audit. Beads 16–30 come from a
second audit (inheritance vs composition, typing, naming, Python runtime
practice, serve/integrations hardening, UI runtime, tests). The docs bead runs
last so every path it documents exists.

| # | Bead | Packages |
|---|---|---|
| 1 | Tooling: `just check`, strict ruff, mypy wired, CI, dead settings | pyproject, justfile, Makefile, CI |
| 2 | State owners: TaskMeta, AttemptJournal, RunRecord, StateFile/ResultFile, one atomic write, `core/iso.py` | state, core, callers |
| 3 | Layer fixes + layering test: `serve/stats` → `state/runtime_stats`, config I/O → `state/config_file`, `redact` → core, `task_summary` imports | state, core, serve, cli, orchestrator |
| 4 | beads: `Queue` interface honest, `TaskStore` split, one claim algorithm, `_FLAGS` registry, no swallowed dep add, client timeout | beads |
| 5 | core policy tables: RetryTable, triage rules, SpecValidator, events visitors, dedupes | core, state/events |
| 6 | workers/session: CoderProcess, EventStream, monitors, classify_exit, terminate_group; Compact reuses | workers |
| 7 | coders: base env, OllamaCoder mixin, EVENT_MAP runner, mcp.py, `prompts/` with MODE_TEMPLATES, Workspace | coders, prompts, templates |
| 8 | workers job/observe: phase steps, JobSnapshot, declared config fields, plan on ctx | workers, core |
| 9 | serve core: auth.py, state.py, ROUTERS, TaskIndex, task_actions, process status, routers ≤120 lines | serve, state, observability |
| 10 | serve analytics: metrics registry | serve/analytics |
| 11 | integrations: QuestionStore only; telegram split (api, notify, commands, messages, listener); event render table | integrations, observability, serve/app |
| 12 | cli: render.py, artifact locator, effective_coder_model, bootstrap.py, job view; no command > 25 lines | cli, state, orchestrator |
| 13 | API models + generated UI types (`just ui-types`) | serve/api, ui/shared |
| 14 | UI structure: styles recipes, BeadsPage split, diff.ts, useBeadFilters, ChatPage; vitest + eslint in `just check` | ui |
| 16 | Composition over inheritance — coders: `Coder` Protocol + frozen `CoderSpec`, lazy registry, env reads in one place | coders |
| 17 | Composition over inheritance — `FnStep`, `PeriodicService` as data, `Service` Protocol, `StartupCheckSpec`, no `Daemon` class, closures instead of `_DualSink`/`TaskLog` | workers, orchestrator, state, observability |
| 18 | Typed domain: `EventKind`/`TaskStatus`/`ResultStatus`/`StepStatus` StrEnums, `TaskSummary`/`Question`/`AttemptRow` types, frozen+slots value objects, `core/errors.py` | core, state, workers, integrations |
| 19 | Naming: `fleet_home` everywhere, no private cross-module imports, no single-letter params, dry-run flags → plan/apply, module renames | all |
| 20 | Orchestrator seams: `GitRepo`/`TaskWorktree` + pure `classify_status`, `classify_lease`, reap `APPLY` table, injected `Clock`, dedupes | orchestrator, core |
| 21 | Workers/coders seams: `ProcessRunner`, `child_env`, steps hold queue/store (no factories), `PlanInput`, `coder_factory` | workers, coders, orchestrator |
| 22 | Runtime hygiene: subprocess timeouts, no blocking I/O in `async def`, one UTC clock, supervised background tasks, poller backoff | serve, integrations, state |
| 23 | Serve hardening: `require_token` (constant-time, covers healthz/ws), bounded `Query` params, one error shape, CORS field, artifact route table | serve, core |
| 24 | Integrations hardening: sqlite `user_version` migrations + per-thread connection, `TelegramApi.call`, `TunnelSettings` + tunnel as a daemon, fleet root resolution | integrations, cli |
| 25 | Observability: `PidFile` record, start lock + liveness window, log rotation, memoised fingerprint, tailview timestamp fix | observability, state |
| 26 | CLI polish: `errors.py` + `ExitCode`, shared options, `serve_host/port` config, bd passthrough via `BdClient`, help epilogs | cli, core |
| 27 | UI runtime: `POLL` constants gated on socket, `useEventSocket` with backoff, `useTaskMutation` (every failure toasts), `ApiError` body parsing, react-query everywhere, `useNow` | ui, cli/render |
| 28 | UI accessibility + naming: `Modal`/`Tabs`/`Clickable` primitives, jsx-a11y, consistent component/format names | ui |
| 29 | Tests hygiene: split files > 500 lines, fakes (`FakeTelegramApi`, `FakeProcessRunner`, `FakeClock`, `FakeQueue`), no sleeps, no private patching, hygiene test | tests |
| 30 | Configuration surface: field metadata → generated `docs/CONFIG.md` + `runtime.toml.header`, documented env vars and tunables | core, cli, docs |
| final | Docs: ARCHITECTURE layout and rules updated, OVERVIEW, PRODUCT_PLAN; this ADR Accepted | docs |

## Affects

Every package under `src/fleet/`, `tests/`, `docs/ARCHITECTURE.md`,
`docs/OVERVIEW.md`, `docs/PRODUCT_PLAN.md`, `justfile`, `Makefile`,
`pyproject.toml`, `.github/workflows/ci.yml`, `src/fleet/ui/`.
