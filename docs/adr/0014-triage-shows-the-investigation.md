# ADR 0014: Triage shows the blocked-task investigation

## Status

Accepted

## Date

2026-09-21

## Context

Since ADR 0011, the bundled `blocked-task-investigator` trigger has opened
one investigation bead (one task row in the beads task queue) per
fleet-blocked task, and its worker writes a markdown report about why the
task blocked. Nothing read that report back. The triage question — the
ask_human (the operator-question store the supervisor posts questions to,
surfaced in the Inbox tab and over Telegram, the chat-notification
integration) question the operator answers — was a block reason plus a
fixed list of options with no evidence. An operator reading it on Telegram
could not make an informed choice: retry, edit, or close were guesses.

## Decision

- The `blocked_task` event key `"<task_id>@<blocked_at>"` is the join
  between a block and its investigation: the trigger firing row carries
  that key plus the investigation bead it opened, resolved with
  `triggers/lookup.py::investigation_task_id`. A re-block after an unblock
  is a new key, so it joins to a new investigation.
- The report is read from the investigator bead's own task directory,
  `artifacts/INVESTIGATION.md` first, then `outputs/INVESTIGATION.md`
  (`state/investigation.py`), and parsed tolerantly into five fields —
  root cause, evidence, category, recommended action, confidence
  (`core/investigation.py`). A missing, reworded, or half-written section
  yields an empty string, never an error, so a half-written report still
  improves the question.
- The question text stays inside a character budget (`PROMPT_MAX_CHARS`,
  3200) because Telegram truncates a message at 4096 characters and the
  numbered options are appended after the prompt text — an unbounded
  prompt would cut the options off. The investigation block is capped
  first, so it is never the part that gets cut.
- The investigator's recommended action maps onto an EXISTING triage
  option and only reorders the list, putting the recommendation first.
  Option strings are never rewritten, because the apply step
  (`orchestrator/triage.py`) matches the operator's answer against them
  verbatim — a reworded option would silently stop applying.
- Triage holds a question while an investigation bead exists but its
  report does not, bounded by `triage_investigation_wait_minutes` (30
  minutes by default) and switched off with `triage_wait_for_investigation`.
  When no investigation was opened for a block, triage asks straight away:
  waiting for something that will never arrive is worse than asking
  without evidence.

## Consequences

- A first question can now arrive up to half an hour after a block while
  triage waits for the report to land.
- The bundled trigger's `max_open` (2) caps how many investigations may be
  open at once, so under a burst of blocks some questions still arrive
  without a report.
- A report that arrives after the question was already asked is not folded
  in retroactively; the asked question keeps its original text. Fixing
  that is a known follow-up.
