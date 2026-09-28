# Fleet 2: flows instead of beads-backed workflows

Date: 2026-09-27
Status: Proposed (feature request + design)
Replaces, once done: ADR 0007 (schedules), 0008 (workflows), 0011 (triggers),
0013 (builders), 0016 (blocked-task helper as beads triage), and the `job`
worker family from ADR 0003.
Keeps: ADR 0001 (beads as an adapter), 0003 (a worker is a step pipeline),
0004 (task directory), 0005 (supervisor as service runner), 0006 (clean code).

## 1. Problem

Fleet started as "an orchestrator on top of beads": every piece of work is a
bead, and the supervisor runs beads. That was right for hand-added tasks. It
became a burden when we added schedules, triggers and workflows, because each
of them had to be *translated into beads and back*:

- A workflow step is a bead carrying three copies of its link to the run
  (labels, metadata, a `workflow_run_steps` table with a cached status).
- A per-unit step is a `job` worker that researches, designs, gets a gate,
  spawns child beads, and then polls them. Four phases, three journals.
- A step's `needs` becomes a `blocks` dependency, a job child becomes a
  `parent-child` dependency, and `bd show` returns both in one list. The bug
  fixed in `adf3e61` came from exactly that.
- A run keeps a private copy of the workflow definition inside SQLite, so
  editing and re-importing a workflow never reaches a running run (we patched
  `spec_json` by hand on 2026-09-26).
- Schedules and triggers are each a saved template plus a store, again
  separate from workflows, again opening beads.

The result: three definition stores (schedules, triggers, workflows), two
places where a definition can live (YAML file and SQLite), and about 9 000
lines of Python (`workflows/`, `triggers/`, `schedules/`, `workers/job.py`,
and the linking parts of `core/`, `state/`, `beads/`) whose only job is
carrying graph state through a task list that was not built to hold it.

Every new feature has to be threaded through all of that.

## 2. Goals

1. **Very few abstractions, each explainable in one sentence.**
2. **Definitions are files**, read from an ordered list of folders
   (built-in, public, private). Two machines with the same folders are the
   same fleet. There is no import step and no stale copy.
3. **Beads is used for one thing only**: tasks that a person or an agent adds
   by hand and wants to see in a shared task list.
4. **Runs are readable**: one folder per run on disk, plus two SQLite tables.
5. **Remove code**, not add: the migration ends with the beads-linking layer
   deleted.

Not goals: syncing runs between machines (beads keeps that job for hand-added
tasks; flow definitions sync via git), a general workflow engine, a new UI
framework.

## 3. The abstractions

There are five. Everything in fleet is one of them.

| Concept | One sentence | Lives in |
|---|---|---|
| **Step** | One coder launch: a prompt, a working directory, an outputs folder. | `pool/` |
| **Flow** | A YAML file: named steps, `needs` edges, inputs, and `on:` (what starts it). | `flows/` |
| **Run** | One execution of a flow: its inputs plus every step's outputs. | `runs/` |
| **Start** | Something that starts a run: a cron time, an event, or a person. | `supervisor/starts/` |
| **Pool** | The one place that executes steps under a concurrency cap, with retries and worktrees. | `pool/` |

What disappears as a *concept*: workflow, stage, schedule, trigger, job,
job child, builder, helper, worker family, task family. Each of them is
now either a flow or a start.

- A **scheduled worker** is a flow with one step and `on: cron`.
- A **triggered worker** is a flow with one step and `on: event`.
- A **workflow** is a flow with several steps.
- A **job** (one worker per unit) is a step with `for_each`.
- The **blocked-task helper** is a flow with `on: event: bead_blocked`.
- A **hand-added bead** is started by the built-in `bead.yaml` flow
  (`on: event: bead_ready`), which runs one step and closes the bead.

### 3.1 Step

A step is exactly what the worker contract already describes
(`docs/WORKER_CONTRACT.md`): fleet makes a directory, writes `prompt.md`,
`STATE.md` and an empty `outputs/`, launches a coder there, and reads
`RESULT.json` and `outputs/outputs.json` when the coder exits. Nothing
changes for coders or templates.

A step has two kinds:

- `coder` (default): run a coder with the rendered prompt.
- `human`: ask one question through `ask_human`, store the answer as the
  step's outputs. This replaces `job_gate` and the "confirm with ask_human at
  the end" prompt rules.

Step fields: `name`, `kind`, `needs`, `prompt`, `coder`, `model`, `cwd`,
`isolation`, `retries`, `for_each`, `key`, `after`, `parallel`, `skip_if`
(a rendered condition; a skipped step counts as finished with empty
outputs), `outputs` (declared keys, for templates and validation). Every
field except `name`, `kind` and `needs` may be a template.

### 3.2 Flow

A flow is one YAML file. Its name is the file name. Example, shortened
(the full autocode flow is `example-autocode.yaml` next to this file):

```yaml
fleet_flow: 2
description: Autonomous coding of one feature.
on:
  manual: true                 # started from CLI / UI
inputs:
  repo:    {required: true}
  feature: {required: true}
defaults: {coder: opencode, model: opencode-go/muse-spark-1.3-contributor, isolation: worktree}

steps:
  requirements:
    prompt: |
      Turn the spec into testable requirements. Write outputs/outputs.json
      with {"units": ["M1", "M2", "R1", ...]}.
    outputs: [units]

  failures:
    needs: [requirements]
    for_each: "{{ steps.requirements.outputs.units }}"   # one step run per unit
    parallel: true
    prompt: |
      Write docs/{{ inputs.feature }}/failures/{{ item }}.md. Do not commit.

  commit-failures:
    needs: [failures]
    prompt: Commit docs/{{ inputs.feature }}/failures/*.md in one commit.

  approve:
    needs: [commit-failures]
    kind: human
    prompt: Failure modes are written. Continue to unit tests?
```

Rules:

- `needs` is the only edge. A step is ready when every step it needs has
  finished. There are no stages; stages were only a way to say "these run
  together", which `needs` already says.
- `for_each` is the one dynamic construct. When the step becomes ready, the
  list is rendered from earlier outputs and the step runs once per item, with
  `{{ item }}` and `{{ index }}` in its templates. A step that `needs` a
  `for_each` step waits for all items. `{{ steps.failures.items }}` gives
  the list of per-item outputs. This replaces the `job` worker (research,
  design, gate, spawn, observe) and the `chunking` builder.

  The earlier step decides **how many** copies run, **with what**, and **in
  what order** (operator decision, 2026-09-27):
  - Items may be objects. `{{ item.unit }}` in the prompt; `coder`, `model`,
    `cwd`, `isolation`, `retries` may be templates over `item`, so step 1 can
    give a hard unit a bigger model.
  - `parallel` may be a template, e.g.
    `parallel: "{{ steps.requirements.outputs.parallel }}"`, so step 1 picks
    "all at once" or "one after another" for the whole list.
  - Finer than that, `after: "{{ item.after }}"` makes one item wait for
    other items of the same step (a name or list of names from a declared
    `key: "{{ item.unit }}"`). Items without `after` start right away. This
    gives a dependency graph *between items*: M1 and M2 run together, R3
    waits for M1.
  - What stays fixed is the set of steps in the file. Step 1 cannot add a
    step with a new prompt; that is the job worker we are removing, and it
    is what made runs hard to follow. The UI can draw the graph before the
    run starts and fill in the item count as it goes.

  Example: step 1 writes
  `{"units": [{"unit": "M1"}, {"unit": "M2"}, {"unit": "R3", "after": ["M1"], "model": "opus"}], "parallel": true}`
  and step 2 declares
  ```yaml
  for_each: "{{ steps.requirements.outputs.units }}"
  key:      "{{ item.unit }}"
  after:    "{{ item.after | default([]) }}"
  parallel: "{{ steps.requirements.outputs.parallel }}"
  model:    "{{ item.model | default(defaults.model) }}"
  ```
- Templates use `{{ inputs.x }}`, `{{ steps.x.outputs.y }}`, `{{ item }}`,
  `{{ run.id }}`, `{{ run.date }}`. They render into `prompt` **and** `cwd`
  (today `cwd` is not rendered, which forced every autocode step to `cd`).
- `on:` declares starts:
  ```yaml
  on:
    cron: {expr: "0 7 * * 1-5", tz: Europe/Berlin}
    event: {source: bead_blocked}
    manual: true
  ```
  A flow can have several. `enabled: false` turns the whole flow off.

### 3.3 Folders: built-in, public, private

`~/.fleet/config.toml`:

```toml
[flows]
folders = [
  "builtin",                        # shipped with fleet: bead.yaml, helper.yaml
  "/Users/sergii/git/fleet-flows",  # public repo, shared between instances
  "/Users/sergii/.fleet/flows",     # private, this machine only
]
```

Fleet reads every `*.yaml` in every folder, in order. A later folder with the
same file name **replaces** the earlier one; a later `<name>.override.yaml`
with only some keys **merges** over it (this is how a private folder turns
`enabled: false` or changes a cron time without copying the whole flow).
Files are re-read on change (the supervisor already has `config_reload`).
There is no `fleet workflow import`, no `workflows` table.

Portability: clone the public repo, copy the private folder, point
`config.toml` at both. Done.

### 3.4 Run

Starting a flow:

1. `runs/` copies the flow file into the run folder as `flow.yaml`. That is the
   run's frozen definition — a plain file you can read and, if you must,
   edit. It replaces `spec_json`.
2. It inserts one row in `runs` and, as steps become ready, rows in
   `step_runs`. `for_each` adds one `step_runs` row per item
   (`step_name`, `item_index`).
3. Each step run's directory is `~/.fleet/runs/<run>/<step>[/<index>]/`,
   which is today's task directory unchanged.

```sql
runs      (id, flow, started_at, finished_at, status, inputs_json)
step_runs (run_id, step, item_index, status, attempt, started_at, finished_at)
```

Status is never cached from somewhere else; these rows *are* the status.
The run's state for templates is inputs plus the `outputs.json` files on
disk. Crash recovery is "find step runs in `running` with no live process,
mark them for retry", which the pool's lease logic already does.

### 3.5 Start

`supervisor/starts/` has one small module per start kind:

- `cron.py`: every tick, for every flow with `on.cron`, start a run if due
  (today's `schedules/cron.py`, minus the store).
- `events.py`: every tick, ask each **source** for events, start a run per
  new event, remember the event key so it fires once (today's
  `triggers/sources/*`, minus the store). Sources: `bead_ready`,
  `bead_blocked`, `tweet` (from `tweet_watch`), and later others.
- `manual.py`: `fleet run <flow> --input k=v` and the UI button.

The `bead_ready` source is the whole beads integration on the input side:
it turns a ready bead into a run of the built-in `bead.yaml` flow, with the
bead's title, description, coder, model and isolation as inputs. When that
run finishes, the same module closes or blocks the bead. Beads is thus a
*source* and a *sink*, in one file, and nothing else in fleet knows about
`bd`.

### 3.6 Pool

The pool is today's supervisor loop minus queue logic: pick ready step runs
across all runs, respect `max_concurrent` and per-coder rate gauges, create
the worktree when `isolation: worktree`, launch the coder, watch it, reap it,
retry up to `retries`, record attempts. Modules keep their names
(`claim`, `spawn`, `reap`, `leases`, `stall`, `worktree`, `rate_gauge`,
`retry_policy`) but read from `step_runs` instead of beads.

The pool does not know what a flow is. It gets a step run id, a rendered
prompt, a directory and launch options.

## 4. Package layout (imports point down only)

```
fleet/
  cli/           fleet run <flow>, fleet flows, fleet runs, fleet serve
  serve/         web: Flows page, Runs page, Run page (steps, items, attempts)
  supervisor/    the tick loop: starts → runs.advance() → pool.fill()
    starts/      cron.py, events.py, manual.py
      sources/   bead_ready.py, bead_blocked.py, tweet.py
  flows/         model.py, folders.py (read+override), graph.py (ready steps,
                 for_each expansion), templates.py
  runs/          store.py (two tables), run_dir.py, state.py (inputs+outputs)
  pool/          claim.py, spawn.py, reap.py, leases.py, retry_policy.py,
                 worktree.py, rate_gauge.py, prompt.py, result.py
    coders/      unchanged
  beads/         client.py only; used solely by supervisor/starts/sources/bead_*.py
  integrations/  ask_human, telegram, mcp_servers — unchanged
  templates/     unchanged
```

`supervisor` imports `flows`, `runs`, `pool`. `runs` imports `flows`
(the model). `pool` imports `coders`. `flows` imports nothing of fleet.
`beads` is imported by one folder. Every `__init__.py` is empty except for
the layer docstring.

## 5. What gets deleted

| Today | Lines (approx.) | Fate |
|---|---|---|
| `workflows/` (model, planning, runs, store, templates, yaml_io, builtins, builders) | 4 900 | → `flows/` + `runs/`, about a quarter of the size |
| `triggers/` (model, store, firing, render) | 950 | → `starts/events.py`; sources move as they are |
| `schedules/` (model, store, firing) | ~1 100 | → `starts/cron.py` |
| `workers/job.py`, `observe.py`, `core/job_*.py`, `state/spawn_journal.py` | ~1 700 | deleted; `for_each` |
| `workers/research*.py`, research templates | ~600 | become `research.yaml` in built-in flows |
| `orchestrator/helper.py`, `triggers/sources/blocked_task.py` triage | ~400 | `helper.yaml` flow with `on: event: bead_blocked` |
| `beads/queue.py`, `task_store.py`, `reconcile.py`, `status_cache.py`, labels/metadata in `planning.py` | ~1 200 | deleted; `client.py` stays |
| `workflow_run_steps`, `workflows`, `workflow_runs`, schedule and trigger tables | | replaced by `runs`, `step_runs` |
| UI: Schedules, Triggers, Workflows, Tasks pages | | → Flows, Runs |

## 6. Decisions to confirm

1. **Runs stay local to one machine.** Flow definitions sync through git;
   hand-added tasks still sync through beads/Dolt. Nothing else syncs.
2. **Parallel `for_each` items share the step's `cwd` unless
   `isolation: worktree`.** Flow authors choose: shared checkout with
   "never commit" prompts plus a commit step, or one worktree per item and a
   merge step. Fleet does not merge for them.
3. **Two step kinds only**, `coder` and `human`. A `shell` kind (run a
   command, no coder) is an obvious later addition and is left out on
   purpose. A sub-flow step is left out; nest with `for_each` first.
4. **The bead flow is the compatibility layer.** `bd create` keeps working
   exactly as today. Bead metadata keys (`fleet_coder`, `fleet_model`,
   `fleet_isolation`) become inputs of `bead.yaml`. All other metadata keys
   are dropped.

## 7. Migration, in order, each step shippable

1. **Folders.** Add `flows.folders` to config and `flows/folders.py`. Load
   the existing workflow YAML from folders instead of the `workflows` table.
   Nothing else changes; the import command is removed. Low risk, useful
   alone.
2. **Runs and pool on `step_runs`.** New `runs/` store and `flows/graph.py`.
   The supervisor advances runs and hands ready step runs to the existing
   spawn/reap code through a thin adapter, next to the beads claim loop.
   Move `autocode` and `summarise` to the new format; they no longer create
   beads.
3. **Starts.** `on: cron` and `on: event` in flow files; the `bead_ready`
   source with `bead.yaml`. Remove the beads claim loop, schedule and
   trigger stores and their UI pages.
4. **Delete** the `job` worker, builders, research worker, helper triage,
   `workflows/`, `beads/queue.py` and friends. Rewrite the Runs UI on the two
   tables.

Each step ends with `uv run pytest`, a supervisor restart, and one real flow
run. The current `autocode/tweet_watch` run finishes on the old code first;
step 2 is the first one that touches the supervisor.

## 8. Open questions

- Should a private `*.override.yaml` be able to change `prompt`, or only
  `on`, `enabled`, `defaults` and `inputs`? Prompt overrides make two
  instances behave differently in ways that are hard to see.
- Do we keep `fleet task <id>` commands for beads-started runs, or is
  `fleet runs` with a `bead:` filter enough?
- `for_each` over a list produced by a `human` step (a person types the
  units) is allowed by the rules above. Is that a feature or a foot-gun?
