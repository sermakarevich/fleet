# Fleet Task Protocol — research design phase

Read `$FLEET_TASK_DIR/artifacts/RESEARCH.md` and
`$FLEET_TASK_DIR/artifacts/candidates.json` (both in your launch pack). If
`$FLEET_TASK_DIR/artifacts/DESIGN_NOTES.md` exists, address the operator's
revision note first. If `$FLEET_TASK_DIR/artifacts/DESIGN_ERRORS.md`
exists, fix the listed validation errors.

Let `TARGET` = `/Users/sergii/.ai/knowledge/research/<target>` (`<target>`
from `candidates.json`'s `inputs.target`).

Write `$FLEET_TASK_DIR/artifacts/DESIGN.md` (approach: how many sources,
how many sub-topics, the dependency shape below) and
`$FLEET_TASK_DIR/artifacts/tasks.json` with exactly this task graph.

## Per shortlisted source not already in the KB (`status == "shortlist"`, `origin == null`)

Two tasks:

```json
{"key": "src-NN", "title": "summary_get: <title>", "workflow": "summary_get", "inputs": {"url": "<url>"}}
```

```json
{
  "key": "copy-NN",
  "title": "copy <Name> into <target>",
  "body": "Locate the summary_get folder for <url> by its index.md front-matter (sources[].resource) under /Users/sergii/.ai/knowledge/papers/ or /Users/sergii/.ai/knowledge/investment/. Copy it recursively (cp -R) to TARGET/sources/<Name>/, keeping the name. Verify TARGET/sources/<Name>/index.md exists. Append a row to TARGET/sources.md: | # | status | kind | score | source | sub-topic | folder | origin | with status=processed. Do not run git. Do not close the bead yourself.",
  "cwd": "/Users/sergii/.ai",
  "depends_on": ["src-NN"]
}
```

## Per shortlisted source already in the KB (`status == "shortlist"`, `origin != null`)

The copy task only, copying from `origin` instead of a fresh summary_get
folder, with `status=in_kb` in its `sources.md` row and no `depends_on`:

```json
{
  "key": "copy-NN",
  "title": "copy <Name> into <target>",
  "body": "Copy the existing folder at <origin> recursively (cp -R) to TARGET/sources/<Name>/, keeping the name. Verify TARGET/sources/<Name>/index.md exists. Append a row to TARGET/sources.md: | # | status | kind | score | source | sub-topic | folder | origin | with status=in_kb, origin=<origin>. Do not run git. Do not close the bead yourself.",
  "cwd": "/Users/sergii/.ai"
}
```

## Per sub-topic in `topics`

```json
{
  "key": "topic-NN",
  "title": "digest: <subtopic>",
  "body": "Read only TARGET/sources/<Name>/summary.md and TARGET/sources/<Name>/digest.md for every source assigned to sub-topic <subtopic> (see TARGET/sources.md for the assignment). Write TARGET/topics/NN-<subtopic>/digest.md:\n\n> [[../../index|Research]] | [[../../overview|Overview]] | [[../../digest|Digest]]\n\n# <Sub-topic title>\n\n**In one sentence:** <what the sources jointly establish on this sub-topic>\n\n## Key points\n- 5-8 bullets, each a complete claim with the source(s) behind it as [[../../sources/<Name>/summary|<short name>]]\n\n---\n## What the sources agree on\n## Where they differ\n## Evidence quality\n## Sources in this sub-topic\n| source | kind | what it contributes |\n\nDo not run git. Do not close the bead yourself.",
  "cwd": "/Users/sergii/.ai",
  "depends_on": ["copy-NN", "..."]
}
```

## Aggregation (topic level), each depending on every `topic-*` key

```json
{"key": "agg-digest", "title": "digest.md", "body": "Read only TARGET/topics/*/digest.md. Write TARGET/digest.md: one `## N. [[topics/NN-x/digest|Title]]` section per sub-topic, copying that digest's `**In one sentence:**` line and `## Key points` bullets verbatim -- no rewording, no merging. End with `## The picture in five moves` (5-7 numbered clauses tracing the argument across sub-topics). Do not run git. Do not close the bead yourself.", "cwd": "/Users/sergii/.ai", "depends_on": ["topic-01", "..."]}
```

```json
{"key": "agg-overview", "title": "overview.md", "body": "Read only TARGET/topics/*/digest.md and TARGET/sources.md. Write TARGET/overview.md: `# <Topic>` - `**Research:** <n> sources, <date range>, focus: <focus>` - `## Human Readable TL;DR` (3-5 plain sentences with analogies) - `## TL;DR` - `## What is established` - `## What is contested` (one line each, link to disagreements.md) - `## What is open` (link to open_questions.md) - `## How to read this folder`. Flowing paragraphs, never one sentence per line. Do not run git. Do not close the bead yourself.", "cwd": "/Users/sergii/.ai", "depends_on": ["topic-01", "..."]}
```

```json
{"key": "agg-disagreements", "title": "disagreements.md", "body": "Read only TARGET/topics/*/digest.md and the source summaries they link. Write TARGET/disagreements.md: one section per real contradiction, `## <claim A> vs <claim B>`, who says what with source links, the likely reason (different setting, metric, date, incentive), which side the evidence favours or \"unresolved\". Include only real contradictions, not differences of emphasis. Zero sections is legitimate -- say so explicitly rather than inventing tension. Do not run git. Do not close the bead yourself.", "cwd": "/Users/sergii/.ai", "depends_on": ["topic-01", "..."]}
```

```json
{"key": "agg-open", "title": "open_questions.md", "body": "Read only TARGET/topics/*/digest.md. Write TARGET/open_questions.md: numbered questions no source answers, each with why it matters for the focus and which sub-topic it belongs to. Do not run git. Do not close the bead yourself.", "cwd": "/Users/sergii/.ai", "depends_on": ["topic-01", "..."]}
```

## Lenses, one per entry in `lenses`, each depending on `agg-digest`

```json
{
  "key": "lens-<name>",
  "title": "lenses/<name>.md",
  "body": "Read only TARGET/digest.md and TARGET/topics/*/digest.md. Write TARGET/lenses/<name>.md: `# <Topic> -- for <name>` - `## What this means for you` - `## Decisions this informs` - `## Risks and unknowns` - `## Where to go deeper` (links into topics/ and sources/). Same facts as digest.md, different selection and framing; introduce no claim absent from the digests. Do not run git. Do not close the bead yourself.",
  "cwd": "/Users/sergii/.ai",
  "depends_on": ["agg-digest"]
}
```

## `agg-index`, depending on everything else

```json
{
  "key": "agg-index",
  "title": "index.md + sources.md + research index",
  "body": "Read only TARGET/*.md, TARGET/topics/*/digest.md, TARGET/sources.md and TARGET/lenses/*.md. Write TARGET/index.md (front-matter type: Research, title, description, generated, focus, topics, lenses, sources counts, runs, tags; then '## How to work through this', '## Cross-cutting', '## Lenses', '## Sub-topics', '## Sources' as in ai show research/get). Confirm TARGET/sources.md already lists every processed/in_kb source (do not rewrite rows written by the copy tasks). Append one bullet (folder link + one-line description) to /Users/sergii/.ai/knowledge/research/index.md. Do not run git. Do not close the bead yourself.",
  "cwd": "/Users/sergii/.ai",
  "depends_on": ["copy-01", "...", "agg-digest", "agg-overview", "agg-disagreements", "agg-open", "lens-tech", "..."]
}
```

Every non-workflow body must be self-contained (no references to files
outside what it names), use absolute paths, name only the files it should
read, and end with `Do not run git. Do not close the bead yourself.`

Write `$FLEET_TASK_DIR/RESULT.json` with `status="partial"` and
`next_step="gate"`.
