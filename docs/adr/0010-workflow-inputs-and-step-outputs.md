# ADR 0010: Workflow run inputs and step outputs

Date: 2026-09-09
Status: Proposed
Builds on: ADR 0008 (workflows), ADR 0004 (task directory artifacts),
ADR 0007 (schedules).

## Problem

ADR 0008 workflows are fixed text. The only placeholders are run metadata
(`{{run.date}}`, `{{steps.<name>.task_id}}`, ...). Two things an operator
needs are impossible:

1. **Inputs at start.** "Summarise *this* paper" needs a URL typed when the
   run is started. Today the only way is export → edit YAML → import.
2. **Values found by an earlier step.** The step that summarises a paper
   decides the folder name; the Slack and vault steps need that name. Text is
   rendered once when the run starts, before any worker has run, so a later
   step can only quote the earlier *task id*, never what that task found.

Also, steps that write to a non-code repository (the `~/.ai` knowledge base,
which auto-syncs) must run without a git worktree, and `Step` has no way to
say so; the per-bead `fleet_isolation` metadata exists but workflows do not
set it.

## Decision

### Inputs

A workflow declares `inputs`, a list of named values asked for when a run is
started:

```yaml
inputs:
  - name: url
    description: Link to the paper, video, article or repository
    required: true
  - name: channel
    default: "#ai-papers"
```

- Names are slugs (`[a-z][a-z0-9_]*`), unique inside the workflow.
- Starting a run takes a `{name: value}` map (API body, CLI `--input name=value`,
  UI form). Missing required inputs or unknown names fail validation before
  any bead is opened. Defaults fill the rest.
- Templates gain `{{inputs.<name>}}`. Values are stored on the run
  (`workflow_runs.inputs_json`) so history shows what a run was started with.
- Schedules that target a workflow may carry a fixed `inputs` map; a workflow
  with a required input and no schedule value cannot be scheduled.

### Step outputs

A worker publishes values for later steps by writing `outputs.json` in its
task directory: a flat object of string values (`{"paper_dir": "/…/papers/X"}`).
The worker instruction template tells coders how (an `outputs.json` note in
`coder_header.md.tmpl` and `docs/WORKER_CONTRACT.md`). Fleet reads the file
when the task closes; missing file means no outputs.

Templates gain `{{steps.<name>.outputs.<key>}}`.

### Late rendering

Because outputs exist only after a step closes, text that references them
cannot be rendered at start. The engine therefore:

1. Renders and opens stage-1 beads exactly as today.
2. Opens every later bead **deferred** (`bd create --defer`) with its final
   title/description still containing `{{steps…outputs…}}` placeholders, and
   dependencies wired at creation as today. Deferred beads are never claimed.
3. The existing periodic `workflow_refresh` service, on each pass, finds
   step runs whose dependencies are all `closed`, reads their `outputs.json`
   (cached on `workflow_run_steps.outputs_json`), renders the text, updates the
   bead (`bd update --title/--description`) and un-defers it.

Steps whose text references no outputs may still be opened deferred: one code
path, no special case. `{{inputs.*}}` is rendered at start for stage 1 and at
release time for later stages, from the same run inputs.

A referenced output that is missing when the step is released renders to the
empty string and the step run records a warning (`outputs_missing`), visible
in the run detail; the run does not stop.

### Step isolation

`Step` and `defaults` gain `isolation: worktree | none`. The engine passes it
as `fleet_isolation` metadata, the same key the `fleet bd create` wrapper uses.

### Surface

- API: `POST /api/workflows/{id}/run` accepts `{"inputs": {…}}`; run views
  include `inputs` and per-step `outputs`; workflow view includes `inputs`.
- CLI: `fleet workflow run <ref> --input url=… [--input k=v…]`;
  `fleet workflow run-show` prints inputs and outputs.
- UI: the Run button opens a form when the workflow declares inputs
  (required marker, default prefilled, description as help text). Run detail
  shows inputs at the top and each step's outputs on its card. The workflow
  editor gets an Inputs section and an isolation selector.

## Implementation plan (3 beads, serial, fleet's own code: restart the
supervisor and server between beads)

- [ ] WI 1/3 — model + inputs: `inputs` and `isolation` in model, validation,
      YAML (round-trip), templates `{{inputs.*}}`, `start_run(inputs=…)`,
      `inputs_json` migration, API body, CLI `--input`, regenerated UI types.
- [ ] WI 2/3 — outputs + late rendering: `outputs.json` contract in the worker
      template and docs, deferred creation of later stages, release in
      `workflow_refresh`, `outputs_json` on step runs, `{{steps.*.outputs.*}}`.
- [ ] WI 3/3 — UI: run form, inputs/outputs in run detail, editor sections;
      import `docs/workflows/paper-summary.yaml` with `--replace`; ADR
      Accepted.

## Consequences

- Positive: workflows become reusable recipes with parameters; data flows
  between steps without prompt conventions; the queue still does all
  sequencing.
- Negative: later-stage beads sit `deferred` instead of `open`, so
  `bd ready` and the Beads page show them differently from today; the run
  detail is the place to read a run. Release depends on the refresh service
  cadence (seconds, not minutes).
- Risk: `bd update --description` on a released bead races with a claim only
  if the bead is not deferred; the design keeps it deferred until after the
  update, so no window exists.
