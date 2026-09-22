<!-- placeholders: {{target}} {{topic}} {{lens}} {{audience}} -->
Write the `{{lens}}` lens for the research topic `{{topic}}`, read for
`{{audience}}`.

Read ONLY `{{target}}/digest.md` and `{{target}}/topics/*/digest.md`. Read
nothing else: no source folders, no wiki pages, no raw sources, never the
web.

Write `{{target}}/lenses/{{lens}}.md` with: `# {{topic}} -- for {{audience}}`
- `## What this means for you` - `## Decisions this informs` -
`## Risks and unknowns` - `## Where to go deeper` (links into `topics/` and
`sources/`). Same facts as `digest.md`, different selection and framing for
`{{audience}}`; introduce no claim absent from the digests.

Read only the files named above. Never fetch the web or read raw sources. Do not run git — the knowledge base syncs itself. Write $FLEET_TASK_DIR/RESULT.json as the protocol says. Do not close the bead yourself.
