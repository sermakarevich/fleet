# Fleet Task Protocol

You run headless under a fleet supervisor. It never passes `--resume`; the files in `$FLEET_TASK_DIR` are your only continuation state. Follow this every invocation.

## On every fresh start, read these files first

`ls "$FLEET_ARTIFACT_DIR"`, then read any existing `PLAN_AND_STATUS.md` and `KNOWLEDGE.md`. 

`$FLEET_TASK_DIR/` layout: 
- `task.json` - metadata 
- `artifacts/` - those `.md` files plus any outputs you write
- `events.jsonl` - use only tail and in case it is critically required
- `log.jsonl` - use only tail and in case it is critically required
- `log.stderr` - use only tail and in case it is critically required

## Write progress under `$FLEET_ARTIFACT_DIR` as you go

- **PLAN_AND_STATUS.md** — one-paragraph restatement, numbered plan (with assumptions / open questions), Status block (`in_progress` | `blocked` | `completed`) listing Done / In progress / Blocked. Overwrite status; never delete prior content.
- **KNOWLEDGE.md** (append-only) — surface area (files + role), invariants, gotchas.

## When done

Finalize `PLAN_AND_STATUS.md` (In progress → Done), run `fleet bd close <task_id> --reason "<summary>"`, exit 0.

## When blocked — ask_human protocol

`AskUserQuestion` is denied by a PreToolUse hook; use this instead.

Call the `mcp__ask_human__ask_human_question` MCP tool with your question. Describe briefly and clearly the problem you are working on and ask clear question. 

