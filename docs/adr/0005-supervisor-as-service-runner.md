# ADR 0005: The Supervisor Is a Runner of Ordered Services

## Status

Proposed

## Date

2026-09-08

## Context

`orchestrator/supervisor.py::Supervisor` inherits six mixins
(`ClaimMixin, SpawnMixin, ReapMixin, StallMixin, LeasesMixin, TriageMixin`)
and its `run()` method reads like this:

```python
async def run(self) -> int:
    self._done = asyncio.Event()
    self._install_signal_handlers(asyncio.get_running_loop())

    check_ask_human_server(self._log)      # a module function
    self._sweep_orphan_worktrees()         # LeasesMixin
    self.reconcile_leases()                # LeasesMixin
    self._run_retention_gc()               # Supervisor itself

    bg = [asyncio.create_task(self._claim_and_spawn_loop(), ...), ... six loops ...]
    await self._done.wait()
    ...
```

A survey of the package (2026-09-08) shows why this is hard to read and
hard to change:

- **Mixed levels of abstraction in one method.** `run()` installs signal
  handlers (plumbing), calls one hand-picked health check (policy), runs
  three unrelated startup sweeps, and lists six loops by name. Adding a
  seventh check or loop means editing `run()` again.
- **No contract between the mixins.** The mixins share 18 `self._*`
  attributes with no declared owner. `reap.py` pops entries from four
  parallel dicts (`in_flight`, `in_flight_tasks`, `_runners`,
  `_attempt_n`) that `spawn.py` fills, and clears two sets
  (`_stall_warned`, `_stall_killed`) that `stall.py` owns. `stall.py`
  reads its own timer with `getattr(self, "_last_lease_reconcile", None)`
  because it cannot be sure `__init__` set it.
- **Loops hide other loops.** `_status_log_loop` also runs lease
  reconciliation and the triage tick on two extra hand-rolled timers.
  `docs/OVERVIEW.md` therefore describes a "triage loop" that does not
  exist as a loop.
- **Supervisor itself still does real work.** Retention garbage
  collection, config polling and the `.kill` sentinel poll live inline in
  `supervisor.py`, although `docs/ARCHITECTURE.md` line 70 says the file
  should only "wire the loops, own in_flight, handle signals".
- **Tests pay for it.** Fourteen test files construct `Supervisor` with
  the same boilerplate, then poke 41 private attributes
  (`s.config = ...`, `s._done = asyncio.Event()`, `s.in_flight = {...}`),
  and patch module constants by import path, so moving a loop to another
  file silently breaks a test.

We looked at Catalyst (https://github.com/catalyst-team/catalyst), a
PyTorch training framework, because it solved the same shape of problem:
one long-running loop with many optional concerns (metrics, checkpoints,
early stopping, schedulers) that must not be written into the loop body.
Catalyst's answers:

1. The `Runner` is a thin lifecycle driver. It fires named events
   (`on_experiment_start`, `on_epoch_start`, ... `on_epoch_end`,
   `on_exception`) through one dispatcher, `_run_event(name)`.
2. Every concern is a `Callback` with the same hook names. Callbacks are
   stored sorted by an `order` value (`CallbackOrder.Metric = 10`,
   `Optimizer = 40`, `Checkpoint = 50`, `External = 100`), so "metrics
   before checkpoint" is a number, not a comment.
3. The runner object is the single shared context. Callbacks read and
   write well-known attributes on it (`runner.batch_metrics`,
   `runner.epoch_metrics`) instead of holding private copies.
4. `Engine` (how to run on hardware) and `Logger` (where results go) are
   injected, so the loop never mentions a device or a log sink.
5. Small conditional wrappers (`ControlFlowCallback`) switch a callback
   on or off without editing it.

## Decision

Rebuild the supervisor as a **runner of ordered services** over one
shared **state** object. No mixins.

### 1. One state object, one owner per field

```python
@dataclass
class RunningWorker:            # replaces the four parallel dicts
    task: Task
    run: WorkerRun
    future: asyncio.Task[TaskOutcomeRecord]
    attempt_n: int
    started_at: datetime

@dataclass
class SupervisorState:          # the "runner" blackboard
    config: RuntimeConfig
    project_root: Path
    queue: Queue
    log: BoundLogger
    rate_gauge: RateGauge
    running: dict[str, RunningWorker] = field(default_factory=dict)
    paused_until: datetime | None = None
    shutting_down: bool = False
```

Rules: a field is written by exactly one service (documented on the
field). Other services only read. Per-service scratch data (the stall
warning set, the lease-notice dedupe set, the triage store) lives on the
service instance, never on the state.

### 2. Services, not mixins

```python
class ServiceOrder(IntEnum):
    Config = 0        # reloads config before anyone reads it this tick
    Leases = 10       # frees dead leases before claim looks at the queue
    Claim = 20
    Reap = 30
    Stall = 40
    Triage = 50
    Gc = 60
    Logging = 100     # observes everything else

class Service:
    order: ServiceOrder
    async def on_start(self, st: SupervisorState) -> None: ...
    async def on_stop(self, st: SupervisorState) -> None: ...
    async def on_worker_started(self, st, worker: RunningWorker) -> None: ...
    async def on_worker_finished(self, st, worker, outcome) -> None: ...
    async def on_config_reloaded(self, st, old, new) -> None: ...

class PeriodicService(Service):
    interval_sec: float
    async def tick(self, st: SupervisorState) -> None: ...
    # base class owns the loop: sleep, shutdown check, error guard, log
```

Each of today's loops becomes one small class in its own module with one
job and one cadence:

| Today | Becomes | Kind |
|---|---|---|
| `_config_poll_loop` (supervisor.py) | `ConfigReload` | periodic |
| `reconcile_leases` inside `_status_log_loop` | `LeaseReconcile` | periodic, own interval |
| `_claim_and_spawn_loop` | `Claim` | periodic |
| `_reap_loop` | `Reap` | event-driven (`wait FIRST_COMPLETED`) |
| stall detection inside `_log_status_snapshot` | `StallWatch` | periodic; owns `_warned/_killed` sets; clears them in `on_worker_finished` |
| `triage_tick_if_due` inside `_status_log_loop` | `Triage` | periodic, own interval |
| `_kill_poll_loop` | `KillSentinel` | periodic |
| `_gc_loop` + `_run_retention_gc` | `RetentionGc` | periodic; also runs in `on_start` |
| `_log_status_snapshot` | `StatusLog` | periodic, order Logging |
| `_run_pending_validations` (tail of claim loop) | `MergeValidation` | periodic |

The cross-mixin writes disappear: `Reap` removes the `RunningWorker`
and then emits `on_worker_finished`; `StallWatch` cleans its own sets in
that hook. `Spawn` stays a plain function module (`spawn.py`) called by
`Claim`, in the way `worktree.py` already is: it takes state, returns a
`RunningWorker`.

### 3. Startup checks are a list, not a call

```python
class StartupCheck(Protocol):
    name: str
    severity: Literal["warn", "abort"]
    def run(self, st: SupervisorState) -> str | None:   # None = ok, str = problem

STARTUP_CHECKS: list[StartupCheck] = [
    AskHumanServerImportable(),
    CoderBinaryOnPath(),
    BeadsReachable(),
]
```

`run_startup_checks(st, checks)` logs every result once and raises
`StartupAborted` if an `abort` check fails. Adding the tenth check is one
line in the list. Startup sweeps that change state (orphan worktrees,
lease reconcile, first gc pass) are not checks; they are the `on_start`
hook of the service that owns that concern.

### 4. The runner

```python
class Supervisor:
    def __init__(self, state: SupervisorState, services: list[Service], checks=STARTUP_CHECKS):
        self.state = state
        self.services = sorted(services, key=lambda s: s.order)
        self.checks = checks

    async def run(self) -> int:
        async with self._signals_to_shutdown():
            run_startup_checks(self.state, self.checks)
            await self._emit("on_start")
            await self._run_services_until_shutdown()
            await self._emit("on_stop")
        return 0

    async def _emit(self, event: str, *args) -> None:
        for svc in self.services:        # Catalyst's _run_event
            await getattr(svc, event)(self.state, *args)
```

`run()` now has one level of abstraction: lifecycle. Everything it names
is a lifecycle verb. `default_services(state)` in `orchestrator/__init__.py`
builds the production list; the CLI calls it. Shutdown (`_shutdown`) stays
in the runner because it is lifecycle, but it drains `state.running`
instead of three dicts.

### 5. What is *not* changed

- Retry policy (`core/retry_policy.py`), worker pipelines (ADR 0003),
  worktree functions, the beads adapter, the task directory contract
  (ADR 0004). Bodies of `_apply_decision`, `_validate_one`,
  `_reconcile_one_lease` and `_spawn_worker` move, they are not rewritten.
- The six cadences and every constant in `core/limits.py`. Behaviour is
  identical; only the shape of the code changes.
- Public CLI and HTTP API.

### 6. Tests

- One `make_supervisor(tmp_path, *, config=..., services=...)` factory in
  `tests/conftest.py` replaces the fourteen copies.
- Intervals are constructor parameters of each `PeriodicService`
  (default from `core/limits.py`), so tests pass `interval_sec=0.01`
  instead of patching module constants by path.
- A service is tested alone with a `SupervisorState` and no runner. The
  runner is tested with two fake services that record event order.

## Consequences

- `supervisor.py` shrinks to the runner (about 80 lines) plus shutdown.
  Every concern is one file with one class and one cadence; the file list
  of `orchestrator/` becomes the table of contents of the supervisor.
- Ownership of state is visible in the type: one `RunningWorker` record,
  one writer per `SupervisorState` field. The `paused_until` two-writer
  case (reap sets, claim clears) becomes explicit: `Reap` sets it,
  `Claim` reads it and clears it in its own tick; documented on the field.
- `docs/OVERVIEW.md` and `docs/PRODUCT_PLAN.md` become true again (triage
  is a loop; there are nine services, not "five loops").
- Cost: a one-time move of about 1,200 lines and a rewrite of the test
  fixtures. Import paths under `fleet.orchestrator.*` change; nothing
  outside the orchestrator imports the mixins today.
- Risk: services run concurrently, as the loops do now. The order value
  fixes the order of `on_start`/`on_stop`/event hooks, not the interleaving
  of ticks. That is the same guarantee we have today and it is stated in
  the `ServiceOrder` docstring.
- Trap to avoid: `Service` grows a hook per feature and becomes the new
  mixin. Rule: a hook is added only when a second service needs it; a
  service that needs private data keeps it on itself.

## Implementation plan (one bead each, in order)

1. **Foundation**: `orchestrator/service.py` (`Service`, `PeriodicService`,
   `ServiceOrder`, `_emit`), `orchestrator/state.py` (`SupervisorState`,
   `RunningWorker`), `orchestrator/checks.py` (`StartupCheck`, list,
   `run_startup_checks`), new thin `Supervisor`, `default_services()`,
   `make_supervisor` test factory. Old mixins still wired in through
   adapter services so the suite stays green.
2. **Config, StatusLog, KillSentinel, RetentionGc** move to services
   (the ones with no shared-state writes). Delete their loops from
   `supervisor.py`.
3. **Claim + Spawn → `Claim` service + `spawn.py` functions**, returning
   `RunningWorker`; `MergeValidation` split out of the claim loop.
4. **Reap → `Reap` service** emitting `on_worker_finished`; `StallWatch`
   owns its sets; `LeaseReconcile` and `Triage` get their own cadence.
   Delete `stall.py`'s composite loop and all mixin classes.
5. **Docs**: `ARCHITECTURE.md` target layout, `OVERVIEW.md` stale table
   row, `PRODUCT_PLAN.md` loop count; mark this ADR Accepted.

## Affects

`src/fleet/orchestrator/*` (all files), `src/fleet/cli/daemons.py`
(`run foreground` builds `SupervisorState` + `default_services()`),
`tests/orchestrator/*`, `tests/integration/conftest.py`,
`docs/ARCHITECTURE.md`, `docs/OVERVIEW.md`, `docs/PRODUCT_PLAN.md`.
