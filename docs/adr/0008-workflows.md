# ADR 0008: Workflows — ordered stages of workers on top of the beads queue

Date: 2026-09-09
Status: Proposed (WF 8/8 flips it to Accepted)
Builds on: ADR 0001 (beads as adapter), ADR 0003 (workers as step pipelines),
ADR 0005 (supervisor as service runner), ADR 0006 (clean-code rules),
ADR 0007 (recurring workers / schedules).

## Problem

A fleet task is one worker doing one job. Real work is a sequence: "collect →
implement (three parts in parallel) → review → write docs". Today an operator
builds that by hand with `bd create --deps`, remembers the ids, and watches the
Tasks page. There is no saved definition, no history of one "batch" as a whole,
and no way to run the same sequence again or on a timer.

## Decision

Add a **workflow**: a saved, named definition of workers arranged in **stages**.
Running a workflow opens ordinary beads, one per step, wired with beads
dependencies. Nothing new is executed by fleet itself: the existing supervisor,
claim loop, worktrees and merge path do all the work. A workflow is therefore a
*planner* for the queue, never a second executor.

### Vocabulary

- **Workflow** — the saved definition (name, stages, defaults).
- **Stage** — an ordered group of steps. All steps in a stage may run in
  parallel; a stage starts when the previous stage is complete.
- **Step** — one worker's task template (title, description, cwd, coder, model,
  priority). Steps have a unique `name` (slug) inside their workflow.
- **Run** — one execution of a workflow (manual or from a schedule). It records
  which bead each step opened and how the whole thing ended.
- **Step run** — one step inside one run: its task id and the last known task
  status.

### Parallelism model

Sequential and parallel arrangement is expressed by stages alone, so the UI can
show a workflow as columns (stages) of cards (steps):

```
stage 1        stage 2                stage 3
[collect] ---> [impl-api]  --------> [review]
           \-> [impl-ui]   ----/
           \-> [impl-docs] ---/
```

Rules:

1. A step with no `needs` depends on **every** step of the previous stage
   (fan-in). Steps of stage 1 have no dependencies.
2. A step may list `needs: [step names]` from **earlier** stages to depend on a
   subset only (a "fast lane" through a stage). `needs` may not point into the
   same or a later stage; that is a validation error.
3. Steps in one stage never depend on each other. Two steps that must be
   sequential go into two stages.

This covers fan-out, fan-in, straight sequences and mixed shapes while staying
drawable and explainable to a non-expert.

### Running

`start_run(workflow)` creates all step beads **at once**, stage by stage, each
with `--deps` set to the beads of the steps it depends on (dependencies are
passed at creation time; see the fleet task-filing notes on the `--deps` race).
Beads then does the sequencing: the supervisor only ever claims ready beads.
Consequences:

- The whole graph is visible on the Beads page the moment a run starts.
- Cancelling a run means closing the not-yet-started beads with a reason and
  killing the running ones through the same path as the task "kill" action.
- Later steps may reference earlier steps' task ids in their text through
  templates (`{{steps.impl-api.task_id}}`), because all ids exist at start.

Templates available in step title/description: `{{workflow.name}}`,
`{{run.id}}`, `{{run.n}}`, `{{run.date}}` (YYYY-MM-DD UTC), `{{step.name}}`,
`{{steps.<name>.task_id}}`. Unknown placeholders are left as written.

Each created bead carries labels `workflow:<workflow_id>,run:<run_id>,step:<name>`
and metadata `fleet_workflow_id`, `fleet_workflow_run`, `fleet_workflow_step`,
plus `fleet_cwd` / `fleet_coder` / `fleet_model` when set (same keys the
`fleet bd create` wrapper uses). One `bd list --metadata-field
fleet_workflow_run=<run_id>` call fetches every task of a run.

### Run status (derived, never hand-edited)

| step task status | step run |
|------------------|----------|
| closed           | done     |
| blocked          | attention (a human is needed) |
| open / deferred  | waiting  |
| in_progress      | running  |

Run status: `cancelled` if cancelled; else `succeeded` when every step is done;
else `attention` when any step is blocked; else `running`. `finished_at` is set
once when the run leaves `running`. A periodic supervisor service refreshes
step statuses so history is correct even when nobody opens the UI.

### Storage: a small SQLite database

`$FLEET_HOME/workflows.db` (SQLite, WAL mode, ordered migrations under
`PRAGMA user_version`, one connection per thread — the same pattern as the
ask_human question store). Tables:

- `workflows(id, name UNIQUE, description, spec_json, created_at, updated_at)`
- `workflow_runs(id, workflow_id, n, trigger, schedule_id, spec_json, status,
  reason, started_at, finished_at)` — `spec_json` is the definition frozen at
  start so editing a workflow never rewrites history.
- `workflow_run_steps(run_id, step_name, stage_index, task_id, task_status,
  updated_at, PRIMARY KEY(run_id, step_name))`.

A database rather than JSON files because runs × steps grow without bound and
the UI needs filtering and paging (past runs per workflow, runs per schedule).
Schedules (ADR 0007) keep their JSON files; moving them is out of scope.

### Import and export as YAML

`fleet_workflow: 1` documents, one workflow per file:

```yaml
fleet_workflow: 1
name: nightly-quality
description: Lint, test and summarise
defaults: {cwd: /Users/me/git/app, coder: opencode, model: qwen3.6:latest, priority: 2}
stages:
  - name: checks
    steps:
      - name: lint
        title: "Lint {{workflow.name}} ({{run.date}})"
        description: Run ruff and fix what it reports.
      - name: tests
        title: Run the test suite
        description: uv run pytest -q; fix failures.
        coder: claude
        model: sonnet
  - name: report
    steps:
      - name: summary
        title: Summarise the night
        description: "Read tasks {{steps.lint.task_id}} and {{steps.tests.task_id}} and write a summary."
        needs: [lint, tests]   # optional here: same as the default fan-in
```

Export writes exactly this shape (no ids or timestamps unless asked). Import
validates the document (schema, unique names, `needs` rules, known coder) and
creates a new workflow, or replaces an existing one when told to. Same code path
for the API, the CLI and the UI upload/download buttons.

### Recurring workflows

ADR 0007 schedules gain a **target**: `task` (today's behaviour) or `workflow`
(`workflow_id`). When a workflow schedule is due, the scheduler starts a run
instead of opening one bead; the schedule's `overlap` policy compares against
the previous **run** status (`skip` while it is still `running`/`attention`).
The UI gets a separate "recurring" tab listing workflow schedules with their
next fire times and past runs; the existing "schedules" tab keeps single-task
schedules.

### Layering

`workflows` sits beside `schedules`: `core < state < beads = schedules =
workflows < workers < orchestrator | serve | cli`. `workflows` imports `core`,
`state`, `beads` only. `schedules` may import `workflows` (a schedule can
target a workflow); `workflows` never imports `schedules`.

## Implementation plan (8 beads, serial, coder opencode)

- [ ] WF 1/8 — `fleet/workflows` package: model, validation, templates, SQLite
      store, YAML import/export. `pyyaml` dependency.
- [ ] WF 2/8 — run engine: `start_run`, `refresh_run`, `cancel_run` (pure
      planning + one queue-calling function).
- [ ] WF 3/8 — `/api/workflows` REST routes, pydantic models, regenerated UI
      types and `api.ts`.
- [ ] WF 4/8 — UI "workflows" tab: list, stage/step editor, import/export.
- [ ] WF 5/8 — UI run monitor: runs list, run detail as a stage grid, cancel.
- [ ] WF 6/8 — recurring: schedule `target`, scheduler fires runs, periodic
      `workflow_refresh` service, `/api/schedules` extension.
- [ ] WF 7/8 — UI "recurring" tab for workflow schedules.
- [ ] WF 8/8 — `fleet workflow` CLI, docs, this ADR Accepted.

## Consequences

- Positive: reuses every existing guarantee (worktrees, merge, retries, kill,
  leases). No new process, no new worker type. A run is inspectable with
  today's tools (`bd show`, Tasks page).
- Negative: a run occupies queue slots for beads that cannot start yet (they are
  `open` but dep-blocked; `bd ready` excludes them, so no slot is actually
  consumed). Editing a workflow does not change runs already started.
- Risk: the `bd create --deps` timing gap could let the supervisor claim a
  dependent bead before its dependency row lands. The engine creates beads in
  stage order so the window is one bead at a time; if it is observed in
  practice, create with `--defer` and un-defer after wiring.
