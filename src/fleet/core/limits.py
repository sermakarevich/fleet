LOG_ROOT = "logging"

RETRY_LIMIT: int = 2
NOCLOSE_LIMIT: int = 12
CONFIG_POLL_INTERVAL_SEC: int = 5
CLAIM_POLL_INTERVAL_SEC: int = 5
SHUTDOWN_GRACE_SEC: int = 30
RATE_LIMIT_DEFAULT_SLEEP_SEC: int = 300
STATUS_LOG_INTERVAL_SEC: int = 30
PROBE_INTERVAL_SEC: int = 30
PROBE_SILENCE_SEC: int = 60
# opencode retries provider rate limits itself with growing back-off; streaks
# almost always clear within ~90 s. Only give up on a rate-limited session after
# this much silence, otherwise the probe kills sessions that were about to recover.
RATE_LIMIT_PROBE_SILENCE_SEC: int = 300
