#!/usr/bin/env bash
# Fleet context-checkpoint hook (PostToolUse): when the runner's context usage
# crosses the checkpoint threshold it touches
# $FLEET_ATTEMPT_DIR/.checkpoint_requested. This hook then nudges the model to
# wrap up (update HANDOFF.md, commit WIP, write partial RESULT.json, exit 0)
# exactly once per attempt (guarded by .checkpoint_sent).
set -euo pipefail
attempt_dir="${FLEET_ATTEMPT_DIR:-}"
if [[ -z "$attempt_dir" ]]; then
    exit 0
fi
if [[ ! -f "$attempt_dir/.checkpoint_requested" ]]; then
    exit 0
fi
if [[ -f "$attempt_dir/.checkpoint_sent" ]]; then
    exit 0
fi
touch "$attempt_dir/.checkpoint_sent"
msg="Context is nearly full. Stop new work now: update HANDOFF.md (Done / In flight / Next / Do-not-redo), commit work in progress with a WIP message, write RESULT.json with status=partial and next_step, then exit 0."
# Hook contract: PostToolUse hooks inject guidance via hookSpecificOutput.additionalContext.
if command -v python3 &>/dev/null; then
    context_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$msg")"
else
    escaped="$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    context_json="\"$escaped\""
fi
printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":%s}}\n' "$context_json"
exit 0
