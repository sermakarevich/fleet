# fleet configuration reference

Settings live in `$FLEET_HOME/runtime.toml` — edit via `fleet config set …`
or directly in the file. The supervisor re-reads the file on change and
applies updates without restart; in-flight subprocesses are never killed by
a config change.

The Settings table below and the `runtime.toml.header` comment block are
GENERATED from field metadata in `src/fleet/core/config.py`; the Tunables
table is GENERATED from `src/fleet/core/limits.py`. Regenerate with
`just config-docs` (`fleet config docs --write`); `just check` fails when the
generated regions drift. Do not edit generated regions by hand — change the
metadata and regenerate.

## Settings

<!-- BEGIN GENERATED:SETTINGS -->
| Name | Type | Default | Description | Example |
|---|---|---|---|---|
| `max_concurrent` | `int` | `3` | Maximum agent subprocesses running at once. | `fleet config set max_concurrent=5` |
| `model` | `str` | `"sonnet"` | Default model when a task sets no override. | `fleet config set model=opus` |
| `coder` | `str` | `"claude"` | Default coder CLI when a task sets no override. | `fleet config set coder=codex` |
| `telegram_chat_id` | `str` | `""` | Telegram chat ID for notifications; empty disables them. | `fleet config set telegram_chat_id=-1001234567890` |
| `telegram_allowed_ids` | `str` | `""` | Telegram sender IDs allowed inbound commands; empty disables all. | `fleet config set telegram_allowed_ids=123456789,987654321` |
| `telegram_default_cwd` | `str` | `""` | Working directory for tasks created via Telegram; empty leaves unset. | `fleet config set telegram_default_cwd=/Users/you/git/myproject` |
| `opencode_ollama_url` | `str` | `"http://127.0.0.1:11435/v1"` | Ollama API base URL used by the opencode coder. | `fleet config set opencode_ollama_url=http://127.0.0.1:11434/v1` |
| `ollama_ssh_host` | `str` | `"rtx"` | SSH host alias for the GPU box behind opencode_ollama_url. | `fleet config set ollama_ssh_host=gpubox` |
| `ollama_remote_port` | `int` | `11434` | Ollama port on the GPU box (remote end of the tunnel). | `fleet config set ollama_remote_port=11434` |
| `max_concurrent_overrides` | `str` | `""` | Per-coder limits as coder:limit pairs; others use max_concurrent. | `fleet config set max_concurrent_overrides=claude:2,opencode:4` |
| `context_windows` | `str` | `""` | Per-model context windows as model:tokens pairs; empty uses built-ins. | `fleet config set context_windows=muse-spark-1.3-contributor:1048576` |
| `opencode_default_model` | `str` | `"qwen3.6:latest"` | Ollama model for opencode tasks without an override. | `fleet config set opencode_default_model=qwen3.5:27b` |
| `opencode_bedrock_region` | `str` | `""` | AWS region for Bedrock; empty inherits the environment. | `fleet config set opencode_bedrock_region=us-east-1` |
| `opencode_bedrock_profile` | `str` | `""` | AWS profile for Bedrock; empty inherits the environment. | `fleet config set opencode_bedrock_profile=dev` |
| `stall_warning_minutes` | `int` | `15` | Silence minutes before an attempt counts as stalled. | `fleet config set stall_warning_minutes=30` |
| `stall_action` | `str` | `"kill"` | Stall response: warn logs only, kill stops the attempt. | `fleet config set stall_action=warn` |
| `max_attempt_minutes` | `int` | `120` | Wall-clock cap per attempt; 0 disables. Over budget kills. | `fleet config set max_attempt_minutes=60` |
| `continue_pack_max_bytes` | `int` | `8192` | Pack budget in bytes before a continue launch compacts. | `fleet config set continue_pack_max_bytes=16384` |
| `state_max_bytes` | `int` | `6144` | Hard cap on the worker-memory file STATE.md in bytes. | `fleet config set state_max_bytes=8192` |
| `compaction_enabled` | `bool` | `true` | Compact before continue launches that need it; else truncate. | `fleet config set compaction_enabled=false` |
| `compaction_coder` | `str` | `"claude"` | Coder CLI used for the cheap compaction call. | `fleet config set compaction_coder=claude` |
| `compaction_model` | `str` | `"haiku"` | Model used for the cheap compaction call. | `fleet config set compaction_model=haiku` |
| `context_checkpoint_pct` | `int` | `75` | Peak-context percent that asks the model to wrap up early. | `fleet config set context_checkpoint_pct=80` |
| `context_kill_pct` | `int` | `90` | Peak-context percent that kills with CONTEXT_PRESSURE. | `fleet config set context_kill_pct=95` |
| `isolation` | `str` | `"worktree"` | Git worktree isolation: worktree isolates repo tasks, none runs in place. | `fleet config set isolation=none` |
| `isolation_exclude` | `str` | `""` | Repo roots that never get a worktree; empty excludes none. | `fleet config set isolation_exclude=/Users/me/.ai` |
| `post_merge_command` | `str` | `""` | Shell command after a clean worktree merge; empty skips. | `fleet config set post_merge_command=make ui-build` |
| `triage_interval_minutes` | `int` | `15` | Minutes between blocked-task triage scans; 0 disables. | `fleet config set triage_interval_minutes=30` |
| `gc_retention_days` | `int` | `30` | Days before closed tasks archive; 0 disables archiving. | `fleet config set gc_retention_days=7` |
| `gc_archive_days` | `int` | `90` | Days before archives delete permanently; 0 disables purging. | `fleet config set gc_archive_days=30` |
| `observer_max_followups` | `int` | `10` | Max follow-up tasks opened per observer validation round. | `fleet config set observer_max_followups=5` |
| `observer_max_rounds` | `int` | `3` | Max partial observer rounds before human review. | `fleet config set observer_max_rounds=5` |
| `job_gate` | `bool` | `true` | Ask approval before a job spawns its planned children. | `fleet config set job_gate=false` |
| `job_child_coder` | `str` | `"claude"` | Default coder for job-spawned child tasks. | `fleet config set job_child_coder=opencode` |
| `job_child_model` | `str` | `"sonnet"` | Default model for job-spawned child tasks. | `fleet config set job_child_model=opus` |
| `job_max_children` | `int` | `30` | Max children one job phase may spawn. | `fleet config set job_max_children=10` |
| `job_max_phase_attempts` | `int` | `2` | Max research/design attempts before a job blocks. | `fleet config set job_max_phase_attempts=3` |
| `serve_cors_origins` | `list[str]` | `[]` | Browser origins allowed cross-origin; empty is same-origin only. | `fleet config set serve_cors_origins=https://fleet.example.com` |
| `serve_host` | `str` | `"0.0.0.0"` | UI server bind address; 0.0.0.0 exposes LAN, 127.0.0.1 local only. | `fleet config set serve_host=127.0.0.1` |
| `serve_port` | `int` | `7890` | UI server port. | `fleet config set serve_port=8080` |
<!-- END GENERATED:SETTINGS -->

## Environment variables

Every `os.environ` read in `src/fleet`: name, who reads it, default, purpose.
A test (`tests/test_config_docs.py`) scans the env reads and asserts each one
appears here.

| Name | Read by | Default | Purpose |
|---|---|---|---|
| `FLEET_HOME` | `state/paths.py` | `~/.fleet` | Fleet home root: beads DB, `runtime.toml`, tasks, logs. |
| `FLEET_API_TOKEN` | `serve/auth.py` | `""` (open) | Bearer token required on the API (`Authorization: Bearer …`) and `?token=` on WebSockets. |
| `TELEGRAM_BOT_TOKEN` | `cli/telegram_setup.py`, `cli/telegram.py`, `serve/state.py` | `""` | Bot token for Telegram notifications and inbound commands. |
| `ASK_HUMAN_DB` | `integrations/ask_human/store.py` | `<fleet_home>/ask_human/questions.db` | Override path of the shared ask_human questions database. |
| `FLEET_ROOT` | `integrations/mcp_servers.py` | auto-detected repo root | Anchors `uv --directory` so MCP servers run this checkout's code. |
| `FLEET_TASK_DIR` | `integrations/ask_human/server.py` | (none) | Derives the agent id when the MCP server runs without one. |
| `FLEET_TASK_ID` | set by `coders/env.py` for every coder child | (set per spawn) | Task id handed to coder subprocesses with `FLEET_TASK_DIR`. |
| `FLEET_WEBFETCH_MODEL` | `integrations/web_fetch/server.py` | first model the endpoint reports | Model used by the `web_fetch` MCP server. |
| `FLEET_WEBFETCH_OLLAMA_URL` | `integrations/web_fetch/server.py` | `http://127.0.0.1:11434` | Ollama endpoint used by the `web_fetch` MCP server. |
| `OPENCODE_LOG_FILE` | `coders/settings.py` | `~/.local/share/opencode/log/opencode.log` | Where the opencode CLI writes its log. |
| `PI_CODING_AGENT_DIR` | `coders/settings.py` | `~/.pi/agent` | Directory where pi reads `models.json`. |

## Tunables

Behavioural constants nobody should tune blind: cadences, timeouts, retry
bounds, API caps. All live in `src/fleet/core/limits.py` and never change at
runtime (unlike Settings, they need a code change + `fleet run restart`).

<!-- BEGIN GENERATED:TUNABLES -->
| Name | Value | Description |
|---|---|---|
| `LOG_ROOT` | `'logging'` | Subdirectory of FLEET_HOME holding daemon logs. |
| `LOG_ROTATE_BYTES` | `20971520` | Rotate a daemon log once it reaches this size. |
| `LOG_ROTATE_KEEP` | `5` | Numbered backups kept per rotated daemon log. |
| `CONFIG_POLL_INTERVAL_SEC` | `5` | How often the supervisor re-reads runtime.toml. |
| `CLAIM_POLL_INTERVAL_SEC` | `5` | How often the claim service polls the queue. |
| `SCHEDULER_TICK_SEC` | `30` | Scheduler tick; cron resolution is one minute. |
| `SHUTDOWN_GRACE_SEC` | `30` | SIGTERM grace before shutdown escalates to SIGKILL. |
| `RATE_LIMIT_DEFAULT_SLEEP_SEC` | `300` | Wait before retrying a rate-limited attempt. |
| `STATUS_LOG_INTERVAL_SEC` | `30` | Heartbeat lines between supervisor status logs. |
| `HEARTBEAT_SEC` | `30` | Attempt lease heartbeat rewrite cadence. |
| `LEASE_RECONCILE_INTERVAL_SEC` | `60` | How often stale attempt leases are reclaimed. |
| `GC_INTERVAL_SEC` | `86400` | Retention pass cadence after the startup pass. |
| `PROBE_INTERVAL_SEC` | `30` | Health-probe tick for running coder sessions. |
| `PROBE_SILENCE_SEC` | `60` | Silence that marks a session as possibly stuck. |
| `FAILURE_MAX_ROUNDS` | `3` | Consecutive failures before a task blocks. |
| `STALL_MAX_ROUNDS` | `2` | Consecutive stall kills before a task blocks. |
| `CONTEXT_MAX_ROUNDS` | `3` | Consecutive context-pressure ends before a task blocks. |
| `PARTIAL_MAX_ROUNDS` | `5` | Consecutive partial outcomes before a task blocks. |
| `NOCLOSE_MAX_ROUNDS` | `3` | Consecutive no-close exits before a task blocks. |
| `RATE_LIMIT_PROBE_SILENCE_SEC` | `300` | Silence giving up on a rate-limited session. |
| `BD_TIMEOUT_SEC` | `60` | Subprocess ceiling for every bd CLI call. |
| `GIT_TIMEOUT_SEC` | `120` | Subprocess ceiling for every git call. |
| `SUBPROCESS_TIMEOUT_SEC` | `60` | Default ceiling for other subprocess.run calls. |
| `MAX_EVENT_PAGE` | `500` | Row cap per whole-task event page request. |
| `CLOSED_TASKS_DEFAULT` | `300` | Default rows for the closed-tasks window. |
| `CLOSED_TASKS_MAX` | `2000` | Max rows for the closed-tasks window. |
| `SEARCH_LIMIT_DEFAULT` | `20` | Default hits per search request. |
| `SEARCH_LIMIT_MAX` | `100` | Max hits per search request. |
| `ANALYTICS_DAYS_DEFAULT` | `7` | Default trailing window in days for analytics. |
| `ANALYTICS_DAYS_MAX` | `365` | Max trailing window in days for analytics. |
| `SERVE_WATCH_INTERVAL_SEC` | `0.2` | Task-dir rescan cadence of the event watcher. |
| `QUESTION_POLL_SEC` | `2.0` | Idle tick between Telegram notify rounds. |
| `QUESTION_BACKOFF_MAX_SEC` | `60.0` | Backoff ceiling after Telegram failures. |
| `WS_REPLAY_LINES` | `50` | Replay window for in-progress tasks on serve restart. |
<!-- END GENERATED:TUNABLES -->

### Other cadences

Constants with the same spirit that live next to the code using them:

| Name | Location | Value | Purpose |
|---|---|---|---|
| `STARTUP_WINDOW_SEC` | `observability/daemon.py` | `3.0` | Daemon start liveness window: `start()` reports alive only if the child survives the whole window. |
| `COMPACT_TIMEOUT_SEC` | `workers/compact.py` | `180` | Ceiling for the cheap compaction model call. |
| `POLL_TIMEOUT_SEC` / `DISCOVERY_ROUNDS` | `integrations/telegram/setup.py` | `5` / `8` | Long-poll timeout and round count for chat-ID discovery. |
| `POLL` | `ui/src/shared/poll.ts` | `fast 3000` / `normal 5000` / `slow 30000` ms | react-query refetch cadences, paused while the events socket is connected. |
