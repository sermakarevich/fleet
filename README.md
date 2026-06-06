# fleet — Python supervisor for running coding agents in parallel

<p align="center">
  <img src="assets/fleet_mini.png" alt="fleet logo">
</p>

<p align="center">
  <a href="https://docs.google.com/presentation/d/1O_pXyKdtpRG2ORD1xw7svifjpCol96wIVvOU6kOMDlI/edit?usp=sharing">
    <img src="https://img.shields.io/badge/Slides-fleet_overview-FBBC04?style=for-the-badge&logo=googleslides&logoColor=white" alt="Slides — fleet overview presentation">
  </a>
</p>

`fleet` is a lightweight Python supervisor that claims tasks from a
**centralized** [beads](https://github.com/gastownhall/beads) queue and runs
them in parallel through a coder (`claude`, `agy`, or `codex` CLI) in a headless loop. Each task
remembers the project working directory it was created in, plus an optional
per-task coder/model override, so a single supervisor can drive work across
many projects — and across multiple agent backends — spawning many concurrent agents - from one machine.

<p align="center">
  <img src="assets/tasks.png" alt="fleet tasks output">
</p>

Fleet ships with a full-featured web UI (`fleet serve`) that covers the entire agent lifecycle — create and configure tasks, monitor live progress and logs, and chat with blocked agents through the Q&A inbox, all from a single dashboard.

<p align="center">
  <img src="assets/fleet_ui.png" alt="fleet web UI">
</p>

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
  - [`fleet serve`](#fleet-serve)
  - [`fleet config show` / `fleet config set`](#fleet-config-show--fleet-config-set)
- [Configuration reference](#configuration-reference)
- [Adding a custom coder](#adding-a-custom-coder)
- [Q&A protocol — for the human](#qa-protocol--for-the-human)

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
fleet config set max_concurrent=3                   # cap how many agents run in parallel
cd /path/to/your/project                            # any project you want the agent to work in

# Title + description:
fleet bd create --title "add codex coder" \
    --description "wire the OpenAI codex CLI into fleet"

# Pin coder/model for this task only:
fleet bd create --coder agy --model "GPT-OSS 120B" \
    --title "insert task.png from assets into README.md" \
    --description "promote the screenshot to the Quick start section"

# Positional-title shortcut (cwd is captured automatically):
fleet bd create "context for other coders"

fleet run start                                     # start the supervisor as a background daemon
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
`task.coder` → `config.coder` (similarly for `model`). Confirm what the supervisor will pick with
`fleet show <task_id>` — explicit overrides are bare, while inherited
values are tagged ` (default)`. To change an override after creation,
edit `$FLEET_HOME/tasks/<task_id>/task.json` directly.

### 4. Start the supervisor

```bash
fleet run start                 # start the supervisor as a background daemon
fleet run status                # is it running? (pid + start time)
fleet run restart               # pick up code/config changes
fleet run stop                  # graceful shutdown
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

The supervisor runs as a long-lived background daemon, managed via
sub-commands. It is tracked through a PID file at `$FLEET_HOME/.supervisor.pid`
(the same file the web UI reads to show supervisor status).

```bash
fleet run start          # spawn the supervisor detached in the background
fleet run status         # show whether it is running (pid + start time)
fleet run restart        # stop + start to pick up code/config changes
fleet run stop           # graceful shutdown (SIGTERM, then SIGKILL after a grace window)
fleet run foreground     # run in the current terminal (blocks; for debugging)
```

| Sub-command | Description |
|---|---|
| `start` | Spawn the supervisor as a detached daemon. Idempotent — a no-op (with a notice) if already running. The default coder comes from `config.coder` (default `claude`); per-task overrides set on `fleet bd create` still win. |
| `stop` | Send SIGTERM for a graceful shutdown (in-flight tasks are released), escalating to SIGKILL after a grace window longer than the supervisor's own shutdown timeout. |
| `restart` | `stop` then `start`. Use this after editing code or `runtime.toml`. |
| `status` | Print running/stopped plus pid and start time. Exits non-zero when stopped (handy in scripts). |
| `foreground` | Run the supervisor in the foreground (blocks). This is what `start` execs; use it directly to watch logs live. |

The daemon's stdout/stderr is captured to `$FLEET_HOME/logging/supervisor.daemon.log`
(structured task logs still go to `$FLEET_HOME/logging/fleet-*.jsonl`).

> Note: daemons are CLI-managed only — they do **not** survive a reboot and are
> **not** auto-restarted on crash. Use `fleet run restart` to apply changes.

### `fleet serve`

The web UI server also runs as a background daemon, tracked through
`$FLEET_HOME/.serve.pid`.

```bash
fleet serve start                 # start on 127.0.0.1:7890 (default)
fleet serve start --port 8080     # custom port
fleet serve status                # running? (pid, start time, port)
fleet serve restart               # rebuild the UI (make ui-build) and restart
fleet serve restart --no-build    # restart without rebuilding the UI
fleet serve stop                  # stop the server
fleet serve foreground --port 8080  # run in the current terminal (blocks)
```

Starts a local web server backed by FastAPI and serves a React SPA at
`http://127.0.0.1:7890`. The UI provides:

- **Dashboard** — live task table with status, elapsed time, and context usage
- **Task detail** — logs, plan, knowledge, and Q&A per task
- **Q&A inbox** — review and answer blocked tasks in one place
- **Analytics** — token usage and throughput charts
- **Config** — view and edit `runtime.toml` settings

| Sub-command | Description |
|---|---|
| `start` | Spawn the UI server detached on `127.0.0.1:<port>` (default 7890). Idempotent. |
| `stop` | Stop the server daemon. |
| `restart` | Run `make ui-build` (rebuild the SPA) **first**, then `stop` + `start`. The build runs before the old server is stopped, so a failed build leaves the current server running. The port defaults to the one recorded in the PID file. Pass `--no-build` to skip the rebuild, or `--port` to change it. |
| `status` | Print running/stopped plus pid, start time, and port. Exits non-zero when stopped. |
| `foreground` | Run uvicorn in the foreground (blocks). This is what `start` execs. |

The UI assets must be built once before first use (and are rebuilt by
`fleet serve restart`):

```bash
make ui-build    # builds React SPA and copies it to $FLEET_HOME/ui_dist/
```

`fleet serve restart` runs `make ui-build` for you. If there is no `Makefile`
(e.g. a non-source install), the build step is skipped with a warning rather
than failing. If `$FLEET_HOME/ui_dist/` is absent, the server starts without the
UI and logs a warning.

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
| `coder` | `claude` | Default coder used when a task does not specify one. Registered values: `claude`, `agy`, `codex`. |
| `model` | `sonnet` | Default model used when the task does not specify one. Interpreted by the active coder (e.g. `claude` understands `sonnet` / `opus` / `haiku`; the `agy` coder ignores it because the agy CLI reads its model from its own settings file; `codex` passes it as `--model`, defaulting to `o4-mini`). |
| `context_pressure_threshold_pct` | `90` | Terminate an agent session when prompt-side context usage exceeds this percentage of the coder's context limit. Supported by all built-in coders (limits: `claude` 200K tokens, `agy` 128K, `codex` 128K). |

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

## Adding a custom coder

Fleet ships with three built-in coders (`claude`, `agy`, `codex`), but you can
wrap any CLI agent in four small steps.

### Step 1 — Implement the `Coder` base class

Create a file in `src/fleet/coders/`, e.g. `src/fleet/coders/mycoder.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from fleet.coders.base import Coder
from fleet.schemas import Event, Task

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_INSTRUCTION_PATH = _TEMPLATES_DIR / "INSTRUCTION.md"
_HEADER_PATH = _TEMPLATES_DIR / "coder_header.md.tmpl"


class MyCoder(Coder):
    name = "mycoder"          # unique name used in fleet bd create --coder
    context_limit = 128_000   # used to compute context-pressure threshold

    def __init__(self, model: str = "my-default-model") -> None:
        self.model = model

    def build_argv(self, task: Task, task_dir: Path) -> list[str]:
        """Return the argv list passed to asyncio.create_subprocess_exec()."""
        artifacts_dir = task_dir / "artifacts"
        instructions = _INSTRUCTION_PATH.read_text(encoding="utf-8").strip()
        invocation_line = f"Invocation directory: {task.cwd}" if task.cwd else ""
        header = _HEADER_PATH.read_text(encoding="utf-8").format(
            task_id=task.id,
            task_title=task.title,
            task_description=task.description or "",
            task_dir=task_dir,
            artifacts_dir=artifacts_dir,
            invocation_line=invocation_line,
        ).strip()
        prompt = f"{header}\n\n---\n\n{instructions}"
        return ["mycli", "--model", self.model, "--json", prompt]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        """Return env-var overlay merged on top of os.environ before spawn.

        These three keys are REQUIRED — the agent reads them to locate its
        artifact directory and write PLAN_AND_STATUS.md / KNOWLEDGE.md.
        """
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
            "FLEET_ARTIFACT_DIR": str(task_dir / "artifacts"),
        }

    def normalize_event(self, raw_line: str) -> Event | None:
        """Parse one stdout line from the subprocess into a normalized Event.

        Return None for any line you want to discard.  Must be pure — no I/O.
        """
        if not raw_line.strip():
            return None
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            return None
        ts = datetime.now(tz=timezone.utc)
        kind = data.get("type", "")
        if kind == "started":
            return Event(kind="session_started", raw=data, ts=ts)
        if kind == "finished":
            return Event(kind="session_ended", raw=data, ts=ts, usage=data.get("usage"))
        return None
```

**Contracts to honour:**
- `build_argv` — the last positional element is almost always the full prompt;
  construct it from the shared templates so the agent receives the Fleet task
  protocol and artifact-directory instructions.
- `env` — always emit `FLEET_TASK_ID`, `FLEET_TASK_DIR`, `FLEET_ARTIFACT_DIR`;
  never put `ANTHROPIC_API_KEY` here (the CLI owns that).
- `normalize_event` — return `None` for anything you don't understand; the
  runner skips `None` events safely. Must be **pure** (no I/O, no logging).

### Step 2 — Register the coder

Add one line to `src/fleet/coders/__init__.py`:

```python
from fleet.coders.mycoder import MyCoder   # add this import

_REGISTRY: dict[str, type[Coder]] = {
    "claude":   ClaudeCoder,
    "agy":      AgyCoder,
    "codex":    CodexCoder,
    "mycoder":  MyCoder,    # add this entry
}
```

### Step 3 — Use your coder

```bash
# set as the default for all tasks
fleet config set coder=mycoder

# or pin it to individual tasks at creation time
fleet bd create --coder mycoder --model my-model --title "Task for my coder"
```

That's it — the supervisor discovers the coder through `_REGISTRY`, so no
further configuration is needed.
