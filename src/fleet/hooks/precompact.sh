#!/bin/sh
# Fleet PreCompact hook — signals context pressure to the supervisor.
# Invoked by Claude Code's PreCompact hook event before auto-compaction.
# Exits 2 to halt the agent; the TaskRunner detects the flag file after exit.

if [ -z "${FLEET_TASK_DIR:-}" ]; then
    echo "fleet precompact hook: FLEET_TASK_DIR not set; skipping context-pressure signal" >&2
    exit 0
fi

mkdir -p "${FLEET_TASK_DIR}"
touch "${FLEET_TASK_DIR}/.context_pressure"
exit 2
