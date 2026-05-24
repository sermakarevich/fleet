#!/usr/bin/env bash
# Fleet: block AskUserQuestion in headless mode.
# Use the Q&A.md protocol instead (see INSTRUCTION.md).
echo "AskUserQuestion blocked — fleet runs headless. Write to Q\&A.md and exit 0." >&2
exit 2
