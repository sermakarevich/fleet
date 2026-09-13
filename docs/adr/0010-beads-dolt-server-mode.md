# ADR 0010: beads Dolt server mode to remove per-process lock contention

Status: Proposed
Date: 2026-09-13

> Note on numbering: `docs/adr/0010-workflow-inputs-and-step-outputs.md` already
> occupies number 0010. This file is named per the task spec that created it
> (fleet-a85k2); renumber to the next free slot (currently 0013) when this ADR
> is promoted out of "Proposed", to avoid two ADRs sharing a number.

## Context

`~/.fleet/.beads/metadata.json` currently has:

```json
{
  "database": "dolt",
  "backend": "dolt",
  "dolt_mode": "embedded",
  "dolt_database": "fleet",
  "project_id": "21309946-9e8c-4bae-b27f-8e51062fd06c"
}
```

In `embedded` mode every `bd` invocation opens the Dolt storage engine
in-process and takes the on-disk lock at
`.beads/embeddeddolt/fleet/.dolt/noms/LOCK`. Under fleet's load (supervisor
polling, serve API snapshotting, many concurrent workers each shelling out to
`bd`), that per-process lock acquisition is unfair: measured `bd list --all
--limit 0 --json` calls in this session took **17–25 s** each when run
back-to-back against the live `~/.fleet` database (confirms the problem
statement's "1.4 s vs 82 s" swings — the queue is not FIFO and some callers
starve).

`bd dolt status` on the live repo confirms the current mode:

```
Dolt engine: embedded (in-process, no server)
  Data: /Users/sergii/.fleet/.beads/embeddeddolt
```

beads 1.0.4 supports a **server mode**: a single long-running `dolt
sql-server` process that all `bd` invocations talk to over MySQL wire
protocol instead of each opening the storage engine directly. This removes
the in-process lock entirely — contention becomes ordinary SQL connection
queuing inside one server, not N processes fighting over a filesystem lock.

## 1. How bd 1.0.4 switches to server mode

From `bd dolt --help` / `bd dolt set --help` / `bd dolt start --help` / `bd
config --help` (all read-only, no mutating commands were run):

- `bd dolt status` reports one of three engine states:
  - **embedded** — in-process, data dir shown, no server.
  - **beads-managed (local) server** — `bd dolt start` launches a
    `dolt sql-server` for the current project; PID/port/data-dir are stored
    under `.beads/`. `bd dolt stop` stops it; auto-started transparently by
    `bd` on demand if not already running (per `bd dolt start --help`: "The
    server auto-starts transparently when needed... manual start is rarely
    required").
  - **externally-hosted server** — `dolt_mode=server` with a remote
    `dolt_server_host` configured; `bd dolt status` pings the endpoint via
    SQL and reports reachability/version/database instead of a local PID.
- Switching mode is done via `bd dolt set <key> <value>`, not a single
  `dolt_mode` flag exposed directly on the CLI surface — `bd dolt set host
  <host>` (plus optionally `port`, `database`, `user`, `data-dir`) is what
  flips a project from embedded to server-backed. `--update-config` also
  persists the values to `config.yaml` for team-wide defaults; without it,
  the value is written only to `metadata.json` for the local project.
- Config keys settable: `database`, `host` (default `127.0.0.1`), `port`
  (auto-detected per project; override with `bd dolt set port <N>`), `user`
  (default `root`), `data-dir` (default `.beads/dolt`).
- **Where it lives**: per-project runtime state (mode, PID, port, data dir)
  is in `.beads/metadata.json` (local, not meant to be shared/team-wide).
  Values written with `--update-config` additionally land in `config.yaml`
  (checked-in, team-wide defaults). For a fully local machine setup like
  `~/.fleet` (single user, single machine, no team to share config with),
  the plain `bd dolt set host 127.0.0.1 --update-config` (or just letting
  `bd dolt start` run once, which appears to auto-manage `metadata.json`)
  is sufficient — there's no cross-machine team to coordinate via
  `config.yaml`.
- `bd dolt test` — read-only connection test against whatever server config
  is currently set; useful to verify before/after a mode switch without
  mutating anything.
- `bd dolt show` — read-only, prints current Dolt configuration plus a live
  connection test.

## 2. Who starts the server, and when

Two options, per the task:

**Option A — dedicated launchd agent (`com.fleet.dolt.plist`).**
Given `~/Library/LaunchAgents/com.fleet.run.plist` and
`com.fleet.serve.plist` already exist and follow an established pattern
(KeepAlive, RunAtLoad, ThrottleInterval, logs under `~/.fleet/logs/`), a
third plist for the Dolt server would look like:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>EnvironmentVariables</key>
	<dict>
		<key>HOME</key>
		<string>/Users/sergii</string>
		<key>PATH</key>
		<string>/Users/sergii/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
	</dict>
	<key>KeepAlive</key>
	<true/>
	<key>Label</key>
	<string>com.fleet.dolt</string>
	<key>ProcessType</key>
	<string>Background</string>
	<key>ProgramArguments</key>
	<array>
		<string>/Users/sergii/.local/bin/bd</string>
		<string>dolt</string>
		<string>start</string>
		<string>-C</string>
		<string>/Users/sergii/.fleet</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>StandardErrorPath</key>
	<string>/Users/sergii/.fleet/logs/dolt-launchd.log</string>
	<key>StandardOutPath</key>
	<string>/Users/sergii/.fleet/logs/dolt-launchd.log</string>
	<key>ThrottleInterval</key>
	<integer>30</integer>
</dict>
</plist>
```

(`bd dolt start` backgrounds itself and writes its own PID file, so
`KeepAlive` here mainly protects against the launchd wrapper process dying;
the actual server's own PID/log management is internal to `bd`.)

**Option B — let the fleet supervisor start it.** Since `bd dolt start` is
described as auto-starting transparently on first use by *any* `bd`
invocation ("manual start is rarely required"), no dedicated process is
strictly needed at all: the first `bd` call from the supervisor, serve API,
or a worker would transparently spin the server up. The supervisor doesn't
need new code for this.

**Recommendation: Option B (rely on bd's built-in auto-start), no plist.**
It is simpler (zero new moving parts, zero new plist to maintain/monitor),
matches how `bd dolt start --help` says the feature is intended to be used,
and avoids a race where a dedicated launchd agent and an auto-start from a
supervisor/worker both try to bind the same port at boot. A dedicated plist
(Option A) would only be worth the extra complexity if we needed guaranteed
warm-start before the first `bd` call (e.g. to avoid a first-request latency
spike) — not a documented requirement here.

## 3. Failure modes

- **Server not running, mode = local/beads-managed**: per `bd dolt start
  --help`, `bd` auto-starts the server transparently on first use. Expected
  behavior is a one-time cold-start delay on the first call after the
  server was down, then normal latency for all subsequent calls (shared
  connection pool instead of per-process lock).
- **Server not running, mode = server (remote host)**: `bd dolt status`
  says it "pings the configured endpoint via SQL and reports reachability" —
  implying `bd` does NOT auto-start a remote server (it can't; it isn't
  local). A remote/externally-hosted server that's down would surface as a
  connection error on the next `bd` call. This matters only if we ever point
  `dolt_server_host` at a non-`127.0.0.1` remote; for a single-machine
  `~/.fleet` setup we'd stay on the local/beads-managed flavor, so this
  failure mode doesn't currently apply.
- **`fleet.beads.client.try_run_bd`**: reviewed `src/fleet/beads/client.py`
  — it wraps every `bd` call with a hard subprocess `timeout` (`BD_TIMEOUT_SEC`)
  and raises `BdError` only on a missing binary or a timeout; there is no
  server health check or fallback logic today, and none is needed for this
  change — a down/cold local server just adds first-call latency inside the
  same timeout budget already in place. No code change required in
  `client.py` for Option B.
- **grep for `embedded`/`dolt` assumptions in `src/fleet` (excl.
  `src/fleet/ui`)**:
  - `src/fleet/beads/create_args.py:5` — a single unrelated hit, the English
    word "embedded" in a comment about metadata, not a Dolt-mode assumption.
  - `src/fleet/cli/beads.py:32` — passes through the `dolt-auto-commit` CLI
    flag; mode-agnostic, works the same in embedded or server mode.
  - No other files reference `dolt` or `embedded` in `src/fleet`. **Fleet's
    own code has no embedded-mode assumption to unwind** — the switch is
    entirely a `bd`/`metadata.json` configuration change, not a fleet code
    change.

## 4. Migration steps and rollback

Migration (not executed as part of this spike; for the follow-up task):

1. Confirm no in-flight fleet work: `fleet run status` / `bd ready` clean.
2. `bd dolt set host 127.0.0.1 --update-config` (or run `bd dolt start` once
   and let it manage `metadata.json`) from `~/.fleet`.
3. `bd dolt test` to confirm connectivity.
4. `bd dolt status` to confirm engine reports a running local server, not
   `embedded`.
5. Time `bd list --all --limit 0 --json` 5x while the supervisor is running
   normally (`for i in 1 2 3 4 5; do time bd list --all --limit 0 --json
   >/dev/null; done` from `~/.fleet`), compare against the embedded-mode
   baseline captured in this spike (17–25 s under load).
6. Watch `~/.fleet/logs/` and `bd dolt status` for a day under normal
   supervisor/serve/worker load before declaring it stable.

Rollback: `bd dolt set` back to the embedded defaults is not a single
documented switch in the `--help` output (server mode is additive, keyed on
`host`/`port`/`data-dir`); the safe rollback is to stop the server
(`bd dolt stop`) and restore the original `metadata.json` (`dolt_mode:
embedded`, no host/port/data-dir overrides) from git/backup, since
`metadata.json` is a small local file worth snapshotting before step 2.

## 5. Sizing note: `bd gc` / `bd flatten`

The task states `bd gc --dry-run` (not run in this spike, per the
read-only constraint) shows **2791 Dolt commits** in the `~/.fleet` database.
Per `bd flatten --help`, `bd flatten --dry-run` "preview[s] commit count and
disk usage" and full flatten "squashes ALL Dolt commit history into a single
commit" — it is a storage-size and irreversible-history-loss lever, not a
concurrency lever: flattening reduces how much history the embedded engine
has to open (`Data:` directory size affects embedded startup file scans, per
`bd dolt status`'s description of embedded mode reporting the on-disk data
directory), so it likely reduces **embedded** open time. It does **not**
address the actual bug in this spike, which is process-level lock fairness,
not database size. `bd compact --help` describes a less destructive
alternative (squash commits older than N days, keep recent ones
cherry-picked) that would also shrink the working set without discarding
recent history — worth a look for storage hygiene, but separately from this
ADR's server-mode decision.

## Recommendation

**Go**, with Option B (rely on `bd`'s transparent auto-start under
server/local-managed mode, no new launchd plist). Rationale:
- Zero fleet code changes needed — `client.py`'s `try_run_bd` already
  timeouts/retries generically, and grep found no embedded-mode
  assumptions elsewhere in `src/fleet` (excl. UI).
- Directly targets the measured root cause (per-process embedded lock
  queue unfairness — 17–25 s single-call latency observed live), rather
  than the storage-size angle (`bd flatten`/`bd compact`), which is a
  separate, complementary optimization.
- Migration is a metadata/config change (`bd dolt set` + `--update-config`),
  fully reversible by restoring `metadata.json`, with a clear before/after
  measurement (`bd list --all --limit 0 --json` timing) to validate.
- Follow-up task should implement the migration steps in section 4 and
  re-measure; this ADR is a spike/proposal only, no code or config was
  changed as part of it.
