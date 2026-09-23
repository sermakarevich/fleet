<!-- placeholders: {{target}} {{topic}} {{focus}} {{lenses}} {{topics}} -->
Write the hub index for the research topic `{{topic}}` and finalise the ledger.

Topic slugs (space-separated): `{{topics}}`. Lenses (space-separated): `{{lenses}}`.
Focus (verbatim into the front-matter): `{{focus}}`.

Read ONLY `{{target}}/*.md`, `{{target}}/topics/*/digest.md`,
`{{target}}/sources.md`, `{{target}}/lenses/*.md`, and
`$FLEET_TASK_DIR/artifacts/candidates.json`. Read nothing else:
no source folders beyond what those files say, no wiki pages, no raw
sources, never the web.

Write `{{target}}/index.md`: front-matter with `type: Research`, `title`,
`description` (one sentence), `generated` (`by: claude/<model-id>, at:
<ISO-8601 UTC>`), `focus` (verbatim), `topics` (the slugs), `lenses`,
`sources` counts (`processed`, `in_kb`, `unreachable`), `runs` (append a row
`{ at: <ISO date>, added: <n> }`), and `tags` (2-5 lowercase); then the body
sections `## How to work through this`, `## Cross-cutting`,
`## Lenses` (`| lens | for |`), `## Sub-topics`
(`| sub-topic | in one sentence | sources |`), and `## Sources`
(`| source | kind | folder |`).

Own the `{{target}}/sources.md` ledger: when the file does not exist yet,
create it with exactly this header line first:

```
| # | status | kind | score | source | sub-topic | folder | origin |
```

Then ensure it lists every shortlisted source from `candidates.json` (one
row per source; never rewrite rows written for other sources, only append
missing ones): fresh sources with `status=processed` and the folder
`research_topics/<topic>/<Name>` where they were filed by their summarise
file stage; already-in-the-KB sources with `status=in_kb` and their
`origin` folder. A shortlisted source the `Source resolution` section
appended to this bead at spawn marks skipped, or that has no
folder on disk and no digest row, is `status=unreachable` with the reason
where the folder would go — never `pending`. A missing or skipped source
is a ledger row, never a reason to return partial: write every row the
evidence supports and finish.

Append one bullet (folder link + one-line description of `{{topic}}`) to
`/Users/sergii/.ai/knowledge/research/index.md`, registering this topic.
That index file is the only file outside `{{target}}` this task may write
(besides its own `$FLEET_TASK_DIR/RESULT.json`).

Read only the files named above. Never fetch the web or read raw sources. Do not run git — the knowledge base syncs itself. Write $FLEET_TASK_DIR/RESULT.json as the protocol says. Do not close the bead yourself.
