<!-- placeholders: {{url}} {{name}} {{origin}} {{target}} -->
Copy one processed source folder into the research target.

Locate the summary_get folder for `{{url}}`:
- When `{{origin}}` is non-empty, the folder is `{{origin}}` (a source already
  in the knowledge base).
- When `{{origin}}` is empty, search under `/Users/sergii/.ai/knowledge/papers`
  and `/Users/sergii/.ai/knowledge/investment` for the folder whose `index.md`
  front-matter `sources[].resource` matches `{{url}}` (normalised: drop scheme
  and `www.`; for arXiv compare the id; for YouTube compare the video id).

Copy it recursively, keeping the name:

```bash
cp -R "<located folder>" "{{target}}/sources/{{name}}/"
test -s "{{target}}/sources/{{name}}/index.md"
```

`test -s` must succeed; if the located folder has no non-empty `index.md`,
stop with an error instead of writing a ledger row.

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
