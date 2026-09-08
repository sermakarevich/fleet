#!/usr/bin/env bash
# Fleet pre-compact hook: save task memory context before the context window compresses.
set -euo pipefail
if [[ -n "${FLEET_ATTEMPT_DIR:-}" ]]; then
    touch "$FLEET_ATTEMPT_DIR/.compacted" 2>/dev/null || true
fi
if command -v bd &>/dev/null; then
    bd prime 2>/dev/null || true
fi
