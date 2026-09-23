# ADR 0013: Workflow builders — expand a saved definition into stages at run start

## Status

Accepted

## Date

2026-09-14

## Context

A plain workflow (ADR 0008) is a fixed graph of stages saved in YAML: every
step is known when the file is imported. Some workflows only know their shape
once a run starts — "one step per chunk" cannot be written as static stages
because the number of chunks depends on the run's input.

The first workflow that needs this is `summary_get` (the `ai:summary:get`
recipe): fetch the source behind a URL (a video transcript, an article page,
a PDF), split its text into chunks, and plan one wiki-page worker per chunk,
followed by digest/summary, explainer/questions/critical-thinking/connections,
and index steps. The fetch tools (`yt` for YouTube, `x` for X/Twitter,
`pdftotext` for arXiv/PDF, HTML extraction otherwise) and the chunk count are
only known at run start.

## Decision

- A workflow carries an optional `builder` name alongside its stages. A
  builder workflow names a builder and saves no stages; a plain workflow has
  stages and no builder. Validation rejects unknown builder names and a
  definition with neither stages nor a builder.
- Builders are registered by name in `fleet.workflows.builders`
  (`BUILDER_MODULES`; today only `summary_get`). The registry maps the name
  to its module so model validation can reject unknown names without
  importing builder code (each builder module is imported on first use only).
- `start_run` expands the saved definition through the builder with
  `BuildContext(run_id, fleet_home, now, inputs)` — the run identity, the
  fleet home, the start time, and the resolved run inputs. The builder
  returns the workflow with concrete stages; the expanded, builder-less spec
  (builder set to none) is frozen on the run, so editing the definition
  never rewrites history (same rule as ADR 0008).
- Builder scratch lives under `$FLEET_HOME/workflows/<builder>/<run_id>/`
  (`BuildContext.work_dir`): the fetched source text, one file per chunk,
  and a JSON chunk manifest. Later step descriptions reference these
  absolute paths literally at build time.
- Builder errors (missing input, fetch failure, bad chunk size) surface as
  `WorkflowInvalid` naming the builder (`builder <name>: <reason>`), through
  the same path as any validation error in the CLI, the API, and the
  Telegram `/workflow` + `/summary` commands.

## Consequences

- Fetch happens at run start, synchronously, inside the caller: `start_run`
  blocks while the builder downloads and chunks the source. A slow or
  failing source fails the run before any bead opens.
- Only `summary_get` exists today; adding a builder is one registry row plus
  a module exposing `build(workflow, ctx)`. Builder modules may import
  `core`, `state`, `beads`, and `workflows.model` only.
- Stages of a builder workflow are visible per run (the frozen expanded
  spec), not on the definition: `fleet workflow show` prints the saved
  definition (builder name, no stages); the concrete stage grid appears on
  the run detail once the run starts.

## Amendment 2026-09-23

The `summary_get` builder was renamed to `summarise` (module, registry key,
definition name, and saved YAML); body text above keeps the old name as
written. The one-shot `scripts/recover_workflow_runs.py` still reads the
pre-rename `workflows/summary_get/<run_id>` work dirs.
