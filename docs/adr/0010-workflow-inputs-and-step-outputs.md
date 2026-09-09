# ADR 0010: Workflow run inputs, step isolation, and step outputs

Date: 2026-09-09
Status: Proposed
Builds on: ADR 0008 (workflows), ADR 0007 (schedules), ADR 0006 (clean-code rules).

## Problem

Workflows (ADR 0008) are fixed text. An operator cannot pass a value when
starting a run — for example the URL of a paper to summarise — so every run
of a workflow does exactly the same thing. Two gaps follow:

1. **No run inputs.** Step titles and descriptions are templates, but there
   is no `{{inputs.<name>}}` placeholder and no way to supply values at run
   start, from the CLI, the API, or a schedule.
2. **No isolation opt-out per step.** Every worker runs in a git worktree
   (a separate copy of the repository, so parallel workers do not clash).
   A step that writes into an auto-synced tree such as `~/.ai` must run in
   place instead; today only a hardcoded repair bead can opt out (the
   `fleet_isolation: "none"` bead metadata the supervisor spawn path
   already honours).
3. **No step outputs.** A later step cannot use a value an earlier worker
   discovered (for example the folder a summary was written to), because
   all step text renders once at run start.

## Decision

Three small, serial work items (WI 1/3–3/3). WI 1/3 ships inputs and
isolation; WI 2/3 ships file-based step outputs with late rendering;
WI 3/3 ships the UI and an example workflow import.

### WI 1/3 — run inputs + step isolation (this bead)

- A workflow declares `inputs:` — a list of `name`, `description`,
  `required`, `default`. Names are slugs (`[a-z][a-z0-9_]*`), unique; a
  required input must not set a default.
- `start_run(..., inputs)` resolves the run map: operator values win,
  defaults fill the rest; unknown names and missing required values are a
  validation error. The resolved map is stored on the run.
- Step text gains `{{inputs.<name>}}`, rendered at run start like the
  other placeholders; unknown names stay as written.
- Steps and workflow defaults gain `isolation: "worktree" | "none" | None`
  (step wins, else defaults, else the supervisor default). The run engine
  stamps the effective value as the `fleet_isolation` bead metadata, which
  the supervisor spawn path already honours (`none` runs in place).
- Storage: `workflow_runs.inputs_json`. API: `POST
  /api/workflows/{id}/run` accepts an optional `{"inputs": {...}}` body
  (invalid inputs are 422). CLI: `fleet workflow run <ref> --input
  name=value` (repeatable); `run-show` prints inputs. Schedules targeting
  a workflow store an `inputs` map, pass it to `start_run` when firing,
  and refuse to save while a required input has no value.

### WI 2/3 — step outputs.json + late rendering of dependent stages

- Contract: a worker may write `outputs.json` in its task directory, a
  flat JSON (JavaScript Object Notation) object of string values.
- Templates gain `{{steps.<name>.outputs.<key>}}`. Steps of stage 1 render
  at run start as today; every later stage is created deferred with
  unrendered text and released (rendered, then un-deferred) once its
  dependencies close. A referenced key that is missing renders `""` and is
  recorded as an `outputs_missing` warning on the step run.
- Storage: `workflow_run_steps.outputs_json`, `released`, `warning`.

### WI 3/3 — UI run form, inputs/outputs in run detail, editor fields

- The workflows UI gets a run form (one field per declared input), shows
  inputs and step outputs/warnings in run detail, edits inputs/isolation
  in the workflow editor, and imports `docs/workflows/paper-summary.yaml`.

### Example workflow

`docs/workflows/paper-summary.yaml` exercises WI 1/3 (`inputs`,
`isolation: none`) and previews WI 2/3 (`{{steps.*.outputs.*}}`
placeholders, left as written until WI 2/3 lands). It must keep passing
`fleet workflow validate`.

## Implementation (3 beads, serial, coder opencode)

- [x] WI 1/3 — run inputs + step isolation (`fleet-vuyrf`)
- [x] WI 2/3 — step outputs.json + late rendering (`fleet-hw1w4`)
- [ ] WI 3/3 — UI run form, run detail, editor fields, import paper-summary
      (`fleet-hhbs3`)

## Consequences

- Positive: one workflow covers a family of runs (pass the paper URL at
  start); knowledge-base filing steps can run in place; later steps can
  consume earlier results without hand-pasted ids.
- Negative: inputs are strings only (no numbers/dates); late rendering
  means stage 2+ beads show raw placeholders until their dependencies
  close.
- Risk: a schedule saved with inputs keeps working if the workflow later
  declares that input required with no default — firing records a skip
  with the reason instead of opening a broken run.
