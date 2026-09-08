# Worker contract

The single reference for what a fleet worker receives, what it must
produce, and what fleet does with each outcome. Other specs cite this
file instead of re-describing the contract.

## What the worker gets

- **Environment**: `FLEET_TASK_DIR` (the task directory), `FLEET_ARTIFACT_DIR`
  (`$FLEET_TASK_DIR/artifacts`), plus whatever the coder's `env()` adds
  (e.g. `BEADS_DIR`).
- **Prompt**: `templates/coder_header.md.tmpl` (task id, title, description,
  task/artifact directory paths) followed by `templates/INSTRUCTION.md`
  (the protocol below) and, for isolated (worktree) tasks,
  `templates/ISOLATED_PROTOCOL.md`.
- **No `--resume`**: fleet never resumes a session. The files under
  `artifacts/` are the worker's only continuation state across attempts.
- **Pre-seeded artifacts**: fleet creates `PLAN.md`, `HANDOFF.md`,
  `KNOWLEDGE.md` (from `templates/*.md.tmpl`) and `outputs/` before every
  spawn, but never overwrites them once they exist. Any `RESULT.json` left
  by the previous attempt is rotated to `RESULT.prev.json` before the new
  attempt starts, so a stale file can't be mistaken for this attempt's
  outcome.

## What the worker must produce

Before exiting, on every attempt, write `artifacts/RESULT.json`:

```json
{"schema": 1, "status": "done|partial|blocked", "summary": "<1-3 sentences>",
 "commits": ["<sha>", ...], "tests": {"command": "...", "passed": true|false|null},
 "open_questions": ["..."], "next_step": "<what the next attempt should do first, or empty>",
 "blocked_reason": "<only when status=blocked>"}
```

Parsed by `core/result.py::parse_result` (pure; returns `None` for missing,
malformed, or unrecognized-`status` content, which fleet treats the same
as a missing file).

Field notes:
- `status` is the only required field besides `schema`.
- `next_step` is read by fleet only when `status=partial`; it becomes the
  release reason so the next attempt knows where to pick up.
- `blocked_reason` is read only when `status=blocked`.
- `summary` is used as the bead close reason (`status=done`) or folded
  into failure comments (rc≠0 exits).

Also, every attempt:
- Overwrite `HANDOFF.md` completely (hard cap 2 KB — fleet truncates on
  read): Done / In flight / Next / Do-not-redo.
- Update `KNOWLEDGE.md` only when something durable changed; keep it
  small (~4 KB), rewriting stale sections rather than appending forever.
- Update `PLAN.md` rarely — it's the restatement and plan, not a status
  log.
- Never read `events.jsonl`, `log.jsonl`, `log.stderr`, or anything under
  `attempts/` — those are for humans and tooling.

## What fleet does with each outcome

Decided in `core/outcome_policy.py::decide` (pure) and applied in
`orchestrator/reap.py` after the subprocess exits with `rc=0`:

| RESULT.json `status` | Bead state before | Fleet action |
|---|---|---|
| `done` | `in_progress` | Closes the bead itself with `summary` as the reason (`Action.CLOSE`). The worker may still run `fleet bd close` itself; if it already did, this is a no-op. |
| `done` | not `in_progress` | No-op (already closed on exit). |
| `partial` | `in_progress` | Releases (re-queues) the bead; `next_step` becomes the release reason. Counts against the same no-close limit as an undeclared success, per spec 3. |
| `blocked` | `in_progress` | Blocks the bead with `blocked_reason` (or `summary` if absent). |
| *(no RESULT.json)* | `in_progress` | Falls back to the pre-contract no-close path: release/block on the no-close counter, comment notes "worker exited without RESULT.json". |

Independent of RESULT.json:
- `rc≠0` is always `TaskOutcome.FAILURE` — retried up to `RETRY_LIMIT`,
  then blocked. If `RESULT.json` is present, its `summary` is folded into
  the bead comment, but it never overrides the failure outcome.
- If the agent set the bead to `blocked` directly (e.g. via `fleet bd
  block`) rather than declaring `status=blocked`, fleet does not call
  `set_blocked` again — that path already changed bead state itself.

## Where the pieces live

- `core/result.py` — `Result` dataclass, `parse_result(text) -> Result | None`. Pure, no I/O.
- `core/task.py` — `TaskOutcome.PARTIAL`, `TaskOutcomeRecord.close_reason`.
- `core/outcome_policy.py` — `Action.CLOSE`, the `PARTIAL` case, the `SUCCESS` `close_reason` branch.
- `orchestrator/reap.py` — reads `artifacts/RESULT.json`, folds it into the outcome record for `rc=0` exits, applies the resulting `Decision`.
- `workers/task.py::PrepareArtifacts` — seeds artifact stubs, rotates the previous `RESULT.json` aside before each spawn.
- `templates/INSTRUCTION.md`, `templates/ISOLATED_PROTOCOL.md` — the protocol text handed to the worker.

## Steps and workers

See `docs/adr/0003-workers-as-step-pipelines.md` for the full rationale.
A **step** is atomic (`Step.run(ctx) -> StepResult`); a **worker** is a
named, ordered tuple of steps (`Worker(name, steps)`). `run_worker` drives
one worker run: it executes steps in order, stops at the first `fail`
(-> `FAILURE`) or `outcome` (-> that outcome), and treats an all-`ok` run
as `SUCCESS`. Each step's `{name, started_at, ended_at, status, reason}`
is appended to `run.json["steps"]`; `run.json["worker"]` records the
worker's name.

Family routing picks *which* worker runs, before the worker plans its own
variant:

1. **Family, from the bead**: an input, never inferred. Bead type
   `task`/`bug`/`feature`/`chore` route to the task family; `epic` routes
   to the observer family. The optional metadata field `fleet_worker`
   overrides. `workers/__init__.py::select_worker` does one dictionary
   lookup — an unrecognised family raises `ValueError`, which blocks the
   bead the same way an unknown coder does.
2. **Variant, from the task directory**: each family exposes
   `plan(ctx) -> Worker`, a pure function over its own artifacts and
   attempt history (fresh vs. continue vs. needs-compaction; research vs.
   design vs. spawn vs. observe for a job).

Rules worth repeating here:
- One attempt equals one worker run; steps live inside that attempt's
  `run.json`.
- Retries and blocking stay in the orchestrator; workers never decide
  their own retries.
- Only the orchestrator changes the status of the bead being worked on.
- `llm_session` is the only step that holds a concurrency slot.
- Compose lists of steps in Python; no YAML pipelines or string-keyed
  step registries. Branching lives in `plan`, not inside a step.
- A step earns its existence with its own test and a second user;
  otherwise it's a function inside another step.
