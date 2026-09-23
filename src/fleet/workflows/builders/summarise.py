"""Build the summarise workflow: fetch a URL, chunk it, plan wiki/derive/enrich/index/verify.

Called by `workflows.runs` through `builders.expand` at run start. The saved
workflow carries no stages; `build` fetches the source behind the run's `url`
input (reusing `builders.sources`), splits it with `builders.chunking`, writes
the fetched text plus one file per chunk into the run work dir, and returns
the workflow with six concrete stages: `plan` (one step), `wiki` (one step
per chunk), `derive` (digest + summary), `enrich` (explainer, questions,
critical-thinking), `index` (one step), and `verify` (one step that checks
the finished entry against the recipe and blocks instead of closing).

The finished entry stays in research/<Slug>/ (or investment/ for finance
topics). Nothing here moves or files it: whoever wants it filed runs the
`ai show summary/move` recipe on purpose.

Step descriptions are worker instructions. Absolute chunk/work paths are
written into them literally at build time; the knowledge-base folder is only
known after the `plan` step runs, so it is referenced as the template
`{{steps.plan.outputs.research_dir}}`, rendered when later stages are released.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from fleet.workflows.builders import BuildContext
from fleet.workflows.builders.chunking import (
    CHUNK_CHARS_DEFAULT,
    Chunk,
    chunk_repo,
    chunk_text,
    parse_chunk_chars,
)
from fleet.workflows.builders.sources import Source, SourceError, SourceKind, fetch
from fleet.workflows.model import Stage, Step, Workflow

#: Template every later stage uses for the knowledge-base folder chosen by `plan`.
RESEARCH_DIR = "{{steps.plan.outputs.research_dir}}"

#: Closing line of every step description.
TAIL = "Do not run git. Do not close the bead yourself."

_TYPE_OF: dict[SourceKind, str] = {
    SourceKind.youtube: "Video",
    SourceKind.pdf: "Paper",
    SourceKind.x: "Article",
    SourceKind.article: "Article",
    SourceKind.repo: "Codebase",
}

_PLAN_DESC = """You are planning where a fetched source will live in the knowledge base.

Source under study: "__TITLE__" (__URL__, kind __KIND__ via __TOOL__).
Run work dir (absolute, build-time): __WORK__

1. Read ONLY these two files (never the chunk bodies):
   - __SOURCE_MD__ (provenance header only: title, source, kind, fetched, tool)
   - __CHUNKS_JSON__ (chunk index/slug/title list)
   Do not read __WORK__/chunks/*.md — chunk bodies belong to later workers.

2. Decide the route from the title and chunk list:
   - Provenance-first rule (BEFORE deriving any folder name): search
     /Users/sergii/.ai/knowledge/research/*/source/source.md and
     /Users/sergii/.ai/knowledge/investment/*/source/source.md for a `Source:`
     line that equals this run's input (__URL__, exact string match). If one
     exists, reuse that folder no matter what slug this run would have derived:
     refresh <research_dir>/source/source.md from __SOURCE_MD__, write
     outputs.json (step 5) with that folder's absolute path and its existing
     folder basename as the slug, and continue. No question. Only when no such
     entry exists, derive a candidate folder below.
   - Investment/finance topic → base /Users/sergii/.ai/knowledge/investment with a new
     folder <YYYY-MM-DD>-<PascalName>, using {{run.date}} for the date.
   - Anything else → /Users/sergii/.ai/knowledge/research/<PascalName>.
   - If the route is genuinely unclear, ask with
     mcp__ask_human__ask_human_question. Never guess.
   - Folder-exists rule. If the candidate folder already exists, do NOT overwrite
     it and do NOT treat it as free — first check which case applies:
     1. Same source (re-run): read <candidate>/source/source.md and compare its
        `Source:` provenance url with this run's input (__URL__). If they match,
        reuse the folder: refresh <research_dir>/source/source.md from __SOURCE_MD__,
        write outputs.json (step 5), and continue. No question.
     2. Genuine conflict: the provenance url differs, or source.md is missing or
        unreadable → ask with mcp__ask_human__ask_human_question, passing
        task_id=<your bead id: the basename of $FLEET_TASK_DIR> and
        context=<this run's source url __URL__> so a retried plan step blocks
        on the already-pending question instead of asking twice. Never guess,
        never overwrite an existing folder.
   - macOS rule: the filesystem is case-insensitive, so research/Livekit and
     research/LiveKit are the same folder. A candidate slug that differs only in
     case from an existing folder is case 2 above, not a new folder.
   - Epic-hub rule: a research/<Name>/ folder that contains a `sources/`
     subdirectory (plural) or whose index.md front-matter has
     `type: Research` is a research epic hub, not an entry. It is NEVER
     reusable as this run's folder — not even when the provenance search
     above found nothing (epic hubs carry no source/source.md, so that
     search never matches them). A candidate that collides with an epic hub,
     including a case-only collision per the macOS rule, is always case 2
     above: ask, never reuse, never write entry files into the hub.

3. Create the layout and copy the source:
   - mkdir -p <research_dir>/source <research_dir>/wiki/images
   - Copy __SOURCE_MD__ to <research_dir>/source/source.md.
   - If __WORK__/source.pdf exists and is smaller than 2 MB, copy it to
     <research_dir>/source/source.pdf too; otherwise pin the PDF location (__URL__) at the
     top of <research_dir>/source/source.md.

4. Write <research_dir>/source/plan.md: a table mapping each chunk slug to its planned wiki
   page NN-<kebab-topic>.md plus a one-line "covers" note per row.

5. Write $FLEET_TASK_DIR/outputs.json exactly as {"research_dir": "<absolute research dir>",
   "slug": "<PascalName>", "title": "__TITLE__", "type": "__TYPE__"}.
   Type rule from the source kind (__KIND__): youtube → Video, pdf → Paper,
   x/article → Article, repo → Codebase. This run: __TYPE__.

Do not run git commands.
__TAIL__"""

#: Appended to the plan instructions on the codebase track: chunks are macro
#: components, so pages are named after components, not chapter topics.
_PLAN_REPO_ADDENDUM = """
6. Codebase track (this run, kind repo): the chunk list is one entry per macro
   component plus an overview. Name each wiki page after its component
   (NN-<kebab-component>.md, e.g. 02-graph-storage.md), overview first,
   ordered by structural importance. The outputs.json "type" for this run is
   "Codebase"."""

_CHUNK_DESC = """You are writing one wiki page for chunk __NN__/__TOTAL__
("__CHUNK_TITLE__") of "__TITLE__".

Run work dir (absolute, build-time): __WORK__

1. Read ONLY these two files:
   - __CHUNK_MD__ (the chunk body; your only source of facts)
   - __RESEARCH_DIR__/source/plan.md (find your chunk slug __SLUG__ and its planned page
     name; default __DEFAULT_PAGE__ when absent)
   Do not read any other chunk file, the original source, or the web.

2. Write __RESEARCH_DIR__/wiki/<page from plan.md> with exactly this contract:
   > [[../index|Wiki]] | [[../summary|Summary]] | [[../digest|Digest]]
   # <Topic>
   **In one sentence:** <the chunk's whole argument in one sentence>
   ## Key points
   - 5–8 bullets, each a complete claim with numbers/mechanisms, not a topic label
   ---
   ## <subsections mirroring the source>  (tables, exact numbers, verbatim quotes)
   **Covers:** <section/timestamp range>

3. Never invent content: only claims present in the chunk. If the chunk is empty or
   garbled, still write the page, saying so (title, one-sentence note, Covers line).

The knowledge base syncs itself and parallel workers share the tree; no git commands.
__TAIL__"""

_CHUNK_DESC_REPO = """You are writing one wiki page for macro component "__CHUNK_TITLE__"
(chunk __NN__/__TOTAL__) of codebase "__TITLE__" (__URL__).

Run work dir (absolute, build-time): __WORK__

1. Read ONLY these two files:
   - __CHUNK_MD__ (the component's source files; your only source of facts)
   - __RESEARCH_DIR__/source/plan.md (find your chunk slug __SLUG__ and its planned page
     name; default __DEFAULT_PAGE__ when absent)
   Do not read any other chunk file or the web. The clone lives outside the
   knowledge base; never copy it in.

2. Write __RESEARCH_DIR__/wiki/<page from plan.md> with exactly this contract:
   > [[../index|Wiki]] | [[../summary|Summary]] | [[../digest|Digest]]
   # <Component>
   **In one sentence:** <the component's whole job in one sentence>
   ## Key points
   - 5–8 bullets, each a complete claim about what the component does, each
     with file:line citations, not topic labels
   ---
   ## <subsections mirroring the component's modules>  (verbatim code excerpts,
     exact parameter names, tables for config/flags)
   **Covers:** <files/directories this page is grounded in>

3. Every structural claim cites file:line. Never invent content: only claims
   present in the chunk. If the chunk notes truncated files, say which files
   were cut instead of guessing their contents.

The knowledge base syncs itself and parallel workers share the tree; no git commands.
__TAIL__"""

_DIGEST_DESC = """You are writing the digest for "__TITLE__" (__URL__).

Run work dir (absolute, build-time): __WORK__

1. Read ONLY __RESEARCH_DIR__/wiki/*.md (never the source, the chunk files, or the web).

2. Write __RESEARCH_DIR__/digest.md:
   - Backlink line: > [[index|Wiki]] | [[summary|Summary]]
   - Heading: # __TITLE__ — Digest
   - Then one section per wiki page in order: ## N. [[wiki/NN-x|Title]] with that page's
     **In one sentence:** line and its ## Key points bullets copied VERBATIM (no
     rewording, no merging).
   - End with ## __FIVE_MOVES__ (5–7 numbered clauses tracing the whole
     source's arc across the pages).

__TAIL__"""

_SUMMARY_DESC = """You are writing the summary for "__TITLE__" (__URL__, type __TYPE__).

Run work dir (absolute, build-time): __WORK__

1. Read ONLY __RESEARCH_DIR__/wiki/*.md (never the source, the chunk files, or the web).

2. Write __RESEARCH_DIR__/summary.md:
   - Heading: # __TITLE__
   - Metadata line for type __TYPE__ (pick the matching variant):
     **Paper:** [..](__URL__) / **Article:** [..](__URL__) — <source>, <date> /
     **Video:** [..](__URL__) — <channel>
   - Sections in order: ## Human Readable TL;DR (3–5 plain sentences with analogies),
     ## TL;DR, then ---, then ## Problem & Motivation, ## Main Original Ideas (numbered,
     with bold names), ## Key Findings, ## Suggestions & Future Directions,
     ## Authors & Institutions.
   - Flowing paragraphs throughout, never one-sentence-per-line.

__TAIL__"""

_SUMMARY_DESC_REPO = """You are writing the technical analysis summary for codebase "__TITLE__"
(__URL__, type Codebase).

Run work dir (absolute, build-time): __WORK__

1. Read ONLY __RESEARCH_DIR__/wiki/*.md (never the clone, the chunk files, or the web).

2. Write __RESEARCH_DIR__/summary.md with exactly this layout, grounded in the
   component pages and their file:line citations:
   - Heading: # Technical Analysis: __TITLE__
   - Metadata lines: **Repository:** __URL__ / **Version analyzed:** <from the
     manifest or unknown> / **Date:** {{run.date}} / **Wiki:** [[index]]
   - Then these 11 sections in order (omit one only if it genuinely does not
     apply; never leave a stub):
     ## 1. Overview / What Problem It Solves (problem space, then how the repo
     addresses it; name the primary user)
     ## 2. High-Level Architecture (ASCII diagram with │ ▼ ─ ► connectors,
     then a 4–6 step data-flow narrative; state where persistent state lives)
     ## 3. <The Core Abstraction> (renamed after the repo's central concept;
     representation, named kinds/types with file:line, key queries with a
     verbatim snippet)
     ## 4. LLM / External Service Integration (providers, required vs optional
     calls, env vars; or state explicitly that the repo calls no LLM/API)
     ## 5. <The Main Pipeline> (renamed after the primary workflow; step by
     step with file.py:line for every function)
     ## 6. Key Files (table File | Lines | What It Does, 10–20 files by
     structural importance)
     ## 7. Dependencies (table Package | Version constraint | Purpose,
     required first, exact constraint strings)
     ## 8. CLI / Usage Surface (entry points, commands, env-var and config
     tables)
     ## 9. Extensibility Points (which file/class to extend per extension)
     ## 10. Limitations and Gotchas (at least 3 real ones, bold-led bullets)
     ## 11. How It Compares to Alternatives (3–4 real named projects plus a
     positioning sentence)
     ## Appendix: Selected Code Snippets (2–4 verbatim snippets with file and
     line ranges)
   - Direct, dense, analytical prose. No marketing adjectives, no emojis.

__TAIL__"""

_EXPLAINER_DESC = """You are writing the plain-language explainer for "__TITLE__" (__URL__).

Run work dir (absolute, build-time): __WORK__

1. Read __RESEARCH_DIR__/digest.md plus __RESEARCH_DIR__/wiki/*.md
   (never the source or the web).

2. Write __RESEARCH_DIR__/explainer.md, 80–150 lines:
   - Backlink line: > [[index|Wiki]] | [[summary|Summary]] | [[digest|Digest]]
   - Heading: # __TITLE__ — In Plain Language
   - Sections in order: ## What is this about?, ## Why does it matter?,
     ## How does it work?, ## Where can this be used?, ## Conclusions & takeaways,
     ## Jargon decoder (a table of 5–12 terms with plain definitions).

__TAIL__"""

_QUESTIONS_DESC = """You are writing retrieval-practice questions for "__TITLE__" (__URL__).

Run work dir (absolute, build-time): __WORK__

1. Read __RESEARCH_DIR__/digest.md plus __RESEARCH_DIR__/wiki/*.md
   (never the source or the web).
   Count the wiki pages: fewer than 5 pages → 6–8 questions; 5–8 pages → 8–12; more
   than 8 pages → 12–20. Cover every wiki page with at least one question and include
   exactly one evaluation question (judgment/recommendation).

2. Write __RESEARCH_DIR__/questions.md:
   - Front-matter: type: Retrieval Prompts, last_reviewed: null, review_count: 0
   - Backlink line: > [[index|Wiki]] | [[summary|Summary]] | [[digest|Digest]]
   - Heading: # Retrieval Practice: __TITLE__
   - One block per question: ### Qn. <question> followed by > [!tip]- Answer and then
     > <2–4 sentences>. See [[wiki/NN-x|Topic]].

__TAIL__"""

_CRITICAL_DESC = """You are writing the critical analysis for "__TITLE__" (__URL__).

Run work dir (absolute, build-time): __WORK__

1. Read __RESEARCH_DIR__/digest.md plus __RESEARCH_DIR__/wiki/*.md
   (never the source or the web).

2. Write __RESEARCH_DIR__/critical_thinking.md, 60–120 lines:
   - Backlink line: > [[index|Wiki]] | [[summary|Summary]] | [[digest|Digest]]
   - Heading: # Critical Analysis: __TITLE__
   - Sections in order: ## Claims vs. evidence, ## Genuinely new vs. repackaged,
     ## Weaknesses and blind spots, ## Applicability (including a
     **Relevance to my work** bullet list for AI/ML engineering, agentic systems, and
     the Elisity data platform), ## What this changes,
     ## Verdict ending with a bold call: **adopt** / **trial** / **watch** / **skip**.

__TAIL__"""

_INDEX_DESC = """You are writing the folder index for "__TITLE__" (__URL__).

Run work dir (absolute, build-time): __WORK__

1. Read __RESEARCH_DIR__/summary.md, __RESEARCH_DIR__/digest.md, and the list of
   __RESEARCH_DIR__/wiki/*.md (never the source or the web).

2. Write __RESEARCH_DIR__/index.md:
   - Front-matter with exactly these keys: type, title, description,
     generated: { by: claude/<model you are running as>, at: <current ISO time> },
     sources: [ {id: original, resource: __URL__},
     {id: local-copy, resource: source/source.md} ], tags: [2–5 topic tags].
   - Heading: # __TITLE__, then 2–3 orientation sentences.
   - ## How to work through this (summary ~2 min → digest ~10 min → wiki pages).
   - ## Read This Folder (links to summary, digest, explainer, critical_thinking,
     questions).
   - ## Wiki table | Page | Covers | with one row per wiki/*.md in order.
   - ## Original Source (link to __URL__ and the local copy source/source.md).

3. Sanity checklist before finishing: every wiki page has **In one sentence:** and
   ## Key points; digest lines are verbatim copies; every page has at least one
   question in questions.md. Report any defect in RESULT.json notes instead of fixing
   other workers' files silently.

__TAIL__"""

_VERIFY_DESC = """You are verifying the finished knowledge-base entry for "__TITLE__" (__URL__)
against the `ai show summary/get` recipe. A step counts as done only when the
entry is usable — never pass a green run over an empty or chrome-filled folder.

Run work dir (absolute, build-time): __WORK__
Entry folder: __RESEARCH_DIR__ (from {{steps.plan.outputs.research_dir}}).

1. Resolve the entry folder from {{steps.plan.outputs.research_dir}} (the plan
   step's outputs.json `research_dir`). If the folder is missing or unreadable,
   that is itself a failure.

2. Check every recipe rule and collect one failure string per problem:
   - index.md, summary.md, digest.md, explainer.md, questions.md,
     critical_thinking.md each exist and are non-trivial (>500 bytes).
   - source/source.md exists and carries the `Source:` provenance line.
   - wiki/ holds at least one page; no page name derived from site chrome
     (reject any page whose stem contains `latest-commit`, `skip-to-content`,
     or `sign-in`) or from README boilerplate (reject any page whose stem
     contains `sponsor`, `star-history`, `stargazer`, `license`,
     `contributing`, `citation`, `code-of-conduct`, `changelog`,
     `table-of-contents`, `related-project`, or `acknowledgement`).
   - digest.md mentions every wiki page name (each page's **In one sentence:**
     line must be quoted there, so the rungs actually differ).
   - every link in index.md ([[wikilink]] or [markdown](link)) resolves to a
     file that exists. Skip anything that points outside the entry folder:
     http/mailto URLs, #anchors, `~/...`, and machine-absolute paths such as
     `/Users/sergii/Downloads/source.pdf`. Those are the operator's own files
     and are never a reason to block.
   - Fast path: run
     `uv run python -m fleet.workflows.builders.summary_verify <research_dir>`
     from the fleet repo (or `python3 -m fleet.workflows.builders.summary_verify`
     with the fleet venv); it prints one line per problem and exits nonzero
     on failure. Fall back to the manual checks above (wc -c, grep, ls) when
     the module is unavailable.

3. Outcome:
   - All checks pass → write $FLEET_TASK_DIR/RESULT.json with status done and
     a one-sentence summary of what was verified.
   - Any check fails → write $FLEET_TASK_DIR/RESULT.json with status blocked
     and blocked_reason listing EVERY failure (one per line), so the operator
     sees WHY instead of a green run. Do NOT fix other workers' files
     silently; report, then stop.

__TAIL__"""


#: Saved definition created on fleet start when no workflow of this name exists
#: (see `fleet.workflows.builtins`). Operators may edit the saved copy freely.
DEFINITION: dict = {
    "name": "summarise",
    "description": (
        "Summarize a URL into an LLM-wiki folder in the knowledge base "
        "(ai:summary:get recipe). The builder fetches the source (yt for YouTube, "
        "x for X/Twitter, pdftotext for arXiv/PDF, shallow git clone for GitHub "
        "repos, HTML extraction otherwise), splits it into chunks (one per macro "
        "component for repos) and creates one wiki-page task per chunk, then "
        "digest/summary, explainer/questions/critical-thinking, index, "
        "and verify (blocks unless the entry satisfies the recipe). "
        "The finished entry stays in research/<Slug>/ (investment/ for "
        "finance topics); filing it elsewhere is a separate deliberate act "
        "via the ai:summary:move recipe, never part of this workflow."
    ),
    "defaults": {"cwd": str(Path.home() / ".ai"), "priority": 2, "isolation": "none"},
    "inputs": [
        {
            "name": "url",
            "description": (
                "Source URL (YouTube, X/Twitter, arXiv/PDF, GitHub repo, or an article page)"
            ),
            "required": True,
        },
        {
            "name": "chunk_chars",
            "description": "Target characters per chunk (2000-60000)",
            "default": str(CHUNK_CHARS_DEFAULT),
        },
        {
            "name": "research_target",
            "description": (
                "Research epic target that spawned this run (absolute path under "
                "/Users/sergii/.ai/knowledge/research/ or the target slug). "
                "Empty for standalone runs. Recorded for provenance only; "
                "nothing in this workflow files or moves the entry."
            ),
            "default": "",
        },
    ],
}


def build(workflow: Workflow, ctx: BuildContext) -> Workflow:
    """Fetch the URL, chunk it, and return the workflow with concrete stages."""
    raw_url = ctx.inputs.get("url")
    url = raw_url.strip() if raw_url else ""
    if not url:
        raise ValueError("input url is required")
    target = parse_chunk_chars(ctx.inputs.get("chunk_chars"))
    work = ctx.work_dir("summarise")
    work.mkdir(parents=True, exist_ok=True)
    source = fetch(url, work)
    _write_source(work, source, url, ctx)
    if source.kind is SourceKind.repo and (work / "repo").is_dir():
        chunks = chunk_repo(work / "repo", target)
    else:
        chunks = chunk_text(source.text, target)
    if not chunks:
        raise SourceError(
            f"fetch {url}: source has no substantive content after README boilerplate "
            "(Sponsor, License, Star History, ...) was dropped — not worth an entry"
        )
    _write_chunks(work, chunks)
    return replace(workflow, stages=_stages(source, chunks, work, url))


def _write_source(work: Path, source: Source, url: str, ctx: BuildContext) -> None:
    """Write the fetched text with a provenance header into the run work dir."""
    header = (
        f"# {source.title}\n"
        f"Source: {url}\n"
        f"Kind: {source.kind.value}\n"
        f"Fetched: {ctx.now.isoformat()}\n"
        f"Tool: {source.tool}\n"
        f"\n"
        f"{source.text}\n"
    )
    (work / "source.md").write_text(header, encoding="utf-8")


def _write_chunks(work: Path, chunks: list[Chunk]) -> None:
    """Write one markdown file per chunk plus a JSON manifest of them all."""
    chunk_dir = work / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for chunk in chunks:
        path = chunk_dir / f"{chunk.slug}.md"
        path.write_text(f"# {chunk.title}\n\n{chunk.text}\n", encoding="utf-8")
        records.append(
            {
                "index": chunk.index,
                "slug": chunk.slug,
                "title": chunk.title,
                "path": str(path),
                "chars": len(chunk.text),
            }
        )
    (work / "chunks.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


def _fill(template: str, **values: str) -> str:
    """Substitute __TOKEN__ placeholders (template braces stay literal)."""
    text = template.replace("__TAIL__", TAIL).replace("__RESEARCH_DIR__", RESEARCH_DIR)
    for key, value in values.items():
        text = text.replace(f"__{key}__", value)
    return text


def _common(source: Source, work: Path, url: str) -> dict[str, str]:
    """Placeholder values shared by every step description."""
    return {
        "TITLE": source.title,
        "URL": url,
        "KIND": source.kind.value,
        "TOOL": source.tool,
        "TYPE": _TYPE_OF[source.kind],
        "FIVE_MOVES": (
            "The system in five moves"
            if source.kind is SourceKind.repo
            else "The argument in five moves"
        ),
        "WORK": str(work),
        "SOURCE_MD": str(work / "source.md"),
        "CHUNKS_JSON": str(work / "chunks.json"),
    }


def _stages(
    source: Source,
    chunks: list[Chunk],
    work: Path,
    url: str,
) -> tuple[Stage, ...]:
    """The six fixed stages: plan, wiki, derive, enrich, index, verify."""
    common = _common(source, work, url)
    chunk_names = tuple(f"chunk-{chunk.index:02d}" for chunk in chunks)
    total = str(len(chunks))
    is_repo = source.kind is SourceKind.repo
    plan_desc = _PLAN_DESC + _PLAN_REPO_ADDENDUM if is_repo else _PLAN_DESC
    chunk_desc = _CHUNK_DESC_REPO if is_repo else _CHUNK_DESC
    summary_desc = _SUMMARY_DESC_REPO if is_repo else _SUMMARY_DESC
    plan = Stage(
        name="plan",
        steps=(
            Step(
                name="plan",
                title=f"summarise: plan {source.title}",
                description=_fill(plan_desc, **common),
            ),
        ),
    )
    wiki = Stage(
        name="wiki",
        steps=tuple(
            Step(
                name=name,
                title=f"summarise: wiki {chunk.index:02d}/{total} {chunk.title}",
                description=_fill(
                    chunk_desc,
                    **common,
                    NN=f"{chunk.index:02d}",
                    TOTAL=total,
                    CHUNK_TITLE=chunk.title,
                    SLUG=chunk.slug,
                    CHUNK_MD=str(work / "chunks" / f"{chunk.slug}.md"),
                    DEFAULT_PAGE=f"{chunk.slug}.md",
                ),
                needs=("plan",),
            )
            for name, chunk in zip(chunk_names, chunks, strict=True)
        ),
    )
    derive = Stage(
        name="derive",
        steps=(
            Step(
                name="digest",
                title=f"summarise: digest {source.title}",
                description=_fill(_DIGEST_DESC, **common),
                needs=chunk_names,
            ),
            Step(
                name="summary",
                title=f"summarise: summary {source.title}",
                description=_fill(summary_desc, **common),
                needs=chunk_names,
            ),
        ),
    )
    enrich = Stage(
        name="enrich",
        steps=(
            Step(
                name="explainer",
                title=f"summarise: explainer {source.title}",
                description=_fill(_EXPLAINER_DESC, **common),
                needs=("digest", "summary"),
            ),
            Step(
                name="questions",
                title=f"summarise: questions {source.title}",
                description=_fill(_QUESTIONS_DESC, **common),
                needs=("digest", "summary"),
            ),
            Step(
                name="critical-thinking",
                title=f"summarise: critical-thinking {source.title}",
                description=_fill(_CRITICAL_DESC, **common),
                needs=("digest", "summary"),
            ),
        ),
    )
    index = Stage(
        name="index",
        steps=(
            Step(
                name="index",
                title=f"summarise: index {source.title}",
                description=_fill(_INDEX_DESC, **common),
                needs=("explainer", "questions", "critical-thinking"),
            ),
        ),
    )
    verify = Stage(
        name="verify",
        steps=(
            Step(
                name="verify",
                title=f"summarise: verify {source.title}",
                description=_fill(_VERIFY_DESC, **common),
                needs=("index",),
            ),
        ),
    )
    return (plan, wiki, derive, enrich, index, verify)
