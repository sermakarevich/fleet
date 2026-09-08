LOG_ROOT = "logging"

CONFIG_POLL_INTERVAL_SEC: int = 5
CLAIM_POLL_INTERVAL_SEC: int = 5
SHUTDOWN_GRACE_SEC: int = 30
RATE_LIMIT_DEFAULT_SLEEP_SEC: int = 300
STATUS_LOG_INTERVAL_SEC: int = 30
# Lease heartbeat: while a worker attempt runs, workers/llm_session.py
# rewrites run.json every HEARTBEAT_SEC with heartbeat_at/lease_until
# (lease_until = now + 3 * HEARTBEAT_SEC). A lease counts as stale only
# when it has been past for more than one full HEARTBEAT_SEC, so a single
# slow event-loop tick can never trigger a reclaim.
HEARTBEAT_SEC: int = 30
LEASE_RECONCILE_INTERVAL_SEC: int = 60
# Retention (gc) pass: archive closed tasks, purge old archives, drop
# stale worktrees. Runs once at supervisor startup, then on this cadence.
GC_INTERVAL_SEC: int = 86400
PROBE_INTERVAL_SEC: int = 30
PROBE_SILENCE_SEC: int = 60
# opencode retries provider rate limits itself with growing back-off; streaks
# almost always clear within ~90 s. Only give up on a rate-limited session after
# this much silence, otherwise the probe kills sessions that were about to recover.
RATE_LIMIT_PROBE_SILENCE_SEC: int = 300
