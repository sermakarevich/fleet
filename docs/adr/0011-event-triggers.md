# ADR 0011: Event triggers (start a task on a signal)

## Status

Accepted

Implemented by Triggers 1/8–7/8 (2026-09).

## Date

2026-09-09

## Context

A task can be started once (`bd create`), on a timer (schedules, ADR 0007),
or as a workflow step (ADR 0008). ADR 0009 reserved a third way, "started
on a signal", and called it a listener in the UI. Nothing implements it.

The first signal we need: **a task enters status `blocked`**. Today a
blocked task waits for a human (triage asks a question). We want fleet to
open an investigation task automatically, so that by the time the human
looks, a root-cause report and a recommended action are attached.

Design goals: one clear abstraction, one package, no new task lifecycle
(same principle as ADR 0007: a firing opens ONE ordinary bead).

## Decision

### Vocabulary

- **Source** — a kind of event fleet can watch. It is stateless: each poll
  returns the events that are true *right now* (for example "these beads
  are blocked"). Sources live in `fleet/triggers/sources/`, one file per
  kind, and are listed in the `SOURCES` registry.
- **Event** — one thing that happened, with a stable `key` (its identity
  for de-duplication) and a flat string `payload`.
- **Trigger** — a saved definition: which source (plus parameters), which
  task template to open (title, description, cwd, coder, model, priority,
  isolation, labels), and a policy (`max_open`, `cooldown_sec`).
- **Firing** — one trigger reacting to one event by opening one bead.
  Recorded append-only per trigger.

### Flow (one supervisor tick, `TRIGGER_TICK_SEC`)

For every enabled trigger: poll its source → for every event decide
(`open` or `skip`) → open a bead → append a firing. Pure decision in
`triggers/firing.py::decide`, one writer `fire()`, loop `fire_due()`,
mirroring `schedules/firing.py`.

### De-duplication and safety

- A trigger fires **at most once per event key** (the firings log is the
  memory). Skips for "already fired", "cooldown" and "max_open reached" are
  not persisted; the event is simply reconsidered next tick.
- `max_open` (default 2) caps how many not-yet-closed tasks opened by this
  trigger may exist; `cooldown_sec` (default 0) is the minimum gap between
  two firings of the same trigger.
- A bead opened by a trigger carries label `trigger:<id>` and metadata
  `fleet_trigger_id`, `fleet_trigger_event`, `fleet_trigger_n`, plus the
  usual `fleet_cwd`, `fleet_coder`, `fleet_model`, `fleet_isolation`.
- Sources must never emit events about beads that a trigger created
  (metadata `fleet_trigger_id` present). This prevents loops such as
  "investigate the investigator".

### Templates

Task title/description/cwd are templates. `{{event.<key>}}` fills a
payload value, `{{trigger.name}}` and `{{n}}` are also available. Unknown
placeholders stay as written (same rule as ADR 0010).

### First source: `blocked_task`

Emits one event per bead in status `blocked`, key `<task_id>@<blocked_at>`
(a re-block after an unblock is a new event). Payload: `task_id`, `title`,
`blocked_reason`, `blocked_at`, `cwd`, `task_dir`, `coder`, `model`,
`rounds`, `result_status`, `stderr_tail`. Parameter `fleet_blocked_only`
(default `true`) skips beads a human blocked by hand (no fleet
`blocked_reason` in `task.json`). Beads with an active `ignore_until` are
skipped.

### Storage

`$FLEET_HOME/triggers/<id>.json` (definition, written by CLI/API) and
`$FLEET_HOME/triggers/<id>.firings.jsonl` (append-only, one line per
firing, written by the supervisor). Owner: `triggers/store.py::TriggerStore`.
Path owner: `state/paths.py::triggers_root`.

### Layer

New package `fleet/triggers/` beside `schedules` (imports `core`, `state`,
`beads` only); imported by `orchestrator`, `serve`, `cli`. UI: the event
kind becomes the second `TriggerKind` in `ui/src/features/triggers`.

### Out of scope (follow-ups)

Workflow targets for triggers, push (webhook) sources, GitHub/Slack
sources. Push sources will be a Source that reads a spool folder the API
writes into, so the tick loop stays the only consumer.

## Consequences

- No new lifecycle: a firing is an ordinary bead (claim, worktree, merge,
  close, retry, triage all unchanged).
- Sources are stateless polls, so a supervisor restart loses nothing; the
  firings log is the only memory and it is append-only.
- A bad source cannot stop the others: `fire_due` isolates each trigger.
