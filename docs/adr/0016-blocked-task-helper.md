# ADR 0016: Blocked-task helper

## Status

Accepted

This ADR supersedes ADR 0014, and removes the blocked-task investigator
trigger introduced by ADR 0011.

## Date

2026-09-25

## Context

Since ADR 0011, a fleet-auto-blocked task got an investigation bead from
the bundled `blocked-task-investigator` trigger, and triage
(`orchestrator/triage.py`, ADR 0014) asked the operator a question built
from a fixed option list — retry, retry with opus, edit and retry, close,
ignore(24h/forever) — reordered to put the investigation's recommended
action first. In practice the canned options rarely matched the real
cause of a block: a merge conflict, a missing dependency, or a design gap
each need a different, specific fix, not a choice among five generic
verbs. The operator still had to read the block reason and any
investigation report themselves, work out the real fix, and then, once
the option was picked, often do the actual repair by hand outside of
fleet — triage could apply "retry" but not "edit the repo to add the
missing package". The investigation report (`core/investigation.py`,
`state/investigation.py`) also only ever informed a question; it never
took action.

## Decision

Replace the fixed-option triage question and the investigator trigger
with a **helper**: a regular, priority-0 fleet task that investigates a
block, proposes fixes specific to what it found, and — once a human
approves one — carries out the fix itself.

- **One helper bead per block event.** `orchestrator/helper.py`
  (`HelperSpawn` service, `ServiceOrder.Helper`, the slot `Triage` used to
  occupy) ticks like the other periodic services, lists auto-blocked beads
  (`blocked_reason` set, no active ignore period — reusing the
  `ignore_active`/`ignore_until_24h` policy), and opens one helper bead
  per `(task_id, blocked_at)` pair (FR-01, FR-03, FR-04).
- **The helper is a normal LLM worker task**, claimed, run and reaped like
  any other bead — no new orchestrator-side Q&A plumbing. It investigates
  using the same evidence the old investigator used (task text, block
  reason, attempt history, logs, artifacts, repo state), then asks the
  human through the existing blocking `mcp__ask_human__ask_human_question`
  tool, already available to every worker. It waits for the answer,
  treats a free-text note as authoritative, and only then implements the
  approved fix — which may touch the target task, the target repo, other
  beads, or fleet's own code and config (FR-08 through FR-17).
- **Dedup per block event** via `helper_task_id`/`helper_blocked_at` on
  the target task's `task.json`: a live helper already tracking the
  current `blocked_at` blocks a second one; a re-block (new `blocked_at`)
  starts a fresh helper in the same chain (FR-01, FR-02, acceptance
  "re-block (edge)").
- **Chain linkage.** A helper's own bead carries labels
  `helps:<target-id>` and `chain:<root-id>`, plus `chain_root`/`chain_seq`
  metadata, where `root-id` is always the original blocked task, even
  when the immediate target is itself a helper. When a helper blocks, it
  is scanned exactly like any other blocked bead, so a helper for a
  helper (FR-19/FR-20) is created the same way a first helper is. Every
  helper is given every earlier report in its chain
  (`orchestrator/helper.py::chain_reports`, FR-22), so it can tell whether
  it is looking at a cause already seen.
- **Progress check.** Each helper's `artifacts/HELPER_REPORT.md`
  (`core/helper_report.py`) declares `Same as previous root cause:
  yes/no`. When a helper answers `yes`, the spawn service stops the chain
  instead of creating another helper, and asks the human one plain-text
  question summarising every report in the chain, rather than looping
  (FR-23, FR-24).
- **Config.** `helper_enabled` (default `true`) turns the whole feature
  off (FR-07); `helper_coder`/`helper_model` (default `claude`/`opus`)
  choose the helper's coder and model, separate from the general per-task
  default (FR-05).
- **Removal.** The `Triage` service, `core/triage_policy.py`'s rule
  engine (`Proposal`, `TriageRule`, the fixed option constants, proposal
  functions), the blocked-task investigator trigger, and their
  triage-only config (`triage_interval_minutes`,
  `triage_wait_for_investigation`, `triage_investigation_wait_minutes`)
  are gone (FR-25, FR-26). `ignore_active` and `ignore_until_24h` are kept
  — `beads/task_store.py`, `state/task_summary.py`,
  `triggers/sources/blocked_task.py` and now `helper.py` all depend on
  them — by moving them out of triage into `core/ignore_policy.py`.

## Consequences

- A blocked task's first response no longer follows a fixed triage
  cadence; it depends on the helper bead being claimed like any other
  priority-0 task, so it can arrive sooner under light load and later
  when workers are busy with other priority-0 work.
- The human sees fixes written for the specific block instead of a
  generic five-option menu, and approving one is enough to get the fix
  applied — the helper does the repair itself rather than leaving it to
  the operator.
- A chain that stops making progress asks exactly one summarising
  question instead of spawning helpers indefinitely.
- Helpers for helpers mean a single stubborn block can still produce a
  short chain of beads before the progress check stops it; this trades a
  few extra beads for not leaving a stuck helper unaddressed.
- This supersedes ADR 0014 (triage's investigation-aware question) and
  removes the ADR 0011 blocked-task investigator trigger; both are kept
  for history, not deleted.

## Related

ADR 0011 event triggers (introduced the investigator trigger this ADR
removes), ADR 0014 triage shows the investigation (superseded).
Requirements: `.sddw/blocked-tasks-help-worker/requirements.md`. Design:
`docs/design/blocked-task-helper.md`.
