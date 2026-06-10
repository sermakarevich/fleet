#!/usr/bin/env bash
# Fleet: block AskUserQuestion in headless mode.
# Use the Q&A.md protocol instead (see INSTRUCTION.md).
echo "AskUserQuestion blocked — fleet runs headless. Use the mcp__ask_human__ask_human_question MCP tool instead." >&2
exit 2
