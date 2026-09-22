"""Verify a finished summary_get knowledge-base entry against the recipe.

Called by the `verify` stage of the summary_get builder (see
`builders/summary_get.py`): the worker resolves the entry folder from
``{{steps.plan.outputs.paper_dir}}`` and runs these checks. Pure function
in, list of failure strings out, so the same logic is unit-testable:

- index/summary/digest/explainer/questions/critical_thinking exist and are
  non-trivial (> ``MIN_BYTES`` bytes).
- source/source.md exists and carries the ``Source:`` provenance line.
- wiki/ holds at least one page and no page stemmed from site chrome or
  README boilerplate.
- digest.md mentions every wiki page name (cheap proxy: each page's
  "In one sentence" line was quoted into the digest verbatim).
- every link in index.md resolves to a file that exists.

An empty list means the entry passes; each string is one blocked reason.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from fleet.workflows.builders.chunking import BOILERPLATE_WIKI_SUBSTRINGS

#: A derived file at or below this size counts as missing/trivial.
MIN_BYTES = 500

#: Required derived files at the entry root (ai:summary:get recipe).
REQUIRED_FILES = (
    "index.md",
    "summary.md",
    "digest.md",
    "explainer.md",
    "questions.md",
    "critical_thinking.md",
)

#: Wiki page stems containing any of these came from site chrome
#: (GitHub nav, sign-in walls) or README boilerplate (Sponsor, License,
#: Star History, ...), not from the source's argument.
BANNED_WIKI_SUBSTRINGS = (
    "latest-commit",
    "skip-to-content",
    "sign-in",
    *BOILERPLATE_WIKI_SUBSTRINGS,
)

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def verify_paper_dir(paper_dir: Path) -> list[str]:
    """Check one finished entry; return one failure string per problem."""
    failures: list[str] = []
    failures.extend(_check_required_files(paper_dir))
    failures.extend(_check_source(paper_dir))
    wiki_pages = _wiki_pages(paper_dir)
    failures.extend(_check_wiki(paper_dir, wiki_pages))
    failures.extend(_check_digest(paper_dir, wiki_pages))
    failures.extend(_check_index_links(paper_dir))
    return failures


def _check_required_files(paper_dir: Path) -> list[str]:
    """Every derived file exists and is bigger than MIN_BYTES."""
    failures = []
    for name in REQUIRED_FILES:
        path = paper_dir / name
        if not path.is_file():
            failures.append(f"verify: missing {name}")
        elif path.stat().st_size <= MIN_BYTES:
            failures.append(
                f"verify: {name} is trivial ({path.stat().st_size} bytes, need >{MIN_BYTES})"
            )
    return failures


def _check_source(paper_dir: Path) -> list[str]:
    """source/source.md exists and carries the `Source:` provenance line."""
    path = paper_dir / "source" / "source.md"
    if not path.is_file():
        return ["verify: missing source/source.md"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"verify: cannot read source/source.md ({exc})"]
    if not re.search(r"(?m)^Source:\s*\S", text):
        return ["verify: source/source.md has no `Source:` provenance line"]
    return []


def _wiki_pages(paper_dir: Path) -> list[Path]:
    """Wiki pages in order; empty when wiki/ is missing or has no pages."""
    wiki = paper_dir / "wiki"
    if not wiki.is_dir():
        return []
    return sorted(
        (path for path in wiki.glob("*.md") if path.is_file()),
        key=lambda path: path.name,
    )


def _check_wiki(paper_dir: Path, pages: list[Path]) -> list[str]:
    """At least one wiki page; none named after site chrome."""
    _ = paper_dir
    if not pages:
        return ["verify: wiki/ holds no pages"]
    failures = []
    for path in pages:
        stem = path.stem.lower()
        for banned in BANNED_WIKI_SUBSTRINGS:
            if banned in stem:
                failures.append(f"verify: wiki page {path.name} looks like site chrome ({banned})")
                break
    return failures


def _check_digest(paper_dir: Path, pages: list[Path]) -> list[str]:
    """digest.md mentions every wiki page name (rungs actually differ)."""
    digest = paper_dir / "digest.md"
    if not digest.is_file():
        return []
    try:
        text = digest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [
        f"verify: digest.md never mentions wiki page {path.name}"
        for path in pages
        if path.stem not in text
    ]


def _clean_target(raw: str) -> str:
    """Drop the anchor and the markdown escape backslash a table cell adds.

    Obsidian needs the pipe escaped inside a table, so index.md carries
    ``[[wiki/01-overview\\|Overview]]``; the capture keeps that backslash.
    """
    return raw.split("#", 1)[0].strip().rstrip("\\").strip()


def _resolve_target(paper_dir: Path, raw: str) -> Path | None:
    """Resolve one link target under the entry; None when external/anchor."""
    target = _clean_target(raw)
    if not target or target.startswith(("http://", "https://", "mailto:")):
        return None
    if "://" in target:
        return None
    candidate = (paper_dir / target.lstrip("/")).resolve()
    try:
        candidate.relative_to(paper_dir.resolve())
    except ValueError:
        return None
    if candidate.suffix:
        return candidate
    dotted = candidate.with_suffix(".md")
    if dotted.is_file():
        return dotted
    return candidate


def _check_index_links(paper_dir: Path) -> list[str]:
    """Every link in index.md resolves to a file that exists."""
    index = paper_dir / "index.md"
    if not index.is_file():
        return []
    try:
        text = index.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    targets = _WIKILINK_RE.findall(text) + _MD_LINK_RE.findall(text)
    failures = []
    seen: set[str] = set()
    for raw in targets:
        target = _clean_target(raw)
        if not target or target in seen:
            continue
        seen.add(target)
        resolved = _resolve_target(paper_dir, raw)
        if resolved is None:
            continue
        if not resolved.is_file():
            failures.append(f"verify: index.md links to missing {target}")
    return failures


def main(argv: list[str] | None = None) -> int:
    """CLI for the verify worker: print failures, exit 1 when any fail."""
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m fleet.workflows.builders.summary_verify <paper_dir>")
        return 2
    failures = verify_paper_dir(Path(args[0]))
    for failure in failures:
        print(failure)
    if failures:
        print(f"verify: {len(failures)} problem(s)")
        return 1
    print("verify: entry passes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
