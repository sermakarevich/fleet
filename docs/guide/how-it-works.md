# How it works

## How it works (centralized model)

There is **one** fleet home directory on your machine — `~/.fleet` by default,
override with `$FLEET_HOME` if you like.

```
~/.fleet/
├── .beads/                       # the centralized bd queue (single Dolt DB)
├── runtime.toml                  # supervisor config
├── logging/                      # supervisor logs (fleet-<date>.jsonl)
└── tasks/<task_id>/
    ├── task.json                 # per-task metadata: cwd, coder, model
    ├── log.jsonl                 # per-task supervisor log
    ├── log.stderr                # raw subprocess stderr
    ├── events.jsonl              # per-task structured events (agent reads on resume)
    ├── attempts.jsonl            # one start + one end line per worker run (outcome, reason, fleet action)
    ├── .failures                 # failure counter (drives retries)
    ├── .noclose                  # no-close counter (agent exited without closing the bead)
    ├── .stalls                   # stall counter (agent went silent past the warning threshold)
    ├── STATE.md                  # agent-owned worker memory (plan/done/next/facts)
    ├── RESULT.json               # agent-declared outcome (present until reap)
    └── outputs/                  # agent deliverables referenced from RESULT.json
```

Each task records the project working directory the agent should run in,
plus the optional coder/model override, inside
`$FLEET_HOME/tasks/<task_id>/task.json`
(`{"cwd": "/abs/path", "coder": "claude", "model": "sonnet"}`).
The supervisor — which can be started from anywhere — claims tasks from
the central queue and runs each agent subprocess in that cwd. All per-task
artifacts and logs live under `$FLEET_HOME/tasks/<task_id>/`, so they're
preserved across project moves and shared between coders. If no `task.json`
exists for a task, the supervisor falls back to running the agent in
`$FLEET_HOME` itself.

Create tasks with the `fleet bd` passthrough and write `task.json` next to
the new task ID (see "Create your first task" below).

### Blocked tasks and restarts

When a task gets blocked (e.g. after repeated failures, a stall, or an
agent that keeps exiting without closing its bead), fleet records why in
`task.json` as `blocked_reason` / `blocked_at`, and appends a line to
`attempts.jsonl` for every worker run with its outcome, the reason, and
the action fleet took (released, blocked, closed, ...). You can see this
in the web UI: the **Workers** tab shows the block reason inline, the worker
detail header shows a banner with the same reason, and the **Attempts** tab
lists the full attempt history for that task.

`POST /api/tasks/{id}/unblock` (also reachable from the Unblock button in
the UI) reopens the bead **and** resets the failure, no-close, and stall
counters back to zero, so the task gets a clean slate on its next run.
This is different from the Unblock action in the BD portal, which only
flips the bead status and leaves fleet's counters as they were — a task
unblocked that way can immediately re-block if the old counters were
already near their limits.

Attempt history and block reasons only start accumulating from the first
worker spawn after you upgrade to a fleet version with this feature —
older tasks won't have retroactive history.

### Triage of blocked tasks

Every `triage_interval_minutes` (15 by default, 0 disables) the supervisor
scans fleet-blocked beads and posts one non-blocking question per bead to
the ask_human store (visible in the Inbox tab / Telegram) with a rule-based
fix proposal: rate limits suggest switching coder/model, repeated stalls
suggest a stronger model, exhausted context retries suggest splitting the
task, and worker-reported blocks quote the report verbatim. Answering
applies the fix (retry, retry with `claude/opus`, append your note to the
task and retry, close as won't-do, or ignore 24h / forever). Ignored tasks
show an "ignored" badge in the Workers table with an Unignore button
(`POST /api/tasks/{id}/unignore`, `fleet tasks --ignored` lists them);
unblocking or re-blocking a bead clears the ignore.

### Epics are validated automatically

Beads of type `epic` are runnable: once every child bead is `closed` or
`blocked` (a `blocked` child never unblocks `bd ready`, so the supervisor
also scans open epics itself), the observer worker claims the epic,
digests the children into `artifacts/CHILDREN.md`, and validates the whole
job against the epic goal — running the test suite, not re-reading child
logs. A met goal closes the epic; missing work opens follow-up child beads
(up to `observer_max_followups` per round, `observer_max_rounds` rounds
before the epic blocks for human review) and the epic sleeps until they
close. The task detail **Children** tab shows each child with its RESULT
status plus the digest. While children still run, the observer releases
the epic immediately (outcome `waiting`: no comment, no retry counting).

### Jobs decompose themselves

An epic bead with `--worker job` is a job: it researches the repo, designs
its own child beads, asks you to approve the plan, then spawns the children
and observes them — no hand-decomposition needed:

```
fleet bd create "ship signup validation" -t epic --worker job --model opus
```

The job runs one phase per attempt (`job.research` writes
`artifacts/RESEARCH.md`, `job.design` writes `artifacts/DESIGN.md` plus
`artifacts/tasks.json`, `job.gate` posts one ask_human question "Job
<id>: approve k tasks?" with approve / revise / cancel, `job.spawn`
creates the children with dependencies, `job.observe` validates like the
observer). Each `tasks.json` entry (`key`, `title`, `body`, optional `cwd`,
`coder`, `model`, `priority`, `depends_on` naming sibling keys) becomes one
child bead; the epic sleeps until they close. `fleet job <id>` prints the
phase, children, and pending gate; the task detail shows a phase badge plus
Research/Design tabs. Research/design failing twice blocks the job; pass
`--job-gate off` (or `job_gate: false` in runtime.toml) to skip approval.
