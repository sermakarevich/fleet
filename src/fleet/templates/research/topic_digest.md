<!-- placeholders: {{target}} {{nn}} {{subtopic}} {{title}} {{sources}} {{topic}} {{linked}} -->
Write the digest for sub-topic `{{title}}` (`{{subtopic}}`) from its sources.
Every source lives in exactly one place: fresh sources under
`research_topics/{{topic}}/`, already-in-the-KB sources at their origin.
Link to them there; never move or copy them.

Fresh sources (filed by their summarise runs): read ONLY
`/Users/sergii/.ai/knowledge/research_topics/{{topic}}/<Name>/summary.md` and
`/Users/sergii/.ai/knowledge/research_topics/{{topic}}/<Name>/digest.md` for
each source `<Name>` in `{{sources}}` (space-separated folder names).

Already-in-the-KB sources (linked, never re-summarised): read ONLY
`/Users/sergii/.ai/knowledge/<folder>/summary.md` and
`/Users/sergii/.ai/knowledge/<folder>/digest.md` for each knowledge-relative
folder in `{{linked}}` (space-separated; empty when none). Read nothing else.

Write `{{target}}/topics/{{nn}}-{{subtopic}}/digest.md` with exactly this
shape:

```markdown
> [[../../index|Research]] | [[../../overview|Overview]] | [[../../digest|Digest]]

# {{title}}

**In one sentence:** <what the sources jointly establish on this sub-topic>

## Key points
- 5-8 bullets, each a complete claim with the source(s) behind it as [[<knowledge-relative folder>/summary|<short name>]] (e.g. [[research_topics/{{topic}}/<Name>/summary|Short]])

---
## What the sources agree on
## Where they differ
## Evidence quality
## Sources in this sub-topic
| source | kind | what it contributes |
```

Every claim in Key points carries its source link(s). The `Sources in this
sub-topic` table has one row per source in `{{sources}}` plus `{{linked}}`.

Read only the files named above. Never fetch the web or read raw sources. Do not run git — the knowledge base syncs itself. Write $FLEET_TASK_DIR/RESULT.json as the protocol says. Do not close the bead yourself.
