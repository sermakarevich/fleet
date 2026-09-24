# ADR 0015: Research workflow — many sources into one laddered knowledge-base topic

## Status

Accepted

## Date

2026-09-22

## Context

`summary_get` (ADR 0013) turns **one** URL into a laddered wiki folder in the
knowledge base (KB, the markdown vault at `~/.ai`): `summary.md` (2 min),
`digest.md` (10 min), one wiki page per chapter, plus explainer, questions and
critique. It answers "what does this source say?".

Research is a different question: "what do the best N sources say about this
topic, where do they agree, where do they contradict each other, and what is
still open?". Today that means an operator hand-picking URLs, starting N
summary_get runs, and synthesising across the resulting folders by hand.

Three facts about fleet shape the design:

- Workflow **builders** expand into stages at run start, synchronously (ADR
  0013). A research run only knows its fan-out *after an LLM has chosen the
  sources*, so a builder cannot express it.
- The **job worker** already does exactly that shape: one epic bead whose
  worker researches, designs `artifacts/tasks.json`, asks the operator to
  approve the plan (approve / revise / cancel), spawns the children with
  dependencies, then observes and validates them (`workers/job.py`,
  `core/job_phase.py`). The gate is `--job-gate off` when the operator wants
  no question.
- `jev` (the TypeSafe judge-model CLI, `jev --help`) answers typed questions
  with calibrated probabilities at roughly 1/100 of the cost of a prompt to a
  chat model. It cannot write text; it can rank.

The operator's stated priorities: quality first (cost control later), a
human-approved source list by default, hierarchical outputs readable at
several depths and through several lenses (business, product, tech, AI), and
re-runnable research.

## Decision

### 1. Research is a job, not a builder

A research run is an epic bead with `--worker research`. It reuses the job
phase table (`core/job_phase.py`) unchanged — research → design → gate →
spawn → observe — with research-specific prompts:

| phase | writes | what it does |
|---|---|---|
| `research` (discover) | `artifacts/RESEARCH.md`, `artifacts/candidates.json` | collects and ranks candidate sources (section 3) |
| `design` | `artifacts/DESIGN.md`, `artifacts/tasks.json` | turns the shortlist into children (section 4) |
| `gate` | one ask_human question | shows the shortlist with scores and one-line reasons; approve / revise (with note) / cancel |
| `spawn` | children | opens the workflow runs and beads with dependencies |
| `observe` | `artifacts/CHILDREN.md` | validates coverage: every approved source has a folder and is linked from the topic index; opens follow-ups otherwise |

Inputs come from the bead body, in the recipe's front-matter form (section
6): `topics`, `focus`, `target` (folder slug under `knowledge/research/`),
`n_sources`, `lenses`, and the gate flag.

### 2. A job child may be a workflow run

`tasks.json` entries gain two optional keys:

```json
{"key": "src-03", "title": "summary_get: <title>",
 "workflow": "summary_get", "inputs": {"url": "https://..."}}
```

`core/job_plan.validate_tasks` accepts `workflow` (a saved workflow id or
name) plus `inputs` (string map) and rejects `body`/`coder`/`model` on such an
entry — the workflow's own defaults apply. `workers/job.py::SpawnChildren`
starts the run through `workflows.runs.start_run` and records the run id in
the children journal. For dependency purposes the child *is the run*: a
sibling that `depends_on` it depends on every task of the run's last stage,
and the observer's "children terminal" check (`core/job_ready.py`) treats a
run as terminal when its status is `succeeded`, `attention` or `cancelled`.

This is the only engine change the workflow needs. It is generic: any job
can now fan out into workflow runs.

### 3. Ranking is a funnel; the model reads only the winners

Full content is never fetched to rank a candidate. The discover phase:

1. **Collects 3–5× N candidates as metadata only** — title, abstract or
   first paragraph, authors, date, venue or channel, URL. Free routes first:
   arXiv and Semantic Scholar APIs for papers, the HN Algolia API for
   discussion, GitHub search for frameworks and notebooks, web search for
   articles and YouTube videos. X/Twitter is **never searched blind** (it
   costs paid credits per tweet); X threads enter only when another route
   points at them (an author's announcement thread, for instance).
2. **Applies hard filters with no model call** — duplicate URL/title, date
   window, language, dead link (HEAD request), and **already in the KB**
   (section 5).
3. **Scores every survivor with `jev`** on its metadata text, three
   questions per candidate: relevance to `focus` (0–1), depth (primary
   research / survey / tutorial / opinion), authority (peer-reviewed,
   recognised lab or author, popular blog, unknown). Scores are written to
   `candidates.json` so the gate can show them and a re-run can reuse them.
4. **Shortlists N plus a ~30 % reserve**, ranked by relevance, tie-broken by
   depth then authority.
5. **One chat-model pass over the shortlist only**, to check that every
   topic in `topics` has at least one source and swap a reserve in where a
   topic has none. This is the single "expensive" call in ranking.

For N = 10 that is about 40 candidates × 3 jev questions plus one model call.
The costly reading happens exactly N times, inside summary_get, and never for
a rejected candidate.

### 4. Children and their dependency graph

The design phase emits, per approved source:

- **new to the KB** → a `summary_get` workflow run (writes the source's
  folder to its normal home, `research/` or `investment/`, by summary_get's own
  routing rule), then a **copy bead** depending on it that copies the folder
  into `research/<target>/sources/<Name>/`;
- **already in the KB** → the copy bead only.

Then the aggregation chain, each level depending on the one below:

1. per-subtopic digest beads (one per entry in `topics`), each depending on
   the copy beads of the sources assigned to that subtopic;
2. the topic-level beads — `digest.md`, `overview.md`, `disagreements.md`,
   `open_questions.md` — depending on every subtopic digest;
3. lens beads, one per entry in `lenses`, depending on the topic digest;
4. `index.md` + `sources.md` last, depending on everything.

Aggregation beads read **only** the per-source `summary.md` and `digest.md`
(and lower-level aggregates), never wiki pages or raw sources. This is
summary_get's single-source-of-truth rule lifted one level: an aggregate is
derived text, so it can always be rebuilt from the leaves.

Lenses apply at subtopic and topic level only. Leaves stay neutral;
producing a business/product/tech/AI variant of every source would multiply
cost by the lens count for no synthesis gain.

### 5. Already-in-the-KB sources are copied, not re-processed

Before ranking, the discover phase checks `knowledge/research/`,
`knowledge/investment/` and every `knowledge/research/*/sources/` for a
folder whose `index.md` front-matter `sources[].resource` matches the
candidate URL (normalised: scheme and `www.` dropped, arXiv id extracted,
YouTube id extracted). A match is kept with `status: in_kb` and skips
summary_get; the copy bead copies the existing folder. The operator chose a
self-contained research folder (readable as one unit on GitHub mobile) over
links to the originals; the trade-off is that a later edit to the original
does not propagate. `sources.md` records the origin path of every copy so a
re-run can refresh it.

### 6. The recipe is the spec

`ai show research/get` (`~/.ai/skills/research/get.md`) owns the output
contract: folder layout under `/Users/sergii/.ai/knowledge/research/<target>/`,
every file's shape, the ranking rubric, the naming rules, the gate text. The
worker prompts quote the recipe's contracts verbatim into each child's body
(workers never see the recipe itself, per `ai show fleet/add_task`). If the
workflow and the recipe disagree, the recipe wins and the workflow is fixed.

### 7. Re-runs add, they do not redo

A research target folder can be run again with the same or a wider input.
`sources.md` is the ledger: every source ever considered, with its status
(`processed`, `in_kb`, `rejected`, `unreachable`) and scores. A re-run
excludes ledger entries from candidate collection, processes only new
sources, and **regenerates every aggregate** from the now-larger leaf set.
Because aggregates are derived (section 4), this is safe. A schedule (ADR
0007) can therefore keep a topic current.

## Consequences

- Positive: one bead turns a topic list into a laddered, multi-lens research
  folder; the operator approves a scored source list instead of pasting
  URLs; cross-source disagreements and gaps become first-class outputs;
  rerunning is cheap and safe.
- Positive: the engine change (workflow-run children) is small and generic.
- Cost: N summary_get runs is N × ~10 beads. Not controlled in this ADR by
  the operator's choice; a budget input is a natural follow-up.
- `jev` needs `TYPESAFE_API_KEY` in the worker environment
  (`workers/child_env.py` passes `os.environ` through); the discover step
  fails loudly with a `BLOCKED` result if the key is absent rather than
  falling back to a chat-model ranking.
- The shared `~/.ai` tree has no worktree isolation. Copy and aggregation
  beads write disjoint paths and never run git (the KB syncs itself), the
  same rule summary_get already follows.
- Discovery quality depends on which free metadata routes are wired; the
  first version covers arXiv, Semantic Scholar, HN, GitHub and web search.
  X search on demand is a possible later addition behind an explicit flag.

## Implementation (beads, serial unless noted)

- [x] 1. `core/job_plan.validate_tasks` + `workers/job.py::SpawnChildren` +
  `core/job_ready.py`: workflow-run children (section 2), with tests
  (`8c7d8db`, `46e7fd3`).
- [x] 2. `workers/research.py` prompts for discover and design, registered as
  `--worker research`; `candidates.json` schema and the jev scoring helper
  (`52aafcf`).
- [x] 3. Copy-bead and aggregation-bead body templates quoting the recipe
  (`a9a3426`).
- [x] 4. CLI/UI: `fleet research <id>` (alias of `fleet job` with the source table),
  run detail shows the shortlist and scores (`7e190e9`).
- [x] 5. Docs: guide section, `docs/workflows/` example, this ADR to Accepted
  (this change).

## Amendment 2026-09-23 — topic-first research, summarise files its own entry

Research runs take a new required input `topic`: a folder name under
`~/.ai/knowledge/research_topics/` (snake_case, must exist — `ai new
<topic>` creates one). The research builder validates it and adds it to
the bead description, so discover/design phases see it without asking.
The `kinds` input vocabulary is `paper, article, video, repo, thread`,
matching the discover prompt.

Every source now lives in exactly one place,
`research_topics/<topic>/<Name>/`, filed by the summarise run itself: the
summarise builder's new optional `topic` input appends a final `file`
stage after `verify` that MOVEs the finished entry there and appends a
`- [[<Name>/summary]] — <tldr>.` bullet to
`research_topics/<topic>/<topic>.md` (the `ai show summary/move` recipe
minus the confirmation question; a present destination fails loudly).
Without `topic` the entry stays in `research/<Slug>/` as before. The
long-declared-but-never-read `research_target` input is now recorded as
provenance (`Research-Target:` / `Topic:` lines in the fetched source
header the plan step copies to `source/source.md`).

The design phase passes `topic` (plus `research_target`) to every
`src-NN` summarise child and emits no `copy-NN` step:
`templates/research/copy.md` is deleted. Already-in-the-KB shortlist
entries get no task — topic digests link their `origin` in place via the
new `{{linked}}` field. The discover dedup scan additionally covers
`research_topics/*/*/index.md` (front-matter resources) and
`research_topics/*/*/summary.md` (URL strings). The `agg-index` bead owns
the `sources.md` ledger rows the copy beads used to write.

Operator note: the saved `research` workflow row needs the required
`topic` input added by hand — builtins backfill optional inputs only.

## Amendment 2026-09-23 — skipped sources and real folder names reach dependents

Run `wfr-2l1rhkdh` showed two spawn-time gaps. `src-06` (embedded null
byte) and `src-10` (HTTP 403) were skipped at spawn and correctly dropped
from dependents' `depends_on`, but the design-rendered bodies still named
them, so the topic-02 digest waited for a source that could never arrive
and looped `partial` 5×; topic-03 silently wrote a `pending` row. And the
folder names in bodies are design-time guesses while the summarise plan
step picks its own slug, so even filed sources may live under a different
`<Name>` than the digest was told.

Chosen design (simpler robust option from the two considered):

- `tasks.json` `src-NN` entries carry a top-level `folder` (the guessed
  `<Name>`; never inside `inputs`, ignored by validation).
- Every spawn attempt, `SpawnChildren` writes
  `artifacts/sources_resolved.json` (key → state, title, guessed folder,
  url, reason, run id) and rewrites each freshly created non-workflow
  child that depends on a manifest key via `bd update`: guessed names of
  skipped sources are stripped from its source lists and a `Source
  resolution` table (key, title, guessed folder, url, status) is appended.
  The job comment records the manifest and the rewrite count. Rewriting
  only fresh children is sufficient: a child is created exactly when all
  its dependencies are created-or-skipped, so those states are final at
  creation time.
- Dependents self-resolve at claim time: `topic_digest.md` and
  `agg_index.md` instruct their workers to treat the appended table as
  authoritative — skipped → `skipped`/`unreachable` row, never pending,
  never partial; a missing guessed folder → `Source:` provenance scan of
  `research_topics/<topic>/*/source/source.md` (title fallback), still
  missing → `unreachable` row, never partial. The file stage preserves
  the plan slug as the destination basename, so the scan always lands.

Rejected alternative: refreshing dependent bodies from the epic's observe
phase when a child run finishes. The epic is claimable only when every
child is terminal (`BeadsQueue._ready_epic_rows`), i.e. never while a
digest is still pending, so no job-side step can beat the claim race —
resolution has to live in the dependent's own body plus its template.

## Output under topic (2026-09-23)

Research aggregates moved in with their topic: `TARGET` is now
`research_topics/<topic>/research/<target>/` (index, overview, digest,
disagreements, open_questions, `lenses/`, `topics/`, `sources.md`). Paper
summaries stay at `research_topics/<topic>/<Name>/`, filed by their
summarise `file` stage. The `agg-index` bead registers the research in the
topic page `research_topics/<topic>/<topic>.md` under a `## Research`
section (above `## Tutorials` when present) instead of
`knowledge/research/index.md`. Old research folders still under
`knowledge/research/<target>/` keep working: the discover dedup scan covers
both locations. Existing KB content is moved by the operator, not by fleet.

## agreements.md (2026-09-24)

The operator's spec pairs every `disagreements.md` with an `agreements.md`:
claims two or more independent sources support, who backs each, how strong
the joint evidence is and under which conditions it holds. It was missing
from the first runs (`wfr-oexdmbmg`). Design now emits an `agg-agreements`
bead (`templates/research/agg_agreements.md`) next to `agg-disagreements`,
depending on every topic digest; `agg-index` waits for it and the overview's
`## What is established` links to it. The recipe (`ai show research/get`)
lists it in the output tree and the definition of done.

## Related

- ADR 0007 recurring workers (schedules), ADR 0008 workflows, ADR 0010 run
  inputs and step outputs, ADR 0013 workflow builders.
- Recipe: `~/.ai/skills/research/get.md` (`ai show research/get`);
  `~/.ai/skills/summary/get.md` for the per-source contract.
- Code the decision touches: `core/job_plan.py`, `core/job_phase.py`,
  `core/job_ready.py`, `workers/job.py`, `workflows/runs.py`.
