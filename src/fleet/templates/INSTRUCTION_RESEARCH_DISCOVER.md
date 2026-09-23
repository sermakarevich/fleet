# Fleet Task Protocol — research discover phase

The bead description is this run's input table (free text or key/value
pairs, per `ai show research/get`):

| key | required | meaning | default |
|---|---|---|---|
| `topics` | yes | one topic or a list of sub-topics | — |
| `focus` | yes | 2-5 sentences: what question the research must answer, for whom, what to ignore | — |
| `target` | yes | folder slug under `research_topics/<topic>/research/` | — |
| `topic` | yes | research topic folder under `/Users/sergii/.ai/knowledge/research_topics/` (snake_case, must exist; sources are filed there) | — |
| `n_sources` | no | how many sources to shortlist | 10 |
| `lenses` | no | audiences for the top-level views | `tech, ai` |
| `gate` | no | `on`/`off` | `on` |
| `date_from` | no | ignore sources older than this (ISO date) | none |
| `kinds` | no | restrict to some of `paper`, `article`, `video`, `repo`, `thread` | all |

If `topics`, `focus`, `target` or `topic` is missing from the description, stop and
call `mcp__ask_human__ask_human_question` to get it — never invent a focus.

## 1. Collect candidates (metadata only, never full content)

Collect **3-5 x `n_sources`** candidates as metadata only: title, abstract
or first paragraph (<= 1,200 chars), authors, date, venue/channel, url,
kind. Free routes first:

| kind | route |
|---|---|
| paper | arXiv API (`export.arxiv.org/api/query`), Semantic Scholar API (`api.semanticscholar.org/graph/v1/paper/search`) |
| article | web search; engineering blogs; HN Algolia API (`hn.algolia.com/api/v1/search`) |
| video | web search restricted to youtube.com |
| repo / notebook | GitHub search API (`api.github.com/search/repositories`, `search/code`) |
| thread | **never search X/Twitter blind** (it costs paid credits per tweet); a thread only enters when another route points at it |

Restrict to `kinds` when given.

## 2. Hard filters (no model call)

Drop a candidate if any of these hold:

- duplicate url/title (case-insensitive, near-identical titles) already seen this run;
- older than `date_from`, when given;
- dead link: a HEAD request fails twice;
- **already in the KB**: normalize the candidate's url (drop scheme and
  `www.`; for arXiv compare the arXiv id; for YouTube compare the video
  id) and compare against every `sources[].resource` entry in the
  front-matter of `/Users/sergii/.ai/knowledge/research/*/index.md`,
  `/Users/sergii/.ai/knowledge/investment/*/index.md`,
  `/Users/sergii/.ai/knowledge/research/*/sources/*/index.md`,
  `/Users/sergii/.ai/knowledge/research_topics/*/research/*/index.md`, and
  `/Users/sergii/.ai/knowledge/research_topics/*/*/index.md`, plus the URL
  strings in `/Users/sergii/.ai/knowledge/research_topics/*/*/summary.md`
  (topic entries whose summary carries no front-matter). A match is
  kept with `status: "in_kb"` and `origin: "<folder that matched>"` — it is
  not scored again, only shortlisted for linking later (no re-summarise,
  no move).
- **Skip epic hubs**: a `research/*/` folder that contains a `sources/`
  subdirectory (plural) or whose `index.md` front-matter has
  `type: Research` is a research epic hub, not an entry — skip it for the
  `research/*/index.md` glob. Its `sources` front-matter holds counts, not
  resources, so it can never be an `in_kb` origin. Only folders with
  `source/source.md` (singular) are entries.

Everything that survives (including `in_kb` matches) becomes a candidate
row; anything dropped is not recorded further.

## 3. Score survivors with `jev`

For every survivor that is not already `in_kb`, run these three questions
**verbatim** (STATE = the candidate's metadata as JSON), batched with
`jev ask questions.json -s @cand.json`:

```bash
jev score "How directly does this source answer the research focus: <focus>?" \
    -l irrelevant -l tangential -l relevant -l central -s @cand.json
jev choose "What kind of source is this?" \
    -o primary-research -o survey -o tutorial -o opinion -o announcement -s @cand.json
jev choose "How authoritative is the origin?" \
    -o peer-reviewed -o recognised-lab-or-author -o established-blog -o unknown -s @cand.json
```

If `TYPESAFE_API_KEY` is not set, do not fall back to ranking with a chat
model. Write `$FLEET_TASK_DIR/RESULT.json` with `status="blocked"` and
`blocked_reason="jev needs TYPESAFE_API_KEY"`, then exit.

Record the three results as `scores.relevance` (0-1), `scores.kind`,
`scores.authority` on each candidate.

## 4. Shortlist

Sort by relevance, tie-break by kind (primary-research > survey > tutorial
> announcement > opinion) then authority. Take the top `n_sources` plus a
30% reserve (`status: "shortlist"` / `status: "reserve"`); everything else
that was scored is `status: "rejected"`.

Then **one** model pass over the shortlist + reserve only: assign each
shortlisted source's `subtopic` from `topics`; if a sub-topic has no
source, swap in the best reserve entry that covers it (its `status`
becomes `"shortlist"`, freeing a slot from the previous last-ranked
shortlist entry, whose `status` becomes `"reserve"`).

## 5. Write artifacts

`$FLEET_TASK_DIR/artifacts/candidates.json`:

```json
{
  "inputs": {"topics": [...], "focus": "...", "target": "...", "topic": "...", "n_sources": 10, "lenses": [...], "gate": "on", "date_from": null, "kinds": null},
  "candidates": [
    {
      "url": "...", "title": "...", "kind": "paper", "authors": "...", "date": "...",
      "venue": "...", "abstract": "...",
      "status": "candidate|in_kb|rejected|shortlist|reserve",
      "origin": null,
      "subtopic": null,
      "scores": {"relevance": 0.0, "kind": "...", "authority": "..."}
    }
  ]
}
```

`$FLEET_TASK_DIR/artifacts/RESEARCH.md` (<= 12 KB): a ranked shortlist
table `# | kind | score | source | sub-topic`, the count of `in_kb`
candidates, and the count of reserve candidates.

Write `$FLEET_TASK_DIR/RESULT.json` with `status="partial"` and
`next_step="design"`.
