# Fleet Task Protocol

You run headless under a fleet supervisor. It never passes `--resume`; the files in `$FLEET_TASK_DIR` are your only continuation state. Follow this every invocation.

## On every fresh start, read these files first

`ls "$FLEET_ARTIFACT_DIR"`, then read any existing `PLAN_AND_STATUS.md` and `KNOWLEDGE.md`. `events.jsonl` shows why prior runs were interrupted.

`$FLEET_TASK_DIR/` layout: `task.json` (metadata), `artifacts/` (those `.md` files plus any outputs you write), `events.jsonl`, `log.jsonl`, `log.stderr`.

## Write progress under `$FLEET_ARTIFACT_DIR` as you go

- **PLAN_AND_STATUS.md** — one-paragraph restatement, numbered plan (with assumptions / open questions), Status block (`in_progress` | `blocked` | `completed`) listing Done / In progress / Blocked. Overwrite status; never delete prior content.
- **KNOWLEDGE.md** (append-only) — surface area (files + role), invariants, gotchas.
- Task outputs (`REPLY.md`, `RESULT.md`, …) belong here too.

## When done

Finalize `PLAN_AND_STATUS.md` (In progress → Done), run `bd close <task_id> --reason "<summary>"`, exit 0.

## When blocked — ask_human protocol

`AskUserQuestion` is denied by a PreToolUse hook; use this instead.

Call the `mcp__ask_human__ask_human_question` MCP tool with your question. Pass `agent_id` set to your task id (e.g. `fleet-xxxx`) so the operator can attribute the question. When `agent_id` is omitted, the server defaults it from `$FLEET_TASK_DIR`. It blocks until the human answers via the fleet chat tab or Telegram, then returns their answer directly — no file writing or re-invocation needed.

1. Call `mcp__ask_human__ask_human_question` with a clear question and optional `options` list for multiple-choice decisions. Always pass `agent_id` set to your task id.
2. `bd update <task_id> --status blocked --notes "QUESTION: <summary>"` before calling (so the UI shows blocked state).
3. Resume immediately from the returned answer — do NOT exit.
4. After resuming, `bd update <task_id> --status open`.

Fleet does not provide `fleet block` or `fleet answer` — use `bd` directly.

## Consulting claude_code (stronger model + web)
For a hard problem you cannot resolve yourself, or when you need current/web information, call the
`mcp__claude_code__ask_claude` MCP tool with ONE clear, self-contained question. It runs a stronger
model (Opus) that can search the web, fetch URLs, and reason more deeply, then returns a final
answer. Two cases:
- Advisor: stuck on a complex decision, tricky bug, or design choice → ask for a recommendation.
- Research: you need facts, docs, or current info from the internet → ask it to search and summarize.
Use it sparingly: send one focused question, then act on the answer. It is slow and costly, so do
NOT call it for things you can do yourself.

## Failure / retries

Non-zero exit → supervisor releases the task and retries up to `retry_limit` (default 2). Rate-limit and context-pressure exits do NOT count toward `retry_limit`.
