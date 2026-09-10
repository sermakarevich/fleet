# Getting started

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
- At least one coder CLI on your `PATH`: `claude` (Claude Code), `agy`, `codex` (OpenAI Codex CLI), `opencode` (opencode CLI with Ollama backend), or `pi` (pi CLI)
- **Node.js ≥ 18 and `npm`** — only needed to build the web UI (`fleet serve` / `just ui-build`). Not required for the headless supervisor.
- `claude` (Claude Code) on your `PATH` — only needed to register the bundled `ask_human` MCP server (`fleet ask-human install`).

---

## Quick start

```bash
fleet init                                          # initialize ~/.fleet (beads DB + default config)
fleet config set max_concurrent=3                   # cap how many agents run in parallel
fleet config set max_concurrent_overrides=claude:2,opencode:4   # per-coder limits; unlisted coders use max_concurrent
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
  <img src="../../assets/tasks.png" alt="fleet tasks output">
</p>

See [First-run setup](#first-run-setup) and the [Command reference](commands.md#command-reference)
for the full story (per-task coder/model overrides, log locations, …).

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
they're validated against the registered coders (`claude`, `agy`, `codex`, `opencode`, `pi`)
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
