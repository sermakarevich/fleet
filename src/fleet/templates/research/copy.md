<!-- placeholders: {{url}} {{name}} {{origin}} {{target}} -->
Move one processed source folder into the research target (MOVE, never copy —
every entry has exactly ONE home; research/<Name>/ must not retain it).

Locate the summarise folder for `{{url}}`:
- When `{{origin}}` is non-empty, the folder is `{{origin}}` (a source already
  in the knowledge base).
- When `{{origin}}` is empty, search under `/Users/sergii/.ai/knowledge/research`
  and `/Users/sergii/.ai/knowledge/investment` for the folder whose `index.md`
  front-matter `sources[].resource` matches `{{url}}` (normalised: drop scheme
  and `www.`; for arXiv compare the id; for YouTube compare the video id).
  Skip epic hubs while scanning: a folder whose `index.md` front-matter has
  `type: Research` (or that contains a `sources/` subdirectory) holds counts,
  not resources, so it can never match — only entry folders (with
  `source/source.md`) and `sources/*/` subfolders can.
  summarise never files its output, so the folder is still at
  `/Users/sergii/.ai/knowledge/research/<Name>/` waiting for this move.

Routing (exactly one home):
- Located folder directly under research/ → its home is now
  `{{target}}/sources/{{name}}/`. MOVE it there (below) and leave nothing
  behind at research/<Name>/.
- Located folder under /investment/ or /research_topics/ (already homed
  elsewhere) → do NOT duplicate it. Stop with an error instead of
  copying, so the operator decides (move the home vs reference it). Never
  `cp` a homed entry silently; never leave two folders with the same
  summary.md content.
- Located folder already under a DIFFERENT epic's `<other-target>/sources/`
  (not `{{target}}`) → same as above: stop with an error instead of
  duplicating it into this epic, so the operator decides.
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
`test ! -e "<located folder>"` must also succeed: the source path is gone
(MOVE, never copy). When already-moved, both tests pass trivially against
the existing target folder.

Append one row to `{{target}}/sources.md` for `{{name}}`. When the file does
not exist yet, create it with exactly this header line first:

```
| # | status | kind | score | source | sub-topic | folder | origin |
```

The row records `{{url}}`, the folder `sources/{{name}}`, and the origin
(`{{origin}}` when non-empty, else the located summarise folder). Use
`status=in_kb` when `{{origin}}` is non-empty, else `status=processed`. Never
rewrite rows written for other sources.

Read only the files named above. Never fetch the web or read raw sources. Do not run git — the knowledge base syncs itself. Write $FLEET_TASK_DIR/RESULT.json as the protocol says. Do not close the bead yourself.
