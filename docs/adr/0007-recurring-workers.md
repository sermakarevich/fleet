# ADR 0007: Recurring Workers via Schedules

## Status

Proposed

## Date

2026-09-09

## Context

Fleet can only run a task because something called `bd create` (a human, the
chat intake, a follow-up). There is no way to say "every weekday at 09:00
triage the inbox" or "nightly: refresh the RAG index".
`docs/PRODUCT_PLAN.md` Phase 3 ("Scheduling and recurrence") asks for a
schedules table and a tick loop that instantiates tasks on cron triggers, with
overlap policy and time zone support, a schedules page, and a visible run
history.

The key design question is how recurrence relates to the existing queue.
Options considered:

1. **A new worker type with its own lifecycle** (a long-lived "recurring
   agent"). Rejected: it duplicates claim, worktree, merge, and close logic,
   and a second lifecycle doubles the crash-recovery surface.
2. **Schedules stored as beads in the beads database.** Rejected for now: it
   mixes configuration (the template + cron) with queue state, and the
   supervisor would need a second claim path. Plain files keep the first
   version small and inspectable.
3. **Recurrence as a thin layer on top of the existing queue** (chosen).
   When a schedule fires, the supervisor opens ONE ordinary bead from the
   template; from then on it is a normal task (claim, worktree, merge,
   close). No new worker type, no new task lifecycle.

Vocabulary for this chain: **schedule** (the saved template plus a cron
expression), **run** (one firing of a schedule, by cron or by hand),
**task** (the bead a run opens), **coder** (the CLI tool) vs **worker**
(the step list), **outcome** vs **decision** (per ADR 0006 rule 4).

## Decision

### Schedule

A schedule is a saved task template plus a 5-field cron expression and an
IANA (Internet Assigned Numbers Authority) time zone name (for example
`Europe/Warsaw`). When it is due, the supervisor's scheduler service opens
one ordinary bead from the template.

### Run

A run is one firing (cron or manual) and records: `scheduled_for` (the cron
minute it was due), `fired_at`, `trigger` (`cron` or `manual`), `task_id`
(null when skipped), `skipped` (true/false), `reason` (why skipped, or ""),
`n` (1-based run number).

### Overlap policy

Per schedule: `skip` (the default) — when the task opened by the previous
run is not yet `closed`, record a skipped run instead of opening another;
`queue` — always open a new task (beads simply queues it).

### Firing rules

`fleet/schedules/firing.py` holds the decision layer. `decide()` is pure:
disabled schedules wait; otherwise the baseline is the last cron run's
`scheduled_for` (or `created_at` when no run exists yet) and the first fire
after the baseline must be at or before now, else the schedule waits with
`next at <iso>`. Missed minutes coalesce to the LATEST one, so one outage
produces one make-up run. Overlap applies last: `skip` plus a previous task
still open records a skip (the reason names the status; the task id stays
with the caller), `queue` or a closed/gone previous task opens. `fire()` is
the one writer of cron and manual runs (`n = run_count + 1`); manual runs
always open with `scheduled_for = now`. A queue `BdError` is stored as a
skipped run (`bd error: ...`) and re-raised, so a broken queue does not
retry every tick. `fire_due()` ticks every enabled schedule, logs
`schedule_fired` / `schedule_skipped` / `schedule_fire_failed`, and never
lets one schedule stop the others.

### Catch-up policy

After downtime, at most ONE missed firing is made up (coalesced): the run's
`scheduled_for` is the LATEST due minute at or before now.

### Storage

One owner per file (ADR 0006 rule 1). Definitions live in
`$FLEET_HOME/schedules/<schedule_id>.json` (written by serve/CLI on
create/edit/delete); run history lives in
`$FLEET_HOME/schedules/<schedule_id>.runs.jsonl` (append-only, one line per
run, written by whoever fires: the supervisor's scheduler for cron runs,
the API/CLI for manual runs). Small lines plus `O_APPEND` (operating-system
append-only writes) keep concurrent appends whole. Deleting a schedule
removes both files. `runtime.toml` is NOT used (flat scalars only).

### Identification of created tasks

The bead gets labels `recurring` and `schedule:<schedule_id>`, plus metadata
`{"fleet_schedule_id": ..., "fleet_schedule_run": n, "fleet_cwd",
"fleet_coder", "fleet_model"}` (the last three mirror
`beads/create_args.py` so the supervisor's claim fallback sees them even if
`task.json` is not yet written).

### Layer

New package `fleet/schedules/` beside `beads` (imports `core`, `state`,
`beads` only); imported by `orchestrator`, `serve`, `cli`.

## Consequences

- Recurrence adds no task lifecycle: crash recovery, stall handling, and
  retries are the existing machinery.
- `skip` (the default) bounds concurrency at one open task per schedule;
  `queue` can pile up tasks when the worker is slower than the cadence —
  operators choose per schedule.
- Coalesced catch-up means a long outage produces one make-up run, not a
  flood; intermediate missed minutes are lost (visible as a gap in run
  history, not as skipped rows).
- Run history is append-only per schedule, so per-schedule history never
  needs migration; cross-schedule queries scan files (fine at this scale).

## Not now

Out of scope for this chain: the `replace` overlap policy, per-schedule
concurrency limits, jitter (randomized delay to spread load), second-level
cron, and schedules stored in beads/Dolt.

## Bead plan

1. Sched 1/6: ADR 0007 and `fleet/schedules` package — cron parser, Schedule model, JSON store (this bead; no supervisor or API behaviour changes).
2. Sched 2/6: firing policy in `fleet/schedules/firing.py` — pure due/overlap/catch-up decisions plus the one run writer (`decide`, `open_task`, `fire`, `fire_due`) shared by the supervisor tick and manual Run now (done).
3. Sched 3/6: `serve` API for schedules — create/edit/delete/enable/run-now plus run history endpoints.
4. Sched 4/6: CLI commands for schedules — create/edit/delete/list/runs/run-now.
5. Sched 5/6: UI schedules page with run history.
6. Sched 6/6: acceptance pass — docs, end-to-end test of a nightly schedule, flip this ADR to Accepted.

## Affects

`src/fleet/schedules/`, `src/fleet/orchestrator/`, `src/fleet/serve/`,
`src/fleet/cli/`, `src/fleet/ui/`, `tests/schedules/`,
`tests/test_layering.py`, `tests/orchestrator/test_layering.py`,
`docs/ARCHITECTURE.md`.
