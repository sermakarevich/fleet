<!-- placeholders: {{target}} {{topic}} {{focus}} {{lenses}} {{topics}} -->
Write the hub index for the research topic `{{topic}}` and finalise the ledger.

Topic slugs (space-separated): `{{topics}}`. Lenses (space-separated): `{{lenses}}`.
Focus (verbatim into the front-matter): `{{focus}}`.

Read ONLY `{{target}}/*.md`, `{{target}}/topics/*/digest.md`,
`{{target}}/sources.md`, and `{{target}}/lenses/*.md`. Read nothing else:
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

Confirm `{{target}}/sources.md` already lists every processed/in_kb source
(one row per source with the header
`| # | status | kind | score | source | sub-topic | folder | origin |`); do
not rewrite rows written by the copy tasks, only add rows for statuses they
do not cover if any source is missing.

Append one bullet (folder link + one-line description of `{{topic}}`) to
`/Users/sergii/.ai/knowledge/research/index.md`, registering this topic.
That index file is the only file outside `{{target}}` this task may write
(besides its own `$FLEET_TASK_DIR/RESULT.json`).

Read only the files named above. Never fetch the web or read raw sources. Do not run git — the knowledge base syncs itself. Write $FLEET_TASK_DIR/RESULT.json as the protocol says. Do not close the bead yourself.
