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
task, and worker-reported blocks quote the report verbatim.

The supervisor first waits for the blocked-task investigator's report:
while an investigation bead is open but its report has not landed, the
question is held back (up to `triage_investigation_wait_minutes`, 30 by
default; `triage_wait_for_investigation` switches the wait off). When the
report lands, the question leads with the investigator's root cause,
evidence, category and confidence, and puts the recommended option first.
The full report lives in the investigation bead's
`artifacts/INVESTIGATION.md`, whose path is included in the question.

Answering applies the fix (retry, retry with `claude/opus`, append your note to the
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

### Research jobs

An epic bead with `--worker research` is a research job: it turns a topic
into a laddered knowledge-base folder covering what the best N sources say,
where they agree, where they contradict each other, and what is still open:

```
fleet bd create "transformer interpretability" -t epic --worker research
```

The bead description is the input table, as free text or key/value pairs:

```
topics: transformer interpretability, sparse autoencoders
focus: what methods locate features in production LLMs, for a practitioner evaluating tooling; ignore philosophy-of-mind debates
target: transformer-interp
n_sources: 10
lenses: tech, ai
```

It runs one phase per attempt. `discover` collects 3–5× N candidate sources
as metadata only (title, abstract, authors, date, venue, URL — never full
content), drops duplicates, dead links, and sources already in the knowledge
base, then scores every survivor with `jev` — the TypeSafe judge-model CLI
that scores text with probabilities — on relevance to the focus, source
depth, and authority, and shortlists N plus a ~30% reserve. `design` turns
the shortlist into children: one `summarise` workflow run per new source
plus a copy bead, then per-subtopic digests, topic-level `digest.md` /
`overview.md` / `disagreements.md` / `open_questions.md`, one bead per lens,
and `index.md` + `sources.md` last, each level depending on the one below.
`gate` posts one ask_human question showing the shortlist with scores and
one-line reasons — "approve N tasks?" with approve / revise (with a note) /
cancel. `spawn` starts the workflow runs and beads with dependencies;
`aggregate` is the children doing the reading and synthesis (each aggregate
reads only per-source summaries and lower-level aggregates, never raw
sources); `observe` validates coverage — every approved source has a folder
and is linked from the topic index — and opens follow-ups otherwise.

Output lands under `/Users/sergii/.ai/knowledge/research/<target>/`
(`sources/` holds one folder per source, aggregates sit above). The output
contract — folder layout, every file's shape, the ranking rubric, the naming
rules, the gate text — lives in the spec `ai show research/get`; if this
guide and the spec disagree, the spec wins. `fleet research <id>` (an alias
of `fleet job` with the source table) prints the phase plus the scored
shortlist; the run detail shows the same table.

A finished target can be re-run with the same or a wider input: `sources.md`
is the ledger of every source ever considered, so a re-run skips ledger
entries, processes only new sources, and regenerates every aggregate from
the now-larger leaf set. A schedule (see ADR 0007) can therefore keep a
topic current.
