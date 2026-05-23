# Fleet Task Protocol

You run headless under a fleet supervisor. It never passes `--resume`; the files in `$FLEET_TASK_DIR` are your only continuation state. Follow this every invocation.

## On every fresh start, read these files first

`ls "$FLEET_ARTIFACT_DIR"`, then read any existing `PLAN_AND_STATUS.md`, `KNOWLEDGE.md`, and `Q&A.md`. A new `## A:` block in `Q&A.md` = the human answered; resume from there. `events.jsonl` shows why prior runs were interrupted.

`$FLEET_TASK_DIR/` layout: `task.json` (metadata), `artifacts/` (those `.md` files plus any outputs you write), `events.jsonl`, `log.jsonl`, `log.stderr`.

## Write progress under `$FLEET_ARTIFACT_DIR` as you go

- **PLAN_AND_STATUS.md** — one-paragraph restatement, numbered plan (with assumptions / open questions), Status block (`in_progress` | `blocked` | `completed`) listing Done / In progress / Blocked. Overwrite status; never delete prior content.
- **KNOWLEDGE.md** (append-only) — surface area (files + role), invariants, gotchas.
- Task outputs (`REPLY.md`, `RESULT.md`, …) belong here too.

## When done

Finalize `PLAN_AND_STATUS.md` (In progress → Done), run `bd close <task_id> --reason "<summary>"`, exit 0.

## When blocked — Q&A protocol

`AskUserQuestion` is denied by a PreToolUse hook; use this instead.

1. Append (never edit prior blocks) to `$FLEET_ARTIFACT_DIR/Q&A.md`:
   ```markdown
   ## Q: <one-line> — <YYYY-MM-DD HH:MM, actor>
   **Context:** <where, file:line>
   **Tried:** <approaches>
   **Need:** <what you need from the user>
   ```
2. `bd update <task_id> --status blocked --notes "QUESTION: <summary>"`
3. Optionally `bd comment <task_id> "<longer context>"`.
4. Point `PLAN_AND_STATUS.md` Blocked at the question.
5. Exit 0. Do NOT close the task.

Fleet does not provide `fleet block` or `fleet answer` — use `bd` directly.

## Resume after a human answer

The human appends `## A:` under your `## Q:` and runs `bd update <task_id> --status open`. Your fresh-start read picks it up — continue from where you stopped, do not restart.

## Failure / retries

Non-zero exit → supervisor releases the task and retries up to `retry_limit` (default 3, configurable in `$FLEET_HOME/runtime.toml`). Rate-limit and context-pressure exits do NOT count toward `retry_limit`.
