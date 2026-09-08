# ADR 0003: Workers Are Step Pipelines Between the Orchestrator and the Coders

## Status

Accepted

## Date

2026-09-08

## Context

Fleet has no "worker" object. `orchestrator/runner.py::TaskRunner` equals
"one coder subprocess": it seeds artifact stubs, builds argv from the
coder, streams events, probes health, kills, and returns an outcome record.
`spawn.py` glues claim to runner and `reap.py` glues outcome to the bead.

The worker review of 2026-09-08 (see `docs/WORKER_CONTRACT.md` and the
beads in the "Worker n/9" chain) needs several units of work that are not
"one subprocess per bead":

- a continuation of a task that first compacts its own artifacts;
- a compaction job that calls a cheap model once, or no model at all;
- an observer that waits for child beads, validates the whole job and
  opens follow-ups;
- a job designer that researches, designs, creates child beads and then
  becomes the observer of those children;
- triage and garbage collection, which use no model.

Without a shared shape each of these becomes another module inside
`orchestrator/`, and the subprocess plumbing in `TaskRunner` gets copied.

## Decision

Introduce a `workers/` package as a layer between `orchestrator/` and
`coders/`. Three layers with fixed jobs:

- **Orchestrator** decides *when* and *which*: claim, lease, pick the
  worker, record the attempt, apply the outcome policy, reap. It never
  talks to a model and never interprets a worker's artifacts.
- **Worker** owns one attempt end to end: reads inputs from the task
  directory, runs zero or more model sessions plus Python and shell
  steps, writes artifacts and `RESULT.json`, returns one
  `TaskOutcomeRecord`.
- **Coder** stays "how to talk to one CLI": argv, env, event
  normalisation, hooks. Workers use coders, never the reverse.

Inside the worker layer there are two kinds of thing, and the words stay
distinct:

- A **step** is atomic: one purpose, takes a `StepContext`, returns a
  `StepResult`, knows nothing about beads status. Examples:
  `prepare_fresh`, `prepare_continue`, `compact`, `llm_session`,
  `summarize_attempt`, `merge_worktree`, `collect_children`,
  `validate_children`, `spawn_children`.
- A **worker** is a named list of steps. `FreshTask`, `ContinueTask`,
  `ContinueLargeTask`, `Observer`, `Job` are lists, written as Python
  literals in `workers/*.py`. Fresh and continue are therefore two
  workers that share every non-trivial step; the session code exists
  once, in the `llm_session` step.

Which worker runs is decided at two levels:

1. **Family, from the bead** (an input, never inferred): bead type
   `task`, `bug`, `feature` route to the task family; `epic` routes to
   the observer; the optional metadata field `fleet_worker` overrides.
   The orchestrator does one dictionary lookup in `workers/__init__.py`.
2. **Variant, from the task directory** (a pure function on the worker
   side): each family exposes `plan(ctx) -> Worker` that looks at its
   own artifacts and attempt history and picks the list to run. This is
   where `core/launch.plan_launch` (fresh, continue, needs compaction)
   and the job phases (research, design, spawn, observe) live.

Rules that follow:

- One attempt equals one worker run. Steps are recorded inside the
  attempt's `run.json`; a compaction step is the one exception that also
  gets its own attempt row so it shows in the timeline.
- Retries and blocking stay in the orchestrator (`core/outcome_policy`,
  later `core/retry_policy`). Workers never decide their own retries.
- A worker or step may create beads and add dependencies (the job
  designer does), but only the orchestrator changes the status of the
  bead being worked on.
- The `llm_session` step is the only place a concurrency slot is taken.
  Workers that wait take no slot.
- Compose in Python, not in config. No YAML pipelines, no step registry
  keyed by strings. Branching belongs in `plan`, which picks a different
  list, not inside a step.
- Keep steps coarse: a step earns its existence with its own test and a
  second user. Otherwise it is a function inside another step.
- The orchestrator never asks a model which worker to use.

## Consequences

- `TaskRunner` body moves to `workers/llm_session.py`; `spawn.py` shrinks
  to resolve coder, plan, select worker, record attempt, create task.
- `reap.py` keeps outcome policy but dispatches on the result kind so an
  observer result can use a job-level rule.
- New outcome `WAITING` (released, not counted, no retry) for workers that
  wake before their inputs are ready.
- Beads of type `epic` become runnable: the observer worker claims them
  once their children are closed or blocked.
- Package order becomes `core` < `state` < `beads` < `workers` <
  `orchestrator`, with `coders` beside `workers` (workers import coders).

## Affects

`src/fleet/workers/` (new), `src/fleet/orchestrator/{spawn,runner,reap,claim,stall}.py`,
`docs/ARCHITECTURE.md` target layout, `docs/WORKER_CONTRACT.md`,
beads chain "Worker n/n" (foundation bead inserted after Worker 1;
observer and job workers appended).
