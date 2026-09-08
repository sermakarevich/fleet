# Fleet Task Protocol — shared rules

You run headless under a fleet supervisor. It never passes `--resume`; the
files in `$FLEET_TASK_DIR` are your only continuation state. Never read
`events.jsonl`, `log.jsonl`, `log.stderr`, or anything under `attempts/` —
they are for humans and tooling, not for you.

`$FLEET_TASK_DIR/` layout:
- `task.json` - metadata
- `artifacts/` - `RESULT.json`, `PLAN.md`, `HANDOFF.md`, `KNOWLEDGE.md`, `outputs/`
- `events.jsonl`, `log.jsonl`, `log.stderr`, `attempts/` - do not read these

## Write progress under `$FLEET_ARTIFACT_DIR` as you go

- **PLAN.md** — one-paragraph restatement, numbered plan, assumptions / open questions. Written once, updated rarely.
- **HANDOFF.md** — overwrite completely each attempt, hard cap 2 KB. Done / in flight / next / do-not-redo — this is what the next attempt reads first.
- **KNOWLEDGE.md** — curated durable facts (surface area, invariants, gotchas). Rewrite when stale; keep it small (~4 KB), not append-only.
- **outputs/** — real deliverables (reports, data) referenced from RESULT.json.

Commit small and often as you make progress; do not save all commits for the end.

## Before you exit, every attempt

Write `artifacts/RESULT.json`:

```json
{"schema": 1, "status": "done|partial|blocked", "summary": "<1-3 sentences>",
 "commits": ["<sha>", ...], "tests": {"command": "...", "passed": true|false|null},
 "open_questions": ["..."], "next_step": "<what the next attempt should do first, or empty>",
 "blocked_reason": "<only when status=blocked>"}
```

- `status=done`: fleet closes the bead itself using your `summary`. You may still run `fleet bd close <task_id> --reason "<summary>"` yourself; if you already closed it, fleet no-ops.
- `status=partial`: fleet re-queues the task; `next_step` tells the next attempt what to do first.
- `status=blocked`: the bead is set to blocked using `blocked_reason`.

Update `HANDOFF.md` before exiting, whatever the outcome. Exit 0 unless something actually crashed.

## When blocked — ask_human protocol

`AskUserQuestion` is denied by a PreToolUse hook; use this instead.

Call the `mcp__ask_human__ask_human_question` MCP tool with your question. Describe briefly and clearly the problem you are working on and ask clear question.
