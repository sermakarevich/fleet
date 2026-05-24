# fleet — Python supervisor for headless agent fleets

<p align="center">
  <img src="assets/fleet_mini.png" alt="fleet logo">
</p>

`fleet` is a lightweight Python supervisor that claims tasks from a
**centralized** [beads](https://github.com/gastownhall/beads) queue and runs
them through a coder (`claude`, `agy`, or `codex` CLI) in a headless loop. Each task
remembers the project working directory it was created in, plus an optional
per-task coder/model override, so a single supervisor can drive work across
many projects — and across multiple agent backends — from one machine.

---

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [How it works (centralized model)](#how-it-works-centralized-model)
- [First-run setup](#first-run-setup)
- [Command reference](#command-reference)
  - [`fleet init`](#fleet-init)
  - [`fleet ready`](#fleet-ready)
  - [`fleet show <id>`](#fleet-show-id)
  - [`fleet tasks`](#fleet-tasks)
  - [`fleet task <id> {log|plan|knowledge}`](#fleet-task-id-logplanknowledge)
  - [`fleet log [N]`](#fleet-log-n)
  - [`fleet bd <args...>`](#fleet-bd-args)
  - [`fleet run`](#fleet-run)
  - [`fleet config show` / `fleet config set`](#fleet-config-show--fleet-config-set)
- [Configuration reference](#configuration-reference)
- [Q&A protocol — for the human](#qa-protocol--for-the-human)
- [FAQ](#faq)

---

## Installation

Install `fleet` as a global tool so it is on `$PATH` from any directory:

```bash
git clone https://github.com/sermakarevich/fleet.git
uv tool install --editable ./fleet
uv tool update-shell      # if ~/.local/bin is not on PATH yet
```

Then `fleet --help` should work from anywhere. Use `uv tool upgrade fleet`
later to pick up new dependencies; code edits are live because the install is
editable.

Requires:
- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/) on your `PATH`
- [beads (`bd`)](https://github.com/gastownhall/beads) on your `PATH`
- `git` on your `PATH` (beads stores its database inside a git repo)
- At least one coder CLI on your `PATH`: `claude` (Claude Code), `agy`, or `codex` (OpenAI Codex CLI)

---

## Quick start

```bash
fleet init                                          # initialize ~/.fleet (beads DB + default config)
cd /path/to/your/project                            # any project you want the agent to work in
fleet bd create "context for other coders"          # queue a task (cwd is captured automatically)
fleet run &                                         # start the supervisor in the background
fleet tasks                                         # render a live table of in-progress tasks
```

<p align="center">
  <img src="assets/tasks.png" alt="fleet tasks output">
</p>

See [First-run setup](#first-run-setup) and the [Command reference](#command-reference)
for the full story (per-task coder/model overrides, Q&A protocol, log
locations, …).

---

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
    ├── .failures                 # failure counter (drives retries)
    └── artifacts/
        ├── PLAN_AND_STATUS.md    # agent-owned plan + progress
        ├── KNOWLEDGE.md          # agent-owned persistent notes
        └── Q&A.md                # agent ↔ human Q&A thread (when blocked)
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

---

## First-run setup

### 1. Initialize the fleet home

```bash
fleet init
# → Fleet home initialized at /Users/you/.fleet
```

This runs `bd init` inside `$FLEET_HOME` and writes a default
`runtime.toml`. Idempotent — safe to re-run.

### 2. Create your first task

Run `fleet bd create` from inside the project you want the agent to work
in — your shell's cwd is captured automatically and stored alongside the
new task:

```bash
cd /path/to/your/project
fleet bd create --title "Implement feature X"
# → Created fleet-abc: Implement feature X  [cwd: /path/to/your/project]

# Pin coder/model for this task only (overrides config defaults):
fleet bd create --coder agy --model opus --title "Heavy refactor"
# → Created fleet-def: Heavy refactor  [cwd: /…, coder: agy, model: opus]
```

`fleet bd …` forwards verbatim to the `bd` CLI inside `$FLEET_HOME`, so any
flag `bd create` accepts (`--description`, `--priority`, dependencies via
`bd dep add …`, …) works the same way. For `create` specifically, fleet
also writes `$FLEET_HOME/tasks/<id>/task.json` with `{"cwd": "<your cwd>"}`
so the supervisor knows where to spawn the agent. Pass `--json` to get the
raw bd envelope back instead of the human-friendly summary line.

`--coder` and `--model` are intercepted by fleet (not forwarded to `bd`):
they're validated against the registered coders (`claude`, `agy`, `codex`)
and persisted as per-task overrides in `task.json`, applied next time the
supervisor claims the task. Always pass both together when overriding —
or omit both to inherit the config defaults.

### 3. (Optional) Override coder/model for specific tasks

By default the supervisor uses `config.coder` (default `claude`) and
`config.model` (default `sonnet`) for every task. To pin a single task to a
different coder/model — e.g. route a heavy refactor to `agy` while leaving
everyday tasks on `claude` — pass `--coder` **and** `--model` together at
create time (always specify both so the override is unambiguous):

```bash
fleet bd create --coder agy    --model opus --title "Heavy refactor"
fleet bd create --coder codex  --model o3   --title "OpenAI task on o3"
fleet bd create --coder claude --model opus --title "Tricky task on Opus"
```

The override is persisted in `$FLEET_HOME/tasks/<task_id>/task.json` and is
applied the first time the supervisor claims the task. Resolution order is
`task.coder` → `--coder` CLI flag on `fleet run` → `config.coder`
(similarly for `model`). Confirm what the supervisor will pick with
`fleet show <task_id>` — explicit overrides are bare, while inherited
values are tagged ` (default)`. To change an override after creation,
edit `$FLEET_HOME/tasks/<task_id>/task.json` directly.

### 4. Start the supervisor

```bash
fleet run                       # uses config.coder / config.model
fleet run --coder claude        # override default coder for this process
```

The supervisor reads from `$FLEET_HOME/.beads`, claims ready tasks, and spawns
each agent subprocess in **that task's** working directory with the
per-task (or default) coder/model resolved as described above.

---

## Command reference

### `fleet init`

```bash
fleet init
fleet init --force        # re-run bd init even if .beads already exists
```

Creates `$FLEET_HOME` (default `~/.fleet`) with a beads DB, default
`runtime.toml`, and an empty `tasks/` directory.

### `fleet ready`

```bash
fleet ready
fleet ready --limit 10
```

Lists ready tasks. Each line shows the task ID, title, and recorded cwd.

### `fleet show <id>`

```bash
fleet show fleet-abc
fleet show fleet-abc --json       # raw bd show JSON envelope
```

Prints id, title, status, cwd, effective coder, effective model, and
description. The `coder:` and `model:` lines are tagged ` (default)` when
they come from `runtime.toml` rather than a per-task override.

### `fleet tasks`

```bash
fleet tasks
fleet tasks --limit 20
```

Renders a rich table of currently in-progress tasks with: ID, started
time, elapsed, idle, peak context-window usage, event count, coder,
model, title, and cwd. Per-task overrides are bolded; values inherited
from `runtime.toml` are dim. See the screenshot in [Quick start](#quick-start).

### `fleet task <id> {log|plan|knowledge}`

```bash
fleet task fleet-abc log         # → $FLEET_HOME/tasks/fleet-abc/log.jsonl
fleet task fleet-abc plan        # → artifacts/PLAN_AND_STATUS.md
fleet task fleet-abc knowledge   # → artifacts/KNOWLEDGE.md
```

Prints the named artifact for one task. `fleet task --help` additionally
lists currently running tasks with their effective `[coder/model]`, so
you can scan valid IDs without leaving the help screen.

### `fleet log [N]`

```bash
fleet log                        # whole most-recent supervisor log file
fleet log 200                    # tail the last 200 lines
```

Prints the most recently modified `fleet-<date>.jsonl` from
`$FLEET_HOME/logging/`. `N` must be a positive integer when supplied.

### `fleet bd <args...>`

Forwards arguments verbatim to the `bd` CLI, executed inside `$FLEET_HOME`.
This is the recommended way to drive the centralized beads queue from any
directory.

```bash
fleet bd create --title "Implement feature X" --json   # → {"data": {"id": "fleet-abc", …}}
fleet bd create --title "Refactor parser" \
    --description "Extract tokenizer to its own file"
fleet bd dep add fleet-newtask fleet-abc               # add dependencies
fleet bd list                                          # list every task in the central DB
fleet bd list --status=blocked                         # filter by status
fleet bd comment fleet-abc "note"                      # comment on a task
fleet bd dolt push                                     # push the beads data to your git remote
fleet bd prime                                         # show beads workflow help
fleet bd --help                                        # bd's own --help (not fleet's)
```

The exit code of `bd` is propagated. All flags are passed through unmodified,
so `fleet bd` behaves exactly like running `bd` from inside `$FLEET_HOME`.

`fleet bd create` is special-cased: it captures your shell's invocation
cwd and writes it into `$FLEET_HOME/tasks/<task_id>/task.json` so the
supervisor knows where to spawn the agent. Without `--json` you get a
human-friendly summary (`Created <id>: <title>  [cwd: <path>]`); with
`--json` you get the raw bd envelope as before. Pass `--dry-run` to skip
the task.json write (useful if you're driving bd test runs).

`--coder <name>` and `--model <name>` are also intercepted on `create`
(and `new`) — they're stripped from the args before forwarding to `bd`,
validated, and persisted as per-task overrides in `task.json`. Unknown
coder names fail fast without invoking `bd`. The summary line reflects
any overrides applied: `Created <id>: <title>  [cwd: <path>, coder: agy,
model: opus]`.

### `fleet run`

```bash
fleet run
fleet run --coder claude         # override the default coder for this run
```

| Option | Description |
|---|---|
| `--coder` | Optional override for the default coder this process uses. Falls back to `config.coder` (default `claude`). Per-task overrides set on `fleet bd create` still win. Registered values: `claude`, `agy`, `codex`. |

### `fleet config show` / `fleet config set`

```bash
fleet config show
fleet config show --raw                                # raw TOML bytes
fleet config set max_concurrent=5
```

The supervisor re-reads `$FLEET_HOME/runtime.toml` on change and applies updates without restart.

---

## Configuration reference

Configurable keys live in `$FLEET_HOME/runtime.toml`. Edit via `fleet config set …` or
directly in the file.

| Key | Default | Description |
|---|---|---|
| `max_concurrent` | `3` | Maximum number of agent subprocesses running at once. |
| `claim_poll_interval_sec` | `5` | How often (seconds) the supervisor polls for new claimable tasks. |
| `coder` | `claude` | Default coder used when neither the task nor `fleet run --coder` specifies one. Registered values: `claude`, `agy`, `codex`. |
| `model` | `sonnet` | Default model used when the task does not specify one. Interpreted by the active coder (e.g. `claude` understands `sonnet` / `opus` / `haiku`; the `agy` coder ignores it because the agy CLI reads its model from its own settings file; `codex` passes it as `--model`, defaulting to `o4-mini`). |
| `context_pressure_threshold_pct` | `90` | Terminate an agent session when prompt-side context usage exceeds this percentage of the model's limit. |

---

## Q&A protocol — for the human

When an agent is blocked by ambiguity, it will:

1. Append a `## Q:` block to the task's `Q&A.md` in the artifact directory.
2. Run `bd update <task_id> --status blocked --notes "QUESTION: <summary>"`.
3. Exit cleanly.

**To answer and resume the task:**

1. Find the task:
   ```bash
   fleet ready                  # not listed if blocked
   bd list --status=blocked     # from inside $FLEET_HOME
   fleet show <task_id>         # see the question summary
   ```

2. Read the Q&A file from the task's artifact directory:
   ```bash
   cat $FLEET_HOME/tasks/<task_id>/artifacts/Q\&A.md
   ```

3. Append your answer directly below the `## Q:` block:
   ```markdown
   ## A: <YYYY-MM-DD HH:MM>

   <your answer here>
   ```

4. Unblock the task:
   ```bash
   fleet bd update <task_id> --status open --assignee ""
   ```

The supervisor will re-claim the task on the next scheduling cycle. The agent
reads `Q&A.md` on startup (per the resume protocol inlined from
`INSTRUCTION.md`) and continues from where it stopped.

---

## FAQ

**Q: A task exhausted its retries. What now?**

The supervisor moves the task to `blocked` with a reason of the form
`"retry limit (N) exhausted; last failure: …"` and posts a comment with
the last exit code and a tail of stderr. Inspect the failure logs with
`fleet task <task_id> log` (or directly at
`$FLEET_HOME/tasks/<task_id>/log.jsonl` and
`$FLEET_HOME/tasks/<task_id>/log.stderr`). Fix the underlying issue, then:

```bash
fleet bd update <task_id> --status open --assignee ""
```

The supervisor will re-claim it with a fresh retry counter.

---

**Q: How do rate-limit pauses work?**

When the Claude API rate-limit usage exceeds 90 %, the supervisor stops
claiming new tasks. In-flight tasks continue running. The supervisor
resumes claiming after 5 minutes or when the rate gauge drops below the
threshold. Rate-limit exits do NOT consume a retry.

---

**Q: Can I run the fleet across multiple machines?**

Multi-machine operation is out of scope for v1. The supervisor is designed for
single-machine use. The beads queue is a local Dolt database; concurrent access
from multiple machines is not supported in this version.

---

**Q: Why is there no `--resume` flag?**

The fleet does not pass `--resume` to the Claude CLI. Continuation state lives
entirely in the artifact directory (`PLAN_AND_STATUS.md`, `KNOWLEDGE.md`,
`Q&A.md`, `events.jsonl`). The agent reads these files on every fresh
invocation to pick up where it left off. This approach works across restarts,
crashes, and machine reboots without depending on the CLI's session
resumption mechanism.

---

**Q: Where is the bundled `INSTRUCTION.md` template?**

It lives at `<install>/src/fleet/templates/INSTRUCTION.md`. The supervisor reads
it at coder-invocation time and inlines its full content into the prompt, so
the coder always picks up the latest version without any per-project file
copy. Open that path directly if you want to read or hand-edit it.
