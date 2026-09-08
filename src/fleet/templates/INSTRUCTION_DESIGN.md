# Fleet Task Protocol — designing a job

From `artifacts/RESEARCH.md` and the goal, write `artifacts/DESIGN.md`
(approach, decisions, order) and `artifacts/tasks.json` matching this
schema:

```json
{"tasks": [{"key": "t1", "title": "...", "body": "...", "cwd": "/abs/or/null", "coder": "claude|null", "model": "sonnet|null", "priority": 1, "depends_on": ["t0"]}]}
```

Each task must be doable by one worker in one sitting on a cheap model;
put shared context in each body; give dependencies only where order
matters (depends_on names sibling keys). If `artifacts/DESIGN_NOTES.md`
exists, address the operator's revision note first. If
`artifacts/DESIGN_ERRORS.md` exists, fix the listed validation errors.
Write RESULT.json with `status="partial"` and `next_step="gate"`.
