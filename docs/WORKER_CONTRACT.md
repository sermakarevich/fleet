# Worker contract

The single reference for what a fleet worker receives, what it must
produce, and what fleet does with each outcome. Other specs cite this
file instead of re-describing the contract.

## What the worker gets

- **Environment**: `FLEET_TASK_DIR` (the task directory), `FLEET_ATTEMPT_N`
  (this attempt's number), `FLEET_ATTEMPT_DIR`
  (`$FLEET_TASK_DIR/attempts/<n>`), `FLEET_LAUNCH_MODE` (`fresh` or
  `continue`, see "Launch modes" below), plus whatever the coder's `env()`
  adds (e.g. `BEADS_DIR`). The three `FLEET_ATTEMPT_*` / `FLEET_LAUNCH_MODE`
  variables are layered on by `workers/llm_session.py` after calling the
  coder's `env()` — no coder needs to know about them.
- **Prompt**: built once by `coders/base.py::render_prompt(task, task_dir,
  plan)`, called by all five coders: `templates/coder_header.md.tmpl` (task
  id, title, description, task directory path), then the launch pack (empty
  on a fresh start), then `templates/INSTRUCTION_FRESH.md` or
  `templates/INSTRUCTION_CONTINUE.md` depending on `plan.mode`, then the
  shared `templates/INSTRUCTION_COMMON.md`, then — for isolated (worktree)
  tasks — `templates/ISOLATED_PROTOCOL.md`. The exact prompt sent is
  recorded at `attempts/<n>/prompt.md` before spawning (the `log.jsonl`
  argv line keeps `<see prompt.md>` instead of the text).
- **No `--resume`**: fleet never resumes a session. `STATE.md` (plus the
  bounded continue pack) is the worker's only continuation state across
  attempts.
- **Pre-seeded state**: fleet creates `STATE.md` (from
  `templates/STATE.md.tmpl`) and `outputs/` before every spawn, but never
  overwrites them once they exist. Reap snapshots `STATE.md` and
  `RESULT.json` into `attempts/<n>/` and then removes the task-level
  `RESULT.json`, so a stale file can never be mistaken for the next
  attempt's outcome.

## Tools available to the worker

Every worker is handed fleet's MCP (Model Context Protocol) servers
explicitly — never via the operator's personal CLI config — so the tools the
prompt names exist on any machine. Definitions live once in
`integrations/mcp_servers.py::fleet_mcp_servers`; each coder adapts them to
its native config format.

| tool | what it does | opencode | claude | codex | agy |
|---|---|---|---|---|---|
| `ask_human` | ask the operator a question mid-task; blocks until answered (SQLite store under `FLEET_HOME`) | `OPENCODE_CONFIG_CONTENT` `mcp.ask-human` | `<attempt>/mcp.json` via `--mcp-config` + `--strict-mcp-config` | per-attempt `CODEX_HOME/config.toml` `[mcp_servers.ask_human]` | TODO: mechanism unknown |
| `web_fetch` | fetch a URL and get a distilled answer | `OPENCODE_CONFIG_CONTENT` `mcp.web_fetch` (+ `FLEET_WEBFETCH_*` model vars) | same `mcp.json` | same `config.toml` | TODO: same gap |

The supervisor logs a startup warning (`ask_human_unavailable`) when the
bundled ask_human server module cannot be imported.

## What the worker must produce

Before exiting, on every attempt, write `$FLEET_TASK_DIR/RESULT.json`:

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
- Rewrite `STATE.md` completely (hard cap 6 KB — fleet truncates on
  read): fill `## Plan` once, move finished items to `## Done`, keep
  durable findings in `## Facts`, and leave the single next action in
  `## Next`.
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
| BLOCKED_BY_CODER | no | | | BLOCK |
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

## After a block

A blocked bead waits for the operator, not for another worker spawn:

- Every `triage_interval_minutes` the supervisor posts one non-blocking
  ask_human question per fleet-blocked bead (rule-based proposal from
  `core/triage_policy.py`) and applies the answer on the next tick:
  `retry same setup` releases, `retry with claude/opus` pins the override
  then releases, `edit task text and retry` appends your note to the bead
  description then releases, `close as won't do` closes, `ignore 24h` /
  `ignore forever` sets `task.json` `ignore_until` (triage skips the bead
  while active). A free-text note always wins over the picked option.
- Beads blocked by a human (`fleet bd block`, no `blocked_reason` in
  `task.json`) never get triage questions.
- Unblocking (UI button or API) releases the bead and resets the retry
  counters; it also clears any triage ignore.

## Isolation

Git-aware worktree isolation, decided at spawn (`orchestrator/spawn.py`):

- **Non-git task** — `task.cwd` is not inside a git repo (`git rev-parse
  --show-toplevel` fails). The worker runs in place in `task.cwd`; there is
  no worktree and no merge step. Outcome handling is otherwise identical
  (`RESULT.json` `status=done` still closes the bead).
- **Isolated task** — cwd is inside a repo, `config.isolation="worktree"`
  (default), and the bead did not opt out. The worker runs in
  `$FLEET_HOME/worktrees/<repo>-<task_id>` on branch `fleet/<task_id>`,
  forked from the repo's default branch (`origin/HEAD` → current branch →
  `main`). `repo_root`/`base_ref`/`worktree_path` are stored in `task.json`.
  The worker commits everything to its branch, declares `status=done`, and
  exits; fleet merges (fast-forward, else `--no-ff`) into `base_ref` and
  runs `config.post_merge_command` before closing. The prompt gains
  `templates/ISOLATED_PROTOCOL.md`.
- **Opted-out task** — the bead carries `fleet_isolation: "none"` metadata
  (`fleet bd create --isolation none`) or `config.isolation="none"`. Runs
  in place like a non-git task even though the cwd is in a repo.

## Where the pieces live

- `core/result.py` — `WorkerResult` dataclass, `parse_result(text) -> WorkerResult | None`. Pure, no I/O.
- `core/task.py` — `TaskOutcome.PARTIAL`, `TaskOutcomeRecord.close_reason`.
- `core/retry_policy.py` — `Action.CLOSE`, the `PARTIAL` case, the `SUCCESS` `close_reason` branch.
- `orchestrator/reap.py` — reads task-level `RESULT.json`, folds it into the outcome record for `rc=0` exits, applies the resulting `RetryDecision`.
- `workers/task_family.py::ensure_state` — seeds the STATE.md stub, records the launch in `run.json["launch"]`.
- `workers/compact.py::Compact` — the compaction step (see "Compaction").
- `core/compaction_fallback.py` — pure deterministic fallback (see "Compaction").
- `templates/COMPACTION.md` — the compaction prompt.
- `templates/INSTRUCTION_FRESH.md`, `templates/INSTRUCTION_CONTINUE.md`,
  `templates/INSTRUCTION_COMMON.md`, `templates/ISOLATED_PROTOCOL.md` — the
  protocol text handed to the worker; assembled by `coders/base.py::render_prompt`.

## Launch modes

Decided once per attempt, in Python, before the coder is spawned — never
inferred by the model. `core/launch_policy.py::plan_launch` (pure) takes this
task's attempt history and an `ArtifactSnapshot` (`state/artifacts.py::read_artifacts`,
the I/O side) and returns a `LaunchPlan`:

- **`fresh`** — no prior attempts AND `STATE.md` is still its seeded stub.
  The prompt gets `INSTRUCTION_FRESH.md` and no pack; the worker fills in
  the `## Plan` section of `STATE.md` first.
- **`continue`** — everything else (any prior attempt, or STATE.md edited).
  The prompt gets `INSTRUCTION_CONTINUE.md` and a bounded text "pack":
  "Attempt N of this task. Previous attempt ended: `<outcome>`:
  `<reason>`." followed by `STATE.md` and the previous `RESULT.json`'s
  `summary` / `next_step` / `open_questions` / `tests`. The worker is told
  **not** to re-plan or re-read logs — the pack is its only history.
- **`needs_compaction`** — recorded on the `LaunchPlan` (and in this
  attempt's `run.json["launch"]`) when `STATE.md` exceeds
  `state_max_bytes` or the pack exceeds `continue_pack_max_bytes`. This
  spec only truncates to the cap as a deterministic fallback so the launch
  still works; a later worker (`ContinueLargeTask`) acts on the flag by
  compacting STATE.md first.

`workers/task_family.py::PrepareContinue` calls `plan_launch` and stores the
result in `ctx.scratch["launch_plan"]` for `LlmSession` to read; `plan_task`
runs the same computation once more, purely to choose between the
`FreshTask`, `ContinueTask`, and `ContinueLargeTask` workers (see "Steps and
workers" below). Both prepare steps record the decision in this attempt's
`run.json["launch"]` before spawning.

## Compaction

When `plan_launch(...).needs_compaction` is true, `plan_task` returns
`ContinueLargeTask = Worker("task.continue_large", (Compact(),
PrepareContinue(), LlmSession()))`: a `workers/compact.py::Compact` step runs
*before* the continue launch, then `PrepareContinue` re-runs `plan_launch` on
the compacted artifacts and `LlmSession` launches in `continue` mode as usual
(same worker run, same attempt).

- **Bounded inputs, by construction** — never raw logs: current `STATE.md`
  (8 KB cap), the last 3 attempt summaries derived via
  `state/attempt_summary.py` (4 KB each), the last `RESULT.json`, and
  `git log --oneline -30` + `git status --short` (first 30 lines) of the
  workdir. Total input cap ~24 KB; oldest summaries are dropped first.
- **Cheap model call** through the existing coder machinery
  (`compaction_coder`, default `claude`; `compaction_model`, default `haiku`;
  prompt from `templates/COMPACTION.md`; hard turn cap `--max-turns 2` for
  claude; 3-minute timeout). The one fenced `STATE` block is parsed from
  the `assistant_text` events.
- **Atomic write** to task-level `STATE.md` (`state_max_bytes` cap,
  default 6 KB). Any failure, timeout, or over-cap output falls back to
  the deterministic section-by-section truncation in
  `core/compaction_fallback.py` (Facts first, Done second, never Next) and
  logs `compaction_fallback`.
- **Visible and costed**: the compaction journals its own `kind="compact"`
  attempt row in `attempts.jsonl` (with its own `attempts/<n>/` folder:
  events, `run.json["launch"]` `{"mode":"compact"}`, recorded `prompt.md`),
  so it shows in the Attempts timeline with a distinct "compaction" row
  style. A compaction counts against the coder's concurrency cap like any
  attempt. Retry streaks skip `kind="compact"` rows. Disable with
  `compaction_enabled=false`.
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
  (rewrite `STATE.md`, commit WIP, write partial `RESULT.json`, exit 0) and
  touches `.checkpoint_sent` so it fires once. Other coders rely on the kill
  threshold below. The hook injects guidance via
  `hookSpecificOutput.additionalContext`.
- At or past the **kill** threshold — or when stderr/events carry the CLI's
  own "prompt is too long" / context-overflow error — the runner kills the
  process group and reports `CONTEXT_PRESSURE` (a real outcome branch, no
  marker file; analytics read it from `attempts.jsonl`).
- The claude `PreCompact` hook touches `$FLEET_ATTEMPT_DIR/.compacted` so
  the derived attempt summary can count CLI-side auto-compactions
  (`cli_compactions`).
- Policy: `CONTEXT_PRESSURE` releases immediately (never counted as failure),
  with a bead comment per round (`context limit round k/3; compaction +
  continue`); after 3 rounds the bead blocks with "too large for one worker;
  split it". `task_summary` exposes `context_rounds`, `compactions`, and the
  latest `peak_context_pct`; the Attempts timeline shows a "context" badge on
  such attempts.

## Liveness

Three different clocks watch a running attempt, and they answer three
different questions:

- **Stall** watches `attempts/<n>/events.jsonl` mtime: "is the agent still
  *saying* anything?" Silence past `stall_warning_minutes` warns (and kills
  with `stall_action="kill"`); see `orchestrator/stall.py`.
- **Lease** watches `attempts/<n>/run.json` `heartbeat_at`/`lease_until`:
  "is the runner process still *alive*?" `workers/llm_session.py` refreshes
  the lease every `HEARTBEAT_SEC` (30 s) while the coder subprocess lives;
  `orchestrator/leases.py::reconcile_leases` (startup + every 60 s) releases
  a bead whose lease is stale past one full heartbeat *and* whose pid is
  provably dead (or on another host). A stale lease with a live pid only
  warns — fleet never kills what it cannot prove is its own — and beads
  with no attempt dir (human-claimed) are never touched.
- **Timeout** watches the wall clock: "has this attempt run *too long*?"
  `max_attempt_minutes` (per-task `fleet_max_attempt_minutes` or global)
  kills the process group with outcome `KILLED` reason `timeout`, retried on
  the stall ladder.

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

## Observer

Beads of type `epic` route to the observer family
(`workers/observe.py::plan_observer`, always `Observer = Worker("observer",
(WaitChildren(), CollectChildren(), LlmSession(), SpawnFollowups()))`).
The claim rule lives in `beads/queue.py`: an epic is claimed when `bd
ready` lists it, or when it is open, has children (its dependencies of
relation `blocks`/`depends_on`, via `beads/client.py::children_of`), and
`core/job_ready.py::children_terminal` holds (every child `closed` or
`blocked` — a `blocked` child would otherwise leave the epic asleep
forever, since beads only marks an issue ready when every dependency
closed).

Steps:

- `WaitChildren`: all children terminal → ok; else outcome `WAITING`
  (`"k of n children still running"`), which covers the race where an epic
  is claimed while a child still runs.
- `CollectChildren` (Python, no model): digests each child
  (task-level `RESULT.json` status+summary, latest derived attempt
  summary's files-touched count, bead status, `blocked_reason`) into
  `artifacts/CHILDREN.md`, bounded by construction (≤ 8 KB total, ≤ 600
  chars per child, oldest sections dropped first). Child ids and the
  blocked count go to `ctx.scratch`; the validate `LaunchPlan` (with the
  digest as its pack) goes there too, so `FLEET_LAUNCH_MODE=validate`.
- `LlmSession` with the validate pack (`coders/base.py::render_prompt`
  `mode="validate"`, `templates/INSTRUCTION_VALIDATE.md`): checks the repo
  against the epic goal (runs the test suite, reads changed files, never
  re-reads child logs) and writes RESULT.json — `done` when the goal is
  met, `partial` with `followups: [{title, body, cwd, depends_on: []}]`
  when work is missing, `blocked` with `blocked_reason` when a human must
  fix a blocked child. Same coder/model as the epic bead.
- `SpawnFollowups` (Python): validates `followups` with
  `core/job_plan.py::validate_followups` (≤ `observer_max_followups`,
  unique titles, `depends_on` naming sibling titles, acyclic) and creates
  them via `beads/queue.py::create_child` (title/body/cwd default from the
  epic, coder/model inherited, `--deps` between follow-ups, epic gains a
  dependency on each), then comments `"[fleet] opened k follow-ups: ids"`.

Outcome policy (`core/retry_policy.py`, applied in `orchestrator/reap.py`):

| outcome | action |
|---|---|
| `WAITING` | `RELEASE` (short delay against hot-looping), no bead comment, no round counting, logged as `worker_waiting`; the Attempts timeline shows a grey `waiting` row |
| RESULT `done` | `CLOSE` the epic with `close_reason` |
| RESULT `blocked` | `BLOCK`; triage surfaces it |
| RESULT `partial` | `RELEASE` (follow-ups keep the epic asleep until they close); past `observer_max_rounds` partial observer rounds (counted from attempts.jsonl via `core/job_plan.py::observer_rounds`) → `BLOCK` "observer exhausted; needs human review" |
| session-step failure | normal task table |

`WaitChildren`/`CollectChildren`/`SpawnFollowups` take no concurrency
slot; only `LlmSession` does. A waiting observer attempt exits in seconds,
so it never holds a slot long.

## Job worker

Beads of type `epic` with metadata `fleet_worker=job` (`fleet bd create
--worker job`) route to the job family (`workers/job.py::plan_job`), which
reads the task directory into a `core/job_phase.py::JobSnapshot` and picks
one phase worker per attempt — research, design, gate, spawn, observe —
so the Attempts timeline shows the job's history. The job worker creates
beads; it never runs workers.

| Snapshot | Phase | Worker (steps) |
|---|---|---|
| no RESEARCH.md | research | `JobPrepare(research), LlmSession(mode="research")` |
| RESEARCH.md, no tasks.json | design | `JobPrepare(design), LlmSession(mode="design")` |
| tasks.json, gate on, no approval | gate | `AskApproval` |
| tasks.json, approved (or gate off), no children | spawn | `SpawnChildren` |
| children exist | observe | `WaitChildren, CollectChildren, LlmSession(mode="validate"), SpawnFollowups` |

- **Research** explores the repo and writes `artifacts/RESEARCH.md`
  (≤ 12 KB, never changes code), then RESULT `partial`/`next_step=design`.
  **Design** writes `artifacts/DESIGN.md` plus `artifacts/tasks.json`,
  then RESULT `partial`/`next_step=gate`. Both run on the epic's model
  (opus recommended) with `coders/base.py::render_prompt` modes
  `research`/`design` (`templates/INSTRUCTION_RESEARCH.md`,
  `templates/INSTRUCTION_DESIGN.md`).
- **tasks.json contract** (`core/job_plan.py::validate_tasks`):
  `{"tasks": [{key, title, body, cwd, coder, model, priority,
  depends_on}]}` — keys unique, `depends_on` names sibling keys, acyclic,
  at most `job_max_children` (default 30), title ≤ 120 chars, body
  non-empty. Invalid → `SpawnChildren` (or the gate, as a guard) writes
  `artifacts/DESIGN_ERRORS.md` and RESULT `partial`/`next_step=design`,
  so the next attempt re-runs design with the errors in the pack (plus any
  `artifacts/DESIGN_NOTES.md` revision notes).
- **Gate** (`AskApproval`, non-blocking ask_human like triage): posts one
  question "Job \<id\>: approve k tasks?" (options `approve`,
  `revise (write note)`, `cancel job`, `context="job_gate"`) and returns
  `WAITING`. Next claim: `approve` writes `artifacts/APPROVED` and RESULT
  `partial`/`next_step=spawn`; `revise`/note appends to
  `artifacts/DESIGN_NOTES.md`, deletes tasks.json, RESULT
  `partial`/`next_step=design`; `cancel` writes RESULT `blocked`
  `cancelled by operator`. `job_gate: false` config or per-bead
  `fleet_job_gate=off` (`fleet bd create --job-gate off`) skips the gate.
- **Spawn** (`SpawnChildren`): creates beads in dependency order via
  `beads/queue.py::create_child` (body gains "Part of job \<id\>; DESIGN.md
  at \<path\>", cwd/coder/model default from the epic or
  `job_child_coder`/`job_child_model`, `--deps` from keys, epic gains a
  dependency on each child), journaling `artifacts/children.json`
  after **each** create so a crash resumes without duplicates, then comments
  "[fleet] job spawned k children: ids" and RESULT
  `partial`/`next_step=observe`.
- **Observe** reuses the observer steps under worker name `job.observe`
  (observer rounds cap counts `job.observe` partials too).
- **Policy**: research/design failing `job_max_phase_attempts` (default 2)
  times each blocks the job ("job design failed; see attempts"). Wall-clock
  per phase comes from the generic retry table. Only `LlmSession` holds a
  concurrency slot.
