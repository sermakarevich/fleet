<!-- placeholders: {{url}} {{name}} {{origin}} {{target}} -->
Move one processed source folder into the research target (MOVE, never copy —
every entry has exactly ONE home; papers/ staging must not retain it).

Locate the summary_get folder for `{{url}}`:
- When `{{origin}}` is non-empty, the folder is `{{origin}}` (a source already
  in the knowledge base).
- When `{{origin}}` is empty, search under `/Users/sergii/.ai/knowledge/papers`
  and `/Users/sergii/.ai/knowledge/investment` for the folder whose `index.md`
  front-matter `sources[].resource` matches `{{url}}` (normalised: drop scheme
  and `www.`; for arXiv compare the id; for YouTube compare the video id).
  Fresh research-epic summary_get runs skip their file step, so the folder is
  still in papers/ staging waiting for this move.

Routing (exactly one home):
- Located folder under papers/ staging → its home is now
  `{{target}}/sources/{{name}}/`. MOVE it there (below) and leave nothing
  behind in papers/.
- Located folder under /investment/ or /structured_papers/ (already homed
  outside staging) → do NOT duplicate it. Stop with an error instead of
  copying, so the operator decides (move the home vs reference it). Never
  `cp` a homed entry silently; never leave two folders with the same
  summary.md content.
- Located folder already under `{{target}}/sources/{{name}}/` → already
  moved; verify `test -s` below and finish without moving again.

Move it, keeping the name:

```bash
mv "<located folder>" "{{target}}/sources/{{name}}/"
test -s "{{target}}/sources/{{name}}/index.md"
test ! -e "<located folder>"
```

`test -s` must succeed; if the located folder has no non-empty `index.md`,
stop with an error instead of writing a ledger row. The final
`test ! -e "<located folder>"` must also succeed: the staging path is gone
(MOVE, never copy). When already-moved, both tests pass trivially against
the existing target folder.

Append one row to `{{target}}/sources.md` for `{{name}}`. When the file does
not exist yet, create it with exactly this header line first:

```
| # | status | kind | score | source | sub-topic | folder | origin |
```

The row records `{{url}}`, the folder `sources/{{name}}`, and the origin
(`{{origin}}` when non-empty, else the located summary_get folder). Use
`status=in_kb` when `{{origin}}` is non-empty, else `status=processed`. Never
rewrite rows written for other sources.

Read only the files named above. Never fetch the web or read raw sources. Do not run git — the knowledge base syncs itself. Write $FLEET_TASK_DIR/RESULT.json as the protocol says. Do not close the bead yourself.
