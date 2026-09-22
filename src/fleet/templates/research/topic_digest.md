<!-- placeholders: {{target}} {{nn}} {{subtopic}} {{title}} {{sources}} -->
Write the digest for sub-topic `{{title}}` (`{{subtopic}}`) from its sources.

Read ONLY `{{target}}/sources/<Name>/summary.md` and
`{{target}}/sources/<Name>/digest.md` for each source `<Name>` in
`{{sources}}` (space-separated source folder names assigned to this
sub-topic). Read nothing else.

Write `{{target}}/topics/{{nn}}-{{subtopic}}/digest.md` with exactly this
shape:

```markdown
> [[../../index|Research]] | [[../../overview|Overview]] | [[../../digest|Digest]]

# {{title}}

**In one sentence:** <what the sources jointly establish on this sub-topic>

## Key points
- 5-8 bullets, each a complete claim with the source(s) behind it as [[../../sources/<Name>/summary|<short name>]]

---
## What the sources agree on
## Where they differ
## Evidence quality
## Sources in this sub-topic
| source | kind | what it contributes |
```

Every claim in Key points carries its source link(s). The `Sources in this
sub-topic` table has one row per source in `{{sources}}`.

Read only the files named above. Never fetch the web or read raw sources. Do not run git — the knowledge base syncs itself. Write $FLEET_TASK_DIR/RESULT.json as the protocol says. Do not close the bead yourself.
