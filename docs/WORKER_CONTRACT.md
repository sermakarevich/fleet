# Worker contract

The single reference for what a fleet worker receives, what it must
produce, and what fleet does with each outcome. Other specs cite this
file instead of re-describing the contract.

## What the worker gets

- **Environment**: `FLEET_TASK_DIR` (the task directory), `FLEET_ARTIFACT_DIR`
  (`$FLEET_TASK_DIR/artifacts`), `FLEET_ATTEMPT_N` (this attempt's number),
  `FLEET_ATTEMPT_DIR` (`$FLEET_TASK_DIR/attempts/<n>`), `FLEET_LAUNCH_MODE`
  (`fresh` or `continue`, see "Launch modes" below), plus whatever the
  coder's `env()` adds (e.g. `BEADS_DIR`). The three `FLEET_ATTEMPT_*` /
  `FLEET_LAUNCH_MODE` variables are layered on by `workers/llm_session.py`
  after calling the coder's `env()` — no coder needs to know about them.
- **Prompt**: built once by `coders/base.py::render_prompt(task, task_dir,
  plan)`, called by all five coders: `templates/coder_header.md.tmpl` (task
  id, title, description, task/artifact directory paths), then the launch
  pack (empty on a fresh start), then `templates/INSTRUCTION_FRESH.md` or
  `templates/INSTRUCTION_CONTINUE.md` depending on `plan.mode`, then the
  shared `templates/INSTRUCTION_COMMON.md`, then — for isolated (worktree)
  tasks — `templates/ISOLATED_PROTOCOL.md`.
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

Decided in `core/retry_policy.py::decide` (pure) and applied in
`orchestrator/reap.py` after the subprocess exits. Rounds are counted from
`attempts.jsonl` history (consecutive same-outcome attempts; a different
ending resets the streak). `RELEASE` may carry a `wait_sec` delay, stored as
task.json `retry_after` — `claim_next` skips tasks whose `retry_after` is in
the future.

| outcome | retry | wait (sec) | max rounds | then |
|---|---|---|---|---|
| FAILURE (rc≠0) | yes | 60, 300, 900 + jitter 0–30 | 3 | BLOCK |
| KILLED reason=stalled or reason=timeout | yes | 0 | 2 | BLOCK |
| RATE_LIMIT | yes | until resets_at (min 300) | unlimited, not counted | wait |
| CONTEXT_PRESSURE | yes | 0 | 3 | BLOCK reason "too large for one worker; split it" |
| PARTIAL (RESULT.json) | yes | 0 | 5 | BLOCK |
| SUCCESS with RESULT done | close | | | |
| SUCCESS without RESULT.json (noclose) | yes | 0 | 3 (was 12) | BLOCK |
| BLOCKED_BY_AGENT | no | | | BLOCK |
| KILLED manual | no | | | BLOCK "manually interrupted" |
| TERMINAL setup error (unknown coder/model, missing cwd, cwd not a dir) | no | | | BLOCK immediately |

| RESULT.json `status` | Bead state before | Fleet action |
|---|---|---|
| `done` | `in_progress` | Closes the bead itself with `summary` as the reason (`Action.CLOSE`). The worker may still run `fleet bd close` itself; if it already did, this is a no-op. |
| `done` | not `in_progress` | No-op (already closed on exit). |
| `partial` | `in_progress` | Releases (re-queues) the bead; `next_step` becomes the release reason. Counts against the same no-close limit as an undeclared success, per spec 3. |
| `blocked` | `in_progress` | Blocks the bead with `blocked_reason` (or `summary` if absent). |
| *(no RESULT.json)* | `in_progress` | Falls back to the pre-contract no-close path: release/block on the no-close counter, comment notes "worker exited without RESULT.json". |

Independent of RESULT.json:
- `rc≠0` is always `TaskOutcome.FAILURE` — retried up to 3 rounds
  (waits 60, 300, 900 sec + jitter), then blocked. If `RESULT.json` is present, its `summary` is folded into
  the bead comment, but it never overrides the failure outcome.
- If the agent set the bead to `blocked` directly (e.g. via `fleet bd
  block`) rather than declaring `status=blocked`, fleet does not call
  `set_blocked` again — that path already changed bead state itself.

## Where the pieces live

- `core/result.py` — `Result` dataclass, `parse_result(text) -> Result | None`. Pure, no I/O.
- `core/task.py` — `TaskOutcome.PARTIAL`, `TaskOutcomeRecord.close_reason`.
- `core/retry_policy.py` — `Action.CLOSE`, the `PARTIAL` case, the `SUCCESS` `close_reason` branch.
- `orchestrator/reap.py` — reads `artifacts/RESULT.json`, folds it into the outcome record for `rc=0` exits, applies the resulting `Decision`.
- `workers/task.py::PrepareArtifacts` — seeds artifact stubs, rotates the previous `RESULT.json` aside before each spawn.
- `workers/compact.py::Compact` — the compaction step (see "Compaction").
- `core/compaction_fallback.py` — pure deterministic fallback (see "Compaction").
- `templates/COMPACTION.md` — the compaction prompt.
- `templates/INSTRUCTION_FRESH.md`, `templates/INSTRUCTION_CONTINUE.md`,
  `templates/INSTRUCTION_COMMON.md`, `templates/ISOLATED_PROTOCOL.md` — the
  protocol text handed to the worker; assembled by `coders/base.py::render_prompt`.

## Launch modes

Decided once per attempt, in Python, before the coder is spawned — never
inferred by the model. `core/launch.py::plan_launch` (pure) takes this
task's attempt history and an `ArtifactSnapshot` (`state/artifacts.py::read_artifacts`,
the I/O side) and returns a `LaunchPlan`:

- **`fresh`** — no prior attempts AND `PLAN.md`/`HANDOFF.md`/`KNOWLEDGE.md`
  are all still their seeded stubs. The prompt gets `INSTRUCTION_FRESH.md`
  and no pack; the worker plans from the task text and writes `PLAN.md` first.
- **`continue`** — everything else (any prior attempt, or any artifact
  edited). The prompt gets `INSTRUCTION_CONTINUE.md` and a bounded text
  "pack": "Attempt N of this task. Previous attempt ended: `<outcome>`:
  `<reason>`." followed by labelled sections for the previous `HANDOFF.md`,
  the previous `RESULT.json`'s `next_step`/`open_questions`, the latest
  attempt's `SUMMARY.md`, and `KNOWLEDGE.md`. The worker is told **not** to
  re-plan or re-read logs — the pack is its only history.
- **`needs_compaction`** — recorded on the `LaunchPlan` (and in this
  attempt's `launch.json`) when the pack exceeds `continue_pack_max_bytes`,
  `KNOWLEDGE.md` exceeds `knowledge_max_bytes`, or the previous attempt has
  no parseable `RESULT.json` / no non-stub `HANDOFF.md` (it died without
  handing off). This spec only truncates each section to its cap as a
  deterministic fallback so the launch still works; a later worker
  (`ContinueLargeTask`) acts on the flag by compacting artifacts first.

`workers/task.py::PrepareContinue` calls `plan_launch` and stores the
result in `ctx.scratch["launch_plan"]` for `LlmSession` to read; `plan_task`
runs the same computation once more, purely to choose between the
`FreshTask`, `ContinueTask`, and `ContinueLargeTask` workers (see "Steps and
workers" below). Both prepare steps write `attempts/<n>/launch.json` before
spawning.

## Compaction

When `plan_launch(...).needs_compaction` is true, `plan_task` returns
`ContinueLargeTask = Worker("task.continue_large", (Compact(),
PrepareContinue(), LlmSession()))`: a `workers/compact.py::Compact` step runs
*before* the continue launch, then `PrepareContinue` re-runs `plan_launch` on
the compacted artifacts and `LlmSession` launches in `continue` mode as usual
(same worker run, same attempt).

- **Bounded inputs, by construction** — never raw logs: current `HANDOFF.md`,
  `KNOWLEDGE.md`, `PLAN.md`, the last 3 attempt `SUMMARY.md` files (4 KB
  each), the last `RESULT.json`, and `git log --oneline -30` + `git status
  --short` (first 30 lines) of the workdir. Total input cap ~24 KB; oldest
  summaries are dropped first.
- **Cheap model call** through the existing coder machinery
  (`compaction_coder`, default `claude`; `compaction_model`, default `haiku`;
  prompt from `templates/COMPACTION.md`; hard turn cap `--max-turns 2` for
  claude; 3-minute timeout). The two fenced `HANDOFF`/`KNOWLEDGE` blocks are
  parsed from the `assistant_text` events.
- **Atomic writes** to `artifacts/HANDOFF.md` (2 KB cap) and
  `artifacts/KNOWLEDGE.md` (4 KB cap). Any failure, timeout, or over-cap
  output falls back to the deterministic pure truncation in
  `core/compaction_fallback.py` and logs `compaction_fallback`.
- **Visible and costed**: the compaction journals its own `kind="compact"`
  attempt row in `attempts.jsonl` (with its own `attempts/<n>/` folder:
  events, `launch.json` `{"mode":"compact"}`, `SUMMARY.md`), so it shows in
  the Attempts timeline with a distinct "compaction" row style. A compaction
  counts against the coder's concurrency cap like any attempt. Retry streaks
  skip `kind="compact"` rows. Disable with `compaction_enabled=false`.
- After the run the next worker must never re-read huge logs — and neither
  may the compaction job itself.

## Context limits

`workers/llm_session.py` tracks `peak_context_tokens` against the resolved
per-model window on every usage event: `core.context_window.resolve_window`
(built-in `DEFAULT_WINDOWS` table plus the `context_windows`
`"model:tokens,model:tokens"` runtime.toml overrides) with the coder's
`context_limit` class default as fallback. Every coder's
`context_limit_for(model, overrides)` resolves through the same function, and
`state/task_summary.py` uses it for the `context_pct` / `peak_context_pct`
the UI shows — supervisor and UI always divide by the same number. The old
single-number `opencode_context_limit` / `opencode_bedrock_context_limit`
keys are gone; if present in runtime.toml they are ignored with a warning
naming `context_windows`. Two thresholds (`context_checkpoint_pct`,
default 75; `context_kill_pct`, default 90):

- At or past the **checkpoint** threshold the runner touches
  `attempts/<n>/.checkpoint_requested` once. The claude-only
  `PostToolUse` hook (`coders/hooks/posttool_checkpoint.sh`, matcher `""`)
  fires on the next tool use: it tells the model to stop new work now
  (update `HANDOFF.md`, commit WIP, write partial `RESULT.json`, exit 0) and
  touches `.checkpoint_sent` so it fires once. Other coders rely on the kill
  threshold below. The hook injects guidance via
  `hookSpecificOutput.additionalContext`.
- At or past the **kill** threshold — or when stderr/events carry the CLI's
  own "prompt is too long" / context-overflow error — the runner kills the
  process group and reports `CONTEXT_PRESSURE` (a real outcome branch, no
  marker file; analytics read it from `attempts.jsonl`).
- The claude `PreCompact` hook touches `$FLEET_ATTEMPT_DIR/.compacted` so
  `SUMMARY.md` can count CLI-side auto-compactions (`cli_compactions`).
- Policy: `CONTEXT_PRESSURE` releases immediately (never counted as failure),
  with a bead comment per round (`context limit round k/3; compaction +
  continue`); after 3 rounds the bead blocks with "too large for one worker;
  split it". `task_summary` exposes `context_rounds`, `compactions`, and the
  latest `peak_context_pct`; the Attempts timeline shows a "context" badge on
  such attempts.

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
