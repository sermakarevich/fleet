# ADR 0004: Task Directory Artifacts Are Driven by Three Use Cases

## Status

Accepted

## Date

2026-09-08

## Context

A task directory grew to 17 distinct file kinds. Per attempt: `run.json`,
`launch.json`, `mcp.json`, `events.jsonl`, `log.jsonl`, `log.stderr`,
`RESULT.json`, `HANDOFF.md`, `SUMMARY.md` and three dot-markers. Per task:
`task.json`, `attempts.jsonl`, `.kill`, `.needs_validation` and an
`artifacts/` folder with `RESULT.json`, `RESULT.prev.json`, `PLAN.md`,
`HANDOFF.md`, `KNOWLEDGE.md`, `outputs/`.

Reviewing a real 23-attempt task (fleet-exfhr) showed:

- Five places say "what happened": `RESULT.summary`, `HANDOFF.md`,
  `KNOWLEDGE.md`, `SUMMARY.md`, `attempts.jsonl`. The model kept the same
  results table in HANDOFF and KNOWLEDGE; PLAN.md went stale after attempt 2.
  LLM workers do not respect boundaries between three prose files, and the
  compaction step has to judge three files with two different caps.
- `run.json` already mixes identity, lease, steps and exit metrics, yet the
  one-line `launch.json` lives beside it.
- Worker output has two homes (`artifacts/` live, `attempts/<n>/` snapshot)
  plus a hand-rolled third copy, `RESULT.prev.json`.
- The prompt actually sent to the worker is not a file; it is the first
  line of `log.jsonl`.
- Signal files (`.kill`, `.checkpoint_*`, `.compacted`) are documented
  next to artifacts although nobody reads them after the attempt.

## Decision

Every file in a task directory must answer a question from exactly one of
three use cases, and each question has exactly one file.

| Use case | Question | Reader | File |
|---|---|---|---|
| Observability | Is it alive, which step, which pid, last heartbeat, how was it launched | stall, orphans, UI | `attempts/<n>/run.json` |
| Observability | What is it doing now | UI stream, `fleet tail` | `attempts/<n>/events.jsonl` |
| Observability | What did fleet and the CLI do | debugging | `attempts/<n>/log.jsonl`, `log.stderr` |
| Observability | What exactly was the worker told | debugging, prompt tuning | `attempts/<n>/prompt.md`, `mcp.json` |
| Restart, orchestrator | Why did each attempt end, how many, which kind | retry policy, triage, UI | `attempts.jsonl` |
| Restart, worker | Done, in flight, next, facts that must survive | next attempt's model, compaction | `STATE.md` |
| Completion | Finished? what changed, tests, what is left | reap validation, bead close, UI | `RESULT.json` |
| Completion | The deliverables | humans, downstream tasks | `outputs/` |

Resulting layout (9 file kinds):

```
tasks/<id>/
  task.json          # definition
  attempts.jsonl     # journal: start/end per attempt, kind, outcome, reason
  STATE.md           # worker memory: ## Plan, ## Done, ## In flight, ## Next, ## Facts
  RESULT.json        # completion contract, present only between worker exit and reap
  outputs/
  .kill .needs_validation                      # signals, not artifacts
  attempts/<n>/
    run.json         # identity, lease, launch {mode, pack_bytes, kind}, steps, exit metrics
    prompt.md        # the rendered prompt as sent
    mcp.json         # coder input (claude only)
    events.jsonl  log.jsonl  log.stderr
    STATE.md  RESULT.json                      # snapshots taken at reap
    .checkpoint_requested .checkpoint_sent .compacted   # signals
```

Rules that follow:

- **One memory file.** `PLAN.md`, `HANDOFF.md`, `KNOWLEDGE.md` merge into
  `STATE.md` with fixed sections and one byte cap. Compaction rewrites one
  file. The continue pack is `STATE.md` plus the previous `RESULT.json`.
- **Derived data is not stored.** `SUMMARY.md` is computed from
  `run.json`, `events.jsonl` and `attempts.jsonl` on demand
  (`state/attempt_summary.py`). No file.
- **Snapshots replace rotation.** Reap copies `STATE.md` and `RESULT.json`
  into `attempts/<n>/` and then removes the task-level `RESULT.json`.
  `RESULT.prev.json` disappears; the previous result is the previous
  attempt's snapshot.
- **One record per attempt.** `launch.json` folds into `run.json["launch"]`.
- **Inputs are recorded.** `llm_session` writes `prompt.md` before spawning.
- **Signals are documented apart** from artifacts and never read by the UI.
- `state/paths.py` remains the only module that knows these names. Old
  task directories are read through a fallback in one module; nothing
  writes the old layout.

## Consequences

- Templates `PLAN.md.tmpl`, `HANDOFF.md.tmpl`, `KNOWLEDGE.md.tmpl` are
  replaced by `STATE.md.tmpl`; `INSTRUCTION_*.md`, `COMPACTION.md` and
  `coder_header.md.tmpl` describe one file.
- `core/launch.ArtifactSnapshot` shrinks to `state_text`, `state_is_stub`,
  `latest_result`; config `handoff_max_bytes` and `knowledge_max_bytes`
  become `state_max_bytes`.
- `workers/compact.py` emits one fenced `STATE` block.
- UI: Artifacts tab shows STATE.md, RESULT.json, outputs/; Attempts tab
  gets the summary from the API instead of a file.
- `FLEET_ARTIFACT_DIR` is removed; workers write under `$FLEET_TASK_DIR`.

## Affects

`src/fleet/state/{paths,artifacts,attempt_summary,task_summary}.py`,
`src/fleet/core/{launch,config,compaction_fallback}.py`,
`src/fleet/workers/{task,compact,llm_session}.py`,
`src/fleet/orchestrator/{reap,triage}.py`, `src/fleet/coders/*`,
`src/fleet/templates/*`, `src/fleet/serve/api/{tasks,search}.py`,
`src/fleet/cli/tasks.py`, UI task-detail tabs, `docs/ARCHITECTURE.md`
"Task directory contract", `docs/WORKER_CONTRACT.md`. Bead "Worker 13/13".
