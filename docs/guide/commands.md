# Command reference

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
from `runtime.toml` are dim. See the screenshot in [Quick start](getting-started.md#quick-start).

### `fleet task <id> {log|state|result}`

```bash
fleet task fleet-abc log         # → latest attempt's log.jsonl
fleet task fleet-abc state       # → tasks/fleet-abc/STATE.md
fleet task fleet-abc result      # → tasks/fleet-abc/RESULT.json
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

### `fleet gc`

```bash
fleet gc                         # archive closed tasks older than 30 days
fleet gc --days 7                # shorter retention window
fleet gc --dry-run               # report without moving anything
fleet gc --purge                 # also delete archives older than gc_archive_days (90)
```

Moves closed task directories under `$FLEET_HOME/tasks` whose modification
time is older than `--days` (default 30) to `$FLEET_HOME/archive/tasks`,
printing how many directories were archived, how much space moved, and how
many were skipped. Open tasks, recent tasks, and directories without a
readable `task.json` are always skipped. Pass `--dry-run` to preview what
would be archived without moving anything.

### Retention

Disk use stays bounded without manual cleanup. The supervisor runs a
retention pass once at startup (after lease reconciliation) and then every
24 hours, and `fleet gc --purge` runs the same steps on demand:

1. **Archive** — closed tasks older than `gc_retention_days` (default 30,
   `0` disables) move to `$FLEET_HOME/archive/tasks/`.
2. **Purge** — archived task dirs older than `gc_archive_days` (default 90,
   `0` disables) are deleted permanently.
3. **Worktrees** — worktree dirs under `$FLEET_HOME/worktrees/` whose task
   is closed and older than `gc_retention_days` are removed.
4. **Beads** — when `gc_beads` is enabled (default on), `bd gc --older-than
   gc_retention_days --force` and `bd compact --days gc_retention_days` run
   against the beads database itself, permanently deleting closed beads
   older than the window (export first if you need the history) and
   squashing old Dolt commits; this step is skipped while any bead is
   in progress.

Each step logs counts and bytes (`retention_gc_tasks`,
`retention_purge_archive`, `retention_worktrees`, `retention_bd_gc` in the
supervisor log).

### `fleet schedule ...` (recurring workers)

A schedule is a saved task template plus a cron expression and a time
zone. Each time it fires, the supervisor opens one ordinary bead from
the template — after that it is a normal task like any other.

```bash
fleet schedule create --name triage --cron "0 9 * * 1-5" --title "Triage {date}"
fleet schedule list                  # id, on/off, cron, next run, last run, runs
fleet schedule show sch-abc123       # definition, next 5 firings, last 20 runs
fleet schedule run sch-abc123        # fire one manual run now
```

The same schedules are visible in the web UI under the **Scheduled**
sub-tabs of **Workers** (worker schedules) and **Workflows** (workflow
schedules) (`fleet serve`). Definitions live in
`~/.fleet/schedules/<id>.json`, run history in
`~/.fleet/schedules/<id>.runs.jsonl`. See ADR 0007 and
`docs/ARCHITECTURE.md` (section "Schedules").

### `fleet workflow ...` (workflows)

A workflow is a saved, named definition of workers arranged in **stages**:
every step in one stage may run in parallel, and a stage starts when the
previous stage is complete. A step with no `needs` depends on every step of
the previous stage; `needs: [names]` narrows that to a subset from earlier
stages. Running a workflow (a **run**) opens one ordinary bead per step,
wired with bead dependencies — after that each step is a normal task.

```yaml
fleet_workflow: 1
name: nightly-quality
description: Lint, test and summarise
defaults: {cwd: /Users/me/git/app, coder: opencode, model: qwen3.6:latest, priority: 2}
stages:
  - name: checks
    steps:
      - name: lint
        title: "Lint {{workflow.name}} ({{run.date}})"
        description: Run ruff and fix what it reports.
      - name: tests
        title: Run the test suite
        description: uv run pytest -q; fix failures.
  - name: report
    steps:
      - name: summary
        title: Summarise the night
        description: "Read tasks {{steps.lint.task_id}} and {{steps.tests.task_id}}."
```

```bash
fleet workflow import nightly.yaml    # validate + save, prints the id
fleet workflow list                   # id, name, stages, steps, runs, last status
fleet workflow show nightly-quality   # stage outline (steps with needs)
fleet workflow run nightly-quality    # start a manual run, prints run id + steps
fleet workflow runs nightly-quality   # run history with done/total steps
```

The same workflows are visible in the web UI under the **Workflows** tab
(`fleet serve`); recurring workflow runs live under its **Scheduled**
sub-tab (`fleet schedule create --workflow <id|name> ...`). Definitions and run
history live in `~/.fleet/workflows.db` (SQLite). See ADR 0008.

A workflow may name a `builder:` instead of saving `stages:` — a builder
expands the saved definition into concrete stages at run start (see ADR 0013).
`fleet workflow show` prints `builder:` for such workflows, and `fleet workflow
show --yaml` round-trips it. The only builder today is `summary_get`
(`docs/workflows/summary-get.yaml`): import it with
`fleet workflow import docs/workflows/summary-get.yaml`, then run
`fleet workflow run summary_get --input url=<url>` to summarize a YouTube
video, X/Twitter thread, arXiv/PDF, or article page into an LLM-wiki folder in
the knowledge base (one wiki-page step per chunk, then digest/summary,
explainer/questions/critical-thinking/connections, and index).

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
fleet serve start                 # start on 0.0.0.0:7890 (default, all interfaces)
fleet serve start --host 127.0.0.1 # local-only bind
fleet serve start --port 8080     # custom port
fleet serve status                # running? (pid, start time, port)
fleet serve restart               # rebuild the UI (just ui-build) and restart
fleet serve restart --no-build    # restart without rebuilding the UI
fleet serve stop                  # stop the server
fleet serve foreground --port 8080  # run in the current terminal (blocks)
```

Set `FLEET_API_TOKEN` in the environment of `fleet serve` to require `Authorization: Bearer <token>` on the API and `?token=` on WebSockets; unset means open (local use only).

### Network exposure

`fleet serve` binds `serve_host:serve_port` (`0.0.0.0:7890` by default, so the
UI is reachable on your LAN/Tailscale). That default exposes the API to the
local network with no token, so pair it with `FLEET_API_TOKEN` on any network
you do not fully trust — or bind local-only with
`fleet serve start --host 127.0.0.1` (persist via
`fleet config set serve_host=127.0.0.1`). Full key list: [docs/CONFIG.md](../CONFIG.md).

Starts a local web server backed by FastAPI and serves a React SPA at
`http://127.0.0.1:7890` (or `http://<tailscale-ip>:7890` from another device on your tailnet). API spec (Swagger): http://localhost:7890/api/docs. The UI provides:
- **Dashboard** — live task table with status, elapsed time, and context usage
- **Task detail** — logs, plan, knowledge, and chat per task
- **Chat** — review and answer blocked tasks in one place
- **Analytics** — token usage and throughput charts
- **Config** — view and edit `runtime.toml` settings

| Sub-command | Description |
|---|---|
| `start` | Spawn the UI server detached on `<host>:<port>` (default `0.0.0.0:7890`; `--host 127.0.0.1` for local only). Idempotent. |
| `stop` | Stop the server daemon. |
| `restart` | Run `just ui-build` (rebuild the SPA) **first**, then `stop` + `start`. The build runs before the old server is stopped, so a failed build leaves the current server running. The port defaults to the one recorded in the PID file. Pass `--no-build` to skip the rebuild, or `--port` to change it. |
| `status` | Print running/stopped plus pid, start time, and port. Exits non-zero when stopped. |
| `foreground` | Run uvicorn in the foreground (blocks). This is what `start` execs. |

The UI is a Vite + React + TypeScript SPA living in `src/fleet/ui/`. Its
assets must be built once before first use (and are rebuilt by
`fleet serve restart`). Building requires **Node.js ≥ 18 and `npm`** (see
[Installation](getting-started.md#installation)).

```bash
just ui-build      # npm install (deps) + npm run build, then copy dist → $FLEET_HOME/ui_dist/
```

The justfile exposes four UI recipes, all rooted at `src/fleet/ui/`:

| Recipe | What it does |
|---|---|
| `just ui-install` | `npm install` — install/refresh the SPA's node dependencies. |
| `just ui-build` | Depends on `ui-install`, then `npm run build` (`tsc && vite build`) and copies `dist/` to `$FLEET_HOME/ui_dist/`. This is the only recipe you need for a normal build — it installs deps for you. |
| `just ui-dev` | `npm run dev` — Vite dev server with hot reload, for working on the UI itself. |
| `just ui-check` | `npx tsc --noEmit` — typecheck the SPA without emitting output. |

`fleet serve restart` runs `just ui-build` for you. If there is no `justfile`
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

Retry tuning: `max_attempt_minutes` (default 120, 0 = off) caps one attempt's
wall-clock time — over budget the worker is killed and reported as
`KILLED reason="timeout"`. `stall_action` (default `"kill"`) decides what a
stall detection does (`warn` or `kill`).

### `fleet telegram setup` / `fleet telegram status` / `fleet telegram test`

```bash
fleet telegram setup                    # guided wizard to configure the Telegram integration
fleet telegram status                   # show configuration and connectivity
fleet telegram test                     # send a test message to the configured chat
fleet telegram test --message "hello"   # custom message text
```

`fleet telegram setup` walks through token validation, chat-ID discovery (by polling for a message you send to your channel), optional inbound task commands, and a confirmation message. Writes the discovered values to `runtime.toml`. Pass flags to skip interactive prompts:

```bash
fleet telegram setup --chat-id -1001234567890 --yes           # non-interactive outbound only
fleet telegram setup --chat-id -1001234567890 \
    --allowed-ids 123456789 --default-cwd /path/to/project    # non-interactive with inbound
```

`fleet telegram status` exits 0 when fully configured, 1 otherwise — suitable for scripting. Example output:

```
$ fleet telegram status
TELEGRAM_BOT_TOKEN         12345...:***
bot                        @myfleetbot

telegram_chat_id           -1001234567890
telegram_allowed_ids       123456789
telegram_default_cwd       /Users/you/git/myproject

outbound notifications     ok
inbound task commands      ok
```

`fleet telegram test` sends a plain-text message to `telegram_chat_id` and exits non-zero on failure — useful for smoke-testing after config changes:

```
$ fleet telegram test
Message sent to -1001234567890.
```

See [Telegram channel notifications](telegram.md#telegram-channel-notifications) for the full setup guide.

### `fleet ask-human <command>`

```bash
fleet ask-human install                     # register the bundled MCP server with Claude Code (user scope)
fleet ask-human install --scope project     # register at project/local scope instead
fleet ask-human serve                       # run the MCP server on stdio (what `install` registers — only one you'll need)
```

Fleet bundles the `ask_human` human-in-the-loop MCP server that its agents use to ask you questions mid-task. Answer from the Fleet web UI Inbox tab (`fleet serve`) or Telegram.

`fleet ask-human install` requires the `claude` CLI on your `PATH`. It first
removes any existing `ask_human` registration at the chosen scope, then runs
`claude mcp add ask_human --scope <scope> -- fleet ask-human serve`. `--scope`
accepts `user` (default), `project`, or `local` and mirrors Claude Code's MCP
scopes. On success it prints the resolved binary path and reminds you to verify
with `claude mcp list`.
