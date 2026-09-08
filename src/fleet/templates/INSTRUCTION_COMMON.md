# Fleet Task Protocol — shared rules

You run headless under a fleet supervisor. It never passes `--resume`; the
files in `$FLEET_TASK_DIR` are your only continuation state. Never read
`events.jsonl`, `log.jsonl`, `log.stderr`, or anything under `attempts/` —
they are for humans and tooling, not for you.

`$FLEET_TASK_DIR/` layout:
- `task.json` - metadata
- `STATE.md` - worker memory: `## Plan`, `## Done`, `## In flight`, `## Next`, `## Facts`
- `RESULT.json` - your declared outcome (present only between your exit and reap)
- `outputs/` - real deliverables (reports, data) referenced from RESULT.json
- `events.jsonl`, `log.jsonl`, `log.stderr`, `attempts/` - do not read these

## Write progress to `$FLEET_TASK_DIR/STATE.md` as you go

- Read `STATE.md` first, every attempt. It is the only history you need.
- Rewrite it completely before exiting (hard cap 6 KB): move finished
  items to `## Done`, keep durable findings in `## Facts`, and leave the
  single next action in `## Next` so the next attempt knows where to pick up.
- Commit small and often as you make progress; do not save all commits for the end.

## Before you exit, every attempt

Write `$FLEET_TASK_DIR/RESULT.json`:

```json
{"schema": 1, "status": "done|partial|blocked", "summary": "<1-3 sentences>",
 "commits": ["<sha>", ...], "tests": {"command": "...", "passed": true|false|null},
 "open_questions": ["..."], "next_step": "<what the next attempt should do first, or empty>",
 "blocked_reason": "<only when status=blocked>"}
```

- `status=done`: fleet closes the bead itself using your `summary`. You may still run `fleet bd close <task_id> --reason "<summary>"` yourself; if you already closed it, fleet no-ops.
- `status=partial`: fleet re-queues the task; `next_step` tells the next attempt what to do first.
- `status=blocked`: the bead is set to blocked using `blocked_reason`.

Update `STATE.md` before exiting, whatever the outcome. Exit 0 unless something actually crashed.

## When blocked — ask_human protocol

`AskUserQuestion` is denied by a PreToolUse hook; use this instead.

Call the `mcp__ask_human__ask_human_question` MCP tool with your question. Describe briefly and clearly the problem you are working on and ask clear question. The tool is always available in fleet workers.
