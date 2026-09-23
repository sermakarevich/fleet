# Fleet Task Protocol — research design phase

Read `$FLEET_TASK_DIR/artifacts/RESEARCH.md` and
`$FLEET_TASK_DIR/artifacts/candidates.json` (both in your launch pack). If
`$FLEET_TASK_DIR/artifacts/DESIGN_NOTES.md` exists, address the operator's
revision note first. If `$FLEET_TASK_DIR/artifacts/DESIGN_ERRORS.md`
exists, fix the listed validation errors.

Let `TARGET` = `/Users/sergii/.ai/knowledge/research/<target>` (`<target>`
from `candidates.json`'s `inputs.target`).

Each child body is the file
`/Users/sergii/git/fleet/src/fleet/templates/research/<kind>.md` with its
`{{placeholders}}` filled (see
`fleet.workers.research_bodies.render_body`). Read the file and paste the
filled text as `body`. Fill every placeholder from the shortlist (source
URL, folder `Name`, `origin`, `TARGET`, sub-topic slug and title, topic,
focus, lens and audience); the pasted body must contain no `{{` tokens.

Write `$FLEET_TASK_DIR/artifacts/DESIGN.md` (approach: how many sources,
how many sub-topics, the dependency shape below) and
`$FLEET_TASK_DIR/artifacts/tasks.json` with exactly this task graph.

## Per shortlisted source not already in the KB (`status == "shortlist"`, `origin == null`)

Two tasks (the summarise run carries the research provenance so its file
step skips filing into structured_papers/ — the copy bead below owns the
entry's ONE home under research; MOVE, never copy):

```json
{"key": "src-NN", "title": "summarise: <title>", "workflow": "summarise", "inputs": {"url": "<url>", "research_target": "<TARGET>"}}
```

```json
{
  "key": "copy-NN",
  "title": "move <Name> into <target>",
  "body": "<templates/research/copy.md with {{url}}, {{name}}, {{origin}} (empty), {{target}} filled>",
  "cwd": "/Users/sergii/.ai",
  "depends_on": ["src-NN"]
}
```

`<TARGET>` is the absolute target from above
(`/Users/sergii/.ai/knowledge/research/<target>`). The copy bead MOVEs the entry
folder `research/<Name>/` into `<TARGET>/sources/<Name>/`, leaving nothing behind;
nothing is filed into structured_papers/ for these sources.

## Per shortlisted source already in the KB (`status == "shortlist"`, `origin != null`)

The copy task only, moving from `origin` instead of a fresh summarise
folder, with no `depends_on` (MOVE, never copy — when `origin` is already
homed under investment/ or structured_papers/, the copy bead stops with an
error instead of duplicating it, so the operator decides):

```json
{
  "key": "copy-NN",
  "title": "move <Name> into <target>",
  "body": "<templates/research/copy.md with {{url}}, {{name}}, {{origin}}, {{target}} filled>",
  "cwd": "/Users/sergii/.ai"
}
```

## Per sub-topic in `topics`

```json
{
  "key": "topic-NN",
  "title": "digest: <subtopic>",
  "body": "<templates/research/topic_digest.md with {{target}}, {{nn}}, {{subtopic}}, {{title}}, {{sources}} filled>",
  "cwd": "/Users/sergii/.ai",
  "depends_on": ["copy-NN", "..."]
}
```

## Aggregation (topic level), each depending on every `topic-*` key

```json
{"key": "agg-digest", "title": "digest.md", "body": "<templates/research/agg_digest.md with {{target}}, {{topic}}, {{focus}} filled>", "cwd": "/Users/sergii/.ai", "depends_on": ["topic-01", "..."]}
```

```json
{"key": "agg-overview", "title": "overview.md", "body": "<templates/research/agg_overview.md with {{target}}, {{topic}}, {{focus}} filled>", "cwd": "/Users/sergii/.ai", "depends_on": ["topic-01", "..."]}
```

```json
{"key": "agg-disagreements", "title": "disagreements.md", "body": "<templates/research/agg_disagreements.md with {{target}}, {{topic}}, {{focus}} filled>", "cwd": "/Users/sergii/.ai", "depends_on": ["topic-01", "..."]}
```

```json
{"key": "agg-open", "title": "open_questions.md", "body": "<templates/research/agg_open_questions.md with {{target}}, {{topic}}, {{focus}} filled>", "cwd": "/Users/sergii/.ai", "depends_on": ["topic-01", "..."]}
```

## Lenses, one per entry in `lenses`, each depending on `agg-digest`

```json
{
  "key": "lens-<name>",
  "title": "lenses/<name>.md",
  "body": "<templates/research/lens.md with {{target}}, {{topic}}, {{lens}}, {{audience}} filled>",
  "cwd": "/Users/sergii/.ai",
  "depends_on": ["agg-digest"]
}
```

## `agg-index`, depending on everything else

```json
{
  "key": "agg-index",
  "title": "index.md + sources.md + research index",
  "body": "<templates/research/agg_index.md with {{target}}, {{topic}}, {{focus}}, {{lenses}}, {{topics}} filled>",
  "cwd": "/Users/sergii/.ai",
  "depends_on": ["copy-01", "...", "agg-digest", "agg-overview", "agg-disagreements", "agg-open", "lens-tech", "..."]
}
```

Every non-workflow body must be self-contained (no references to files
outside what it names), use absolute paths, name only the files it should
read, and end with `Do not run git. Do not close the bead yourself.`

Write `$FLEET_TASK_DIR/RESULT.json` with `status="partial"` and
`next_step="gate"`.
