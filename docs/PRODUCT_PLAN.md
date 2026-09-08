# Fleet Productization Plan

What it takes to move fleet from a single-operator proof of concept to a platform that can run commercial AI workflows and "AI employees": stable, observable, self-healing, schedulable, configurable, and safe to expose to more than one person.
- Reviewed 7 Sep 2026
- Branch `main` at 43a65ba plus uncommitted work
- Python core, FastAPI server, React UI, beads queue

## Verdict

**Fleet is a good proof of concept with real operating hours behind it, but its architecture is "files plus a CLI plus a prose protocol".** That is fine for one operator on one laptop. It breaks in three fundamental ways once it has to be a product.

**1. No single source of truth.** Task state lives in four places (beads database, `task.json`, a set of dot-files, and supervisor memory). Nothing reconciles them. A supervisor crash leaves claims and child processes orphaned.

**2. No security or tenancy.** Every API route and WebSocket is open, the server binds to all interfaces by default, and there is no notion of user, project, or organization anywhere in the data model.

**3. No control plane.** There is no scheduler (no recurring tasks, no dependency-aware ordering, no backoff), no worker supervision (stalled agents are only warned about, never restarted), and no process supervision for fleet itself.

The recommendation is a deep refactor in seven phases (0 to 6) over roughly four to five months of focused work, keeping the CLI and UI usable throughout. The centerpiece is making fleet's own database authoritative and demoting beads to an optional adapter.

## What exists today
- **~7,100** lines of Python in `src/fleet`
- **881** tests collected
- **89** tests failing on the current dirty tree
- **5** coder adapters (claude, codex, opencode, agy, pi)
- **2,493** task directories in `~/.fleet/tasks`
- **2.5 GB** fleet home; 1.5 GB is the beads Dolt database

The runtime is one asyncio process (`supervisor.py`) running ten ordered services: ConfigReload, LeaseReconcile, Claim (claim-and-spawn every 5 s), MergeValidation, Reap, StallWatch, KillSentinel, Triage, RetentionGc, and StatusLog (see ADR 0005). Each claimed task becomes a `TaskRunner` that spawns a coder CLI, tails its NDJSON stdout into `events.jsonl`, and classifies the exit into one of six outcomes. A 160-line `match` block in `_handle_outcome` holds all retry, release, block and validation policy.

Around that core: a FastAPI server that derives every view by re-reading task directories and shelling out to `bd`; a React UI on React Query polling plus a file-watcher WebSocket; a Telegram bot for notifications and task intake; and an `ask_human` MCP (Model Context Protocol) server backed by SQLite that lets a blocked agent wait for a human answer.

Three writers, four stores, no coordinator. Every arrow is an independent read or write with no transaction across them.

## Findings by theme

Each finding names the code so the team can go straight to it. Severity reflects impact on a commercial deployment, not on today's single-user setup.

### Stability and crash recovery (Critical)
- **Claim is not atomic.** `claim_next` runs `bd ready`, then a separate `bd update --claim`, then writes `task.json`. Two supervisors, or a supervisor and a human, can double-claim. A crash between the two writes leaves beads and task.json disagreeing forever. (`queue.py:223-252`)
- **No recovery of in-flight work.** Runner state is only in memory. If the supervisor dies, children keep running as orphans (no process group, unlike the daemon wrapper), and the task stays `in_progress` with nobody to release it. Startup only sweeps worktrees. (`supervisor.py:68-70, 103-125`)
- **Blocking subprocess calls inside the event loop.** Every queue operation is a synchronous `subprocess.run` called from async loops, freezing all runners' log tailing and the kill poll for the duration of each `bd` call. (`queue.py:181, supervisor.py:127`)
- **Transient errors are read as "task closed".** `_bead_in_progress` swallows every exception and returns False, which routes the outcome into the "already closed" branch and resets failure counters. (`supervisor.py:459-463`)
- **Validation merges run on the shared working tree.** Isolated-task merges check out `main` in the fleet repo while non-isolated tasks may be running in that same tree. One merge per tick also means an unbounded backlog. (`supervisor.py:187-253`)
- **Unbounded growth.** No rotation or retention for `events.jsonl`, `log.jsonl`, or task directories. The home is already 2.5 GB and the Dolt database needs a manual squash recipe. (`logging.py:127-147, justfile beads-gc`)

### Worker health and automatic restart (Critical)
- **Stall detection only warns.** The status loop compares the `events.jsonl` modification time against `stall_warning_minutes` and logs once. It never kills, restarts, or escalates. A hung agent holds a concurrency slot indefinitely. (`supervisor.py:435-457`)
- **Retry policy is a flat counter.** Two failures then block, retried on the next 5 s poll with no backoff, no jitter, and no distinction between an out-of-memory crash, a network blip, and a logic error. (`schemas.py:8, supervisor.py:596-641`)
- **Completion is inferred, not signaled.** Exit code 0 counts as success, then the supervisor checks whether the agent remembered to run `fleet bd close`. If not, the task is re-run up to twelve times. This is the cause of most wasted spend and the reason "done" cannot be trusted. (`runner.py:252-270, supervisor.py:489-523`)
- **No resource limits.** No wall-clock cap, memory or CPU limits, or per-task token budget on spawned agents. The only cap is the global concurrent count.

### Recurring tasks, scheduling and dependencies (Missing)
- There is no scheduler component at all. Tasks exist only because something called `bd create`. Nothing can express "every weekday at 09:00" or "when the nightly build fails".
- Dependencies are delegated to beads' `ready` query. The supervisor has no view of the graph, so it cannot plan, visualize, or prioritize across a DAG (directed acyclic graph) of tasks. (`queue.py:194-200, 323`)
- Priority is a sort key only. No preemption, no per-project or per-tenant fair share, no deadline awareness.

### Configurability (Weak)
- `RuntimeConfig` is a flat dataclass of fourteen fields, several of them coder-specific (`opencode_*`). Validation is a bare type cast; unknown keys are silently dropped; the `coder` value is only validated at spawn time. (`schemas.py:76-91, config.py:33-39`)
- Retry limits, poll intervals, grace periods and the no-close limit are module constants, not configuration. (`schemas.py:6-12`)
- Per-coder concurrency is a comma-separated string re-parsed on every check. There is one global config for everything: no per-project, per-employee, or per-tenant layering. (`concurrency.py`)
- Hot reload swaps the whole object every 5 s by mtime. Runners keep a reference to the old object, which is correct today but undocumented.

### Security and multi-tenancy (Blocking for a product)
- **No authentication anywhere.** All REST routes and both WebSocket endpoints are open, and the server binds `0.0.0.0` by default. (`cli.py:362, serve/app.py`)
- **Remote process control and config rewrite without auth.** `/api/supervisor/restart` spawns a process; `PUT /api/config` rewrites `runtime.toml`, including the Telegram allowlist that gates task creation. (`routes/supervisor.py:96-118, routes/config_routes.py:26`)
- **Agents run with full host permissions.** Every adapter passes a skip-permissions flag (`--dangerously-skip-permissions`, `--dangerously-bypass-approvals-and-sandbox`, `external_directory: allow`). Task descriptions are interpolated into the prompt unescaped. Any task can name any `cwd`. (`claude.py:74, codex.py:46, opencode.py:240, tasks.py:415`)
- **No tenant dimension.** One home directory, one beads database, one config, one task namespace. No user, project, workspace or organization exists in any schema.
- Redaction inspects dictionary keys only; a secret pasted into a tool command string passes through. (`redact.py:21-31`)

### Monitoring and observability (Partial)
- Good raw material: structured JSONL logs per task, a normalized event stream, an analytics page with throughput, context pressure and rate-limit classification.
- But everything is derived by re-parsing files on request. Every dashboard poll walks all task directories and runs a `bd list` subprocess (cached 5 s). (`routes/tasks.py:89, 268; beads_info.py:15`)
- `/healthz` only reports whether the code fingerprint is stale. No readiness check of the queue, disk, or watcher. No Prometheus or OpenTelemetry export, no alerting, no audit log, no dollar-cost model.
- The UI patches task status client-side because the single-task endpoint is documented as stale. Two sources of truth reconciled in three places. (`ui/src/hooks/useApi.ts:10-25`)

### Coder adapter layer (Needs a real interface)
- The base class has three abstract methods. Prompt assembly, environment setup, and Bedrock and Ollama model routing are copy-pasted across five files. Registration is a hardcoded dictionary. (`coders/base.py, coders/__init__.py:8-14`)
- Event normalization quality varies widely. The agy adapter turns every non-JSON line into an assistant message; opencode overloads one field for three meanings. There is no error taxonomy and no structured completion event. (`agy.py:100-106, opencode.py:263`)
- Context limits are class attributes for two coders and instance attributes for two others, so the UI can display the wrong limit. (`opencode.py:44-46`)
- No capability discovery, health check, or cost model. A stale `pi.py.broken.bak` ships in the source tree.

### Engineering hygiene (Needs a floor)
- The working tree carries an unfinished `Queue` interface change; 89 tests fail because the test `MemoryQueue` and a doc-sync test were not updated. Twelve untracked Playwright debug files sit in the repo.
- No CI, no linter or type checker configured, no pre-commit, no Dockerfile, no release tagging. Two competing dev-dependency mechanisms in `pyproject.toml`.
- The wheel does not ship the built UI. The server restart path runs `make ui-build` from a source checkout, so deployment depends on a dev environment.
- No UI tests. Well-covered Python unit tests, but test logic is duplicated per coder because the production code is.
- The `cli/` package mixes daemon management, rendering, and five sub-apps.

## Target architecture

The shape to aim for is a small control plane with one authoritative store, explicit state machines, and thin adapters at the edges. It stays a single Python service for now, but every boundary below is one you could later split into its own process.

One store, one writer path (the API and control plane), adapters at the bottom. Agents no longer close their own tasks; they emit a structured result that the state machine consumes.

### Components and what changes

| Component | Today | Target |
|---|---|---|
| State store | beads Dolt DB + task.json + dot-files + RAM | SQLite (WAL) via SQLAlchemy and Alembic migrations, designed so Postgres is a config change. Beads becomes an optional sync adapter. |
| Task lifecycle | Implicit in a 160-line match block | Explicit state machine with a transition table. Each transition is an appended `run_events` row. Replayable on restart. |
| Scheduler | Poll `bd ready` every 5 s | Cron and interval triggers, dependency-aware ready set, priority and per-project quotas, exponential backoff with jitter, deadline flags. |
| Worker pool | asyncio task per runner; stall warning only | Process groups, PID persisted, heartbeat from events plus optional adapter ping, configurable stall policy (warn → kill → restart → block), wall-clock and token budgets, boot-time reconciliation of orphans. |
| Agent adapters | 3-method ABC, hardcoded registry | Adapter interface with capability flags, health check, cost model, shared prompt builder, unified event schema with error taxonomy, entry-point plugin registration. |
| Completion contract | Agent runs `fleet bd close` | Agent writes a schema-validated `RESULT.json` (or the adapter emits a `task_result` event). Exit 0 without a result is a failure, not a success. |
| Sandbox | Skip-permissions on host | `Sandbox` strategy chosen per project: host, git worktree, or container (Docker or Apple container). Skip-permissions scoped inside the boundary. |
| API | Open, derived from disk per request | Authenticated, tenant-scoped, DB-backed, paginated. Server-sent events from an in-process bus instead of a file poller. |
| Observability | JSONL logs and an analytics page | Prometheus `/metrics`, OpenTelemetry traces per run, real readiness probe, audit log, cost per task/project/employee, alert rules. |
| Deployment | Pidfile daemons, `make` from a checkout | Container image plus systemd and launchd units with restart-on-failure. Wheel ships the built UI. |

## Domain model for "AI employees"

The product framing needs nouns that fleet does not have yet. These are the tables the new store should be designed around from day one, even if the UI exposes them gradually.

| Entity | Meaning | Replaces or extends |
|---|---|---|
| Tenant | Billing and isolation boundary. Owns users, projects, quotas, secrets. | Nothing today |
| Project | A repository or working area with its own sandbox policy and allowed paths. | The `cwd` field in task.json |
| Employee | A persistent agent identity: role description, coder and model, skills and MCP servers, standing instructions, persistent memory, cost budget. | Per-task coder/model overrides plus `STATE.md` |
| Playbook | A parameterized task template with acceptance criteria and required outputs. | Ad hoc titles and descriptions |
| Schedule | Cron or interval trigger that instantiates a playbook for an employee. | Nothing today |
| Task | One unit of work with state, priority, dependencies, deadline. | A beads issue |
| Run | One attempt at a task: PID, sandbox, tokens, cost, outcome, artifacts. | Implicit in log files |
| Event | Normalized agent or system event tied to a run. | `events.jsonl` |
| Question / Approval | Human-in-the-loop items with assignee, SLA, and answer. | ask_human SQLite |
| Audit entry | Who changed what, when, from where. | Nothing today |

## Decisions to make before starting

| Decision | Recommendation | Why |
|---|---|---|
| Keep beads as the store? | Demote to adapter | Beads causes most of the stability findings: subprocess per call, non-atomic claim, a second copy of state, a 1.5 GB database. Keep it as an optional two-way sync for users who already live in beads. |
| Database | SQLite first, Postgres-ready | Single-node deployments stay zero-ops. SQLAlchemy plus Alembic keeps the door open. Avoid hand-rolled SQL as in `ask_human_db.py`. |
| Completion signal | Structured result file | Works for every coder without hooks. Adapters can additionally emit events. Removes the twelve-rerun no-close loop. |
| Sandbox default | Container for untrusted projects, worktree for trusted | Skip-permissions is unavoidable for headless agents, so the boundary must move to the process, not the prompt. |
| Auth | API keys now, OIDC later | Unblocks CLI and integrations immediately; SSO is a tenant-level feature that can follow. |
| Language and runtime | Stay in Python | A rewrite would burn the 881 tests and the adapter knowledge. The changes are structural, not language-bound. |
| Real-time transport | Server-sent events | Simpler than WebSocket for one-directional streams, proxy-friendly, and fed by the in-process event bus instead of polling files. |

## Roadmap

Seven phases, numbered 0 to 6. Estimates assume one senior engineer full time, using fleet itself to farm out the mechanical parts to cheaper models. Each phase ends with a shippable state, and the CLI and UI keep working through every phase.

### Phase 0. Stabilize the ground

*1 week — Start here*
- Finish or revert the in-flight `Queue.set_bd_fields` change; get the suite green and commit.
- Add GitHub Actions running pytest, ruff, mypy in lenient mode, and `tsc` plus `vite build`. Add pre-commit.
- Clean the tree: ignore `.playwright-mcp/`, delete `pi.py.broken.bak` and `supervisor_worktree.py`, unify dev dependencies.
- Bind the server to `127.0.0.1` by default and put a single shared-secret bearer token in front of all routes and WebSockets. Crude, but it closes the open door while the real auth is built.
- Move `bd` calls off the event loop with `asyncio.to_thread`. Add process groups to runner spawns so shutdown kills grandchildren.

**Exit:** green CI on every push, no unauthenticated route, no orphaned processes on restart.

### Phase 1. One source of truth

*3 to 4 weeks*
- Introduce the SQLite store with the domain model above (tenant and employee tables can be single-row placeholders for now). Alembic migrations from the first commit.
- Write the explicit task state machine and the `run_events` append log. Replace the dot-files (`.failures`, `.noclose`, `.needs_validation`, `.kill`, `.worktree`) with columns and transitions.
- Implement `LocalQueue` over the store with a transactional claim. Keep `BeadsQueue` as a sync adapter that mirrors state outward and imports new issues inward.
- One-shot migration tool: import the existing 2,493 task directories and beads export into the store, then apply a retention policy (archive closed runs older than N days, compress event logs).
- Split `Supervisor` into `Scheduler`, `WorkerPool`, and `OutcomePolicy`. The policy becomes a table of outcome to handler, unit-tested without subprocesses.

**Exit:** the supervisor can be killed with `kill -9` mid-run and, on restart, reconciles every task correctly with no manual cleanup.

**Done (7 Sep 2026):** block reason + restart/attempt history are now recorded (`attempts.jsonl`, `blocked_reason`/`blocked_at`) and visible in the UI (Tasks tab, task header banner, Runs tab), with a dedicated `POST /api/tasks/{id}/unblock` that also resets the failure/no-close/stall counters.

### Phase 2. Reliable workers

*2 to 3 weeks*
- Structured completion contract: `RESULT.json` schema (status, summary, artifacts, follow-up tasks) written by the agent; adapters validate it. Update `INSTRUCTION.md` and drop the "run `fleet bd close`" instruction.
- Stall policy as configuration: idle threshold, action ladder (warn, kill and retry with context handoff, block), maximum wall-clock per run, token budget per run and per task.
- Retry policy with failure classes: transient (network, rate limit) versus deterministic (non-zero exit twice with same stderr signature), exponential backoff with jitter, per-class limits.
- Heartbeat from the adapter: events as today plus a lightweight liveness signal so "thinking for 20 minutes" and "hung" can be told apart.
- Resource limits via `resource.setrlimit` in a preexec function and per-run temp directories.

**Exit:** a deliberately hung fake agent is detected, killed, and retried without human action; exit 0 without a result is recorded as a failure, not a success.

### Phase 3. Scheduling and recurrence

*2 weeks*
- Schedules table and a tick loop that instantiates playbooks on cron or interval triggers, with overlap policy (skip, queue, or replace) and time zone support.
- Dependency graph owned by fleet: ready-set computation, cycle detection, fan-out and fan-in from `RESULT.json` follow-ups.
- Priority classes with per-project fair share and a preemption flag for urgent work.
- CLI and UI: `fleet schedule create "0 9 * * 1-5" --playbook daily-triage --employee reviewer`, a schedules page, and a DAG view on the task page.

**Exit:** a nightly recurring task runs unattended for two weeks with correct skip-on-overlap behavior and a visible run history.

### Phase 4. Security and tenancy

*3 to 4 weeks*
- Users, API keys, and roles (owner, operator, viewer). Every route and stream scoped by tenant and project. Audit log on every mutation.
- Project-level sandbox policy: allowed roots, container image, network policy, secret injection via environment from the tenant secret store, never from `runtime.toml`.
- Layered configuration: defaults, tenant, project, employee, task. Validated with pydantic, documented, hot-reloaded with a version stamp.
- Prompt hygiene: escape task text before templating, separate system instructions from user-supplied content, redaction of values not just keys.
- OIDC login for the UI when a tenant configures it.

**Exit:** two tenants on one instance cannot see or affect each other's tasks, files, or configuration, verified by an integration test.

### Phase 5. Observability and operations

*2 weeks*
- Prometheus metrics (queue depth, running, stalled, retries, tokens, cost, latency to claim), OpenTelemetry spans per run, real `/readyz`.
- Cost model per adapter and model with a version table; cost per run, task, employee, project, tenant surfaced in the UI and exported.
- Alert rules and notification channels (Telegram, Slack, email, webhook) as pluggable notifiers with per-tenant routing.
- Container image, systemd and launchd units with restart-on-failure, a `fleet doctor` command, backup and restore of the store, documented upgrade path.
- Split `cli.py` into a package; make the CLI a thin client over the authenticated API so remote control works the same as local.

**Exit:** an operator can deploy from a container image, see a Grafana dashboard, and receive an alert when an employee stalls or exceeds budget.

### Phase 6. The employee layer

*4+ weeks, iterative*
- Employee records with role instructions, skills (MCP servers and tools), persistent memory that outlives tasks, and budgets. Migrate per-task `STATE.md` into per-employee and per-project memory.
- Playbook library with acceptance criteria, required outputs, and review gates (auto-merge, human approval, second-agent review).
- Intake channels beyond Telegram: Slack, email, GitHub issues, webhooks. Each maps to a project and employee by rules.
- Reporting: per-employee weekly summary, throughput, quality signals (rework rate, blocked rate), spend.
- Adapter marketplace: entry-point registration, capability flags, conformance test suite that any new adapter must pass.

**Exit:** a customer can define an employee, give it a schedule and a playbook, and receive its work through their own channel without touching a terminal.

**Total: roughly 17 to 20 engineering weeks.** Phases 0 through 2 are the ones that change the failure profile; do them in order. Phases 3, 4 and 5 can overlap if a second person joins. Phase 6 is where the product differentiates and should be shaped by the first design-partner customers.

## First two weeks, concretely
1. Get the suite green: implement `MemoryQueue.set_bd_fields` in the integration conftest, update the doc-sync test, commit the ollama tunnel work, ignore the Playwright artifacts.
2. Add `.github/workflows/ci.yml`, `ruff` and `mypy` config, and pre-commit.
3. Default bind to loopback and add a bearer token middleware in `serve/app.py`. Read the token from `FLEET_API_TOKEN`; the UI stores it once.
4. Wrap `BeadsQueue._bd` in a thread executor and expose async methods; spawn runners with `start_new_session=True` and kill by process group.
5. Persist the child PID in the run record and add a boot-time reconciliation pass that releases claims whose PID is gone.
6. Turn the stall warning into an action: after `stall_warning_minutes`, kill and release with a comment; after two stalls, block. Make the limit configurable per task.
7. Add rotation for `events.jsonl` and a `fleet gc` command that archives closed task directories older than 30 days. This alone recovers most of the 2.5 GB.
8. Write the ADR (architecture decision record) for "store first, beads as adapter" so Phase 1 starts with agreement rather than debate.

## Risks and how to hold them

| Risk | Mitigation |
|---|---|
| Big-bang rewrite stalls | Each phase ships behind a flag. The beads adapter keeps existing workflows alive while the store lands. No phase deletes a working path before its replacement has run in production for a week. |
| Coder CLIs change their stream formats | Adapter conformance suite with recorded fixtures per CLI version; capability flags gate features instead of name checks. |
| Sandboxing slows agents or breaks tools | Sandbox is a per-project policy. Start with worktree isolation for trusted repos; containers only where tenants are untrusted. |
| Agents ignore the completion contract | Treat missing `RESULT.json` as failure with a clear comment back to the agent on retry; measure compliance per model and adjust instructions per adapter. |
| Multi-tenancy on one host is not real isolation | Say so in the security model. Offer one instance per tenant as the default commercial shape until container isolation is proven. |
| Solo maintainer bandwidth | Use fleet to build fleet: the mechanical parts of Phases 0, 1 and 5 decompose well into sonnet-class tasks once the design and interfaces are fixed by a person. |

Sources: full read of supervisor, runner, queue, config, schemas and coder base; four parallel subsystem reviews (core, adapters, server and UI, engineering hygiene) with file and line citations; test run on the current working tree; inspection of the live `~/.fleet` home.
