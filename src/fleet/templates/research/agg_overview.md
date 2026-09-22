<!-- placeholders: {{target}} {{topic}} {{focus}} -->
Write the topic-level overview for the research topic `{{topic}}`.

Focus (what this research must answer): `{{focus}}`.

Read ONLY `{{target}}/topics/*/digest.md` and `{{target}}/sources.md`. Read
nothing else: no source folders beyond what those files say, no wiki pages,
no raw sources, never the web.

Write `{{target}}/overview.md` with: `# {{topic}}` - `**Research:** <n>
sources, <date range>, focus: {{focus}}` - `## Human Readable TL;DR` (3-5
plain sentences with analogies) - `## TL;DR` - `## What is established` -
`## What is contested` (one line each, link to `disagreements.md`) -
`## What is open` (link to `open_questions.md`) - `## How to read this
folder`. Flowing paragraphs, never one sentence per line.

Read only the files named above. Never fetch the web or read raw sources. Do not run git — the knowledge base syncs itself. Write $FLEET_TASK_DIR/RESULT.json as the protocol says. Do not close the bead yourself.
