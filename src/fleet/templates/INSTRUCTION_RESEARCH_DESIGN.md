# Fleet Task Protocol — research design phase

Read `$FLEET_TASK_DIR/artifacts/RESEARCH.md` and
`$FLEET_TASK_DIR/artifacts/candidates.json` (both in your launch pack). If
`$FLEET_TASK_DIR/artifacts/DESIGN_NOTES.md` exists, address the operator's
revision note first. If `$FLEET_TASK_DIR/artifacts/DESIGN_ERRORS.md`
exists, fix the listed validation errors: the rejected plan is in
`$FLEET_TASK_DIR/artifacts/tasks.rejected.json`; write the corrected plan to `tasks.json`.

Let `TOPIC` = `<topic>` from `candidates.json`'s `inputs.topic` (a folder
under `/Users/sergii/.ai/knowledge/research_topics/`).
Let `TARGET` = `/Users/sergii/.ai/knowledge/research_topics/<TOPIC>/research/<target>`
(`<target>` from `candidates.json`'s `inputs.target`). Every aggregate
(`index.md`, `overview.md`, `digest.md`, `agreements.md`, `disagreements.md`,
`open_questions.md`, `lenses/`, `topics/`, `sources.md`) lives under
`TARGET`; paper summaries stay under `research_topics/<TOPIC>/<Name>/`,
filed by their summarise runs.

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
There is no copy step: every source lives in exactly ONE place and the
summarise file stage puts it there.

## Per shortlisted source not already in the KB (`status == "shortlist"`, `origin == null`)

One task: the summarise run carries the research provenance AND the topic,
so its file stage MOVEs the finished entry to
`research_topics/<TOPIC>/<Name>/` and appends the category bullet — no
follow-up move bead:

```json
{"key": "src-NN", "title": "summarise: <title>", "workflow": "summarise", "inputs": {"url": "<url>", "research_target": "<TARGET>", "topic": "<TOPIC>"}, "folder": "<Name>"}
```

Every `title` in tasks.json must be at most 120 characters or the gate
rejects the whole plan. For `summarise:` titles use a short name (e.g.
`owner/repo` or the page's short title), never the full description.

`<TOPIC>` is the topic folder name from above (not a path). Derive each
source's `<Name>` folder the way the summarise plan step would
(`<PascalName>`, `YYYY-MM-DD-<PascalName>` for investment/finance topics),
record it in the entry's `folder` (a top-level key, never inside `inputs`),
and use it in the depending topic digests' `{{sources}}`. The guess can be
wrong — the plan step picks its own slug. That is expected: at spawn the
job worker strips a skipped source's `folder` from dependent bodies,
appends a `Source resolution` table (key, title, guessed folder, url,
status) to every bead depending on a workflow child, and writes the same
data to `artifacts/sources_resolved.json`; digest workers resolve the real
folder themselves (`Source:` provenance scan per their template) and report
skipped sources as skipped, never pending.

## Per shortlisted source already in the KB (`status == "shortlist"`, `origin != null`)

No task at all: the source is linked, never re-summarised and never moved.
Record its knowledge-relative folder (its `origin` relative to
`/Users/sergii/.ai/knowledge/`, e.g. `research_topics/<other>/<Name>`,
`investment/2026-01-01-<Name>`, or `research/<Name>`) and pass it in the
depending topic digests' `{{linked}}` so they read and link
`<origin>/summary.md` in place. When `origin` is already filed under
`research_topics/<TOPIC>/`, the topic digest links it like a fresh source.

## Per sub-topic in `topics`

```json
{
  "key": "topic-NN",
  "title": "digest: <subtopic>",
  "body": "<templates/research/topic_digest.md with {{target}}, {{nn}}, {{subtopic}}, {{title}}, {{sources}} (fresh <Name> folders), {{topic}} (<TOPIC>), {{linked}} (knowledge-relative in-KB folders, empty when none) filled>",
  "cwd": "/Users/sergii/.ai",
  "depends_on": ["src-NN", "..."]
}
```

`depends_on` lists the `src-NN` keys of this sub-topic's fresh sources
only (a workflow run child is depended on, never depending: it takes no
`depends_on` itself). Sub-topics with only linked sources have no
`depends_on`.

## Aggregation (topic level), each depending on every `topic-*` key

```json
{"key": "agg-digest", "title": "digest.md", "body": "<templates/research/agg_digest.md with {{target}}, {{topic}}, {{focus}} filled>", "cwd": "/Users/sergii/.ai", "depends_on": ["topic-01", "..."]}
```

```json
{"key": "agg-overview", "title": "overview.md", "body": "<templates/research/agg_overview.md with {{target}}, {{topic}}, {{focus}} filled>", "cwd": "/Users/sergii/.ai", "depends_on": ["topic-01", "..."]}
```

```json
{"key": "agg-agreements", "title": "agreements.md", "body": "<templates/research/agg_agreements.md with {{target}}, {{topic}}, {{focus}} filled>", "cwd": "/Users/sergii/.ai", "depends_on": ["topic-01", "..."]}
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
  "depends_on": ["src-01", "...", "topic-01", "...", "agg-digest", "agg-overview", "agg-agreements", "agg-disagreements", "agg-open", "lens-tech", "..."]
}
```

Every non-workflow body must be self-contained (no references to files
outside what it names), use absolute paths, name only the files it should
read, and end with `Do not run git. Do not close the bead yourself.`

Write `$FLEET_TASK_DIR/RESULT.json` with `status="partial"` and
`next_step="gate"`.
