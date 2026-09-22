"""Split fetched source text into chapter-sized chunks along its own structure.

Called by `builders/summary_get.py`. Pure text in, list of chunks out: the
text is cut at markdown headings when it has them, else at blank lines,
and neighbouring pieces are packed greedily up to a target size so every
chunk is a whole section (or a run of whole paragraphs), never a cut mid
sentence. Chunk count is capped so a very long source still yields a
workable number of worker tasks.

`chunk_repo` is the codebase-track sibling: one chunk per macro component
(top-level package, module, service or tooling directory) of a cloned repo,
plus an overview chunk first, so each wiki worker writes the page of one
real component instead of one slice of prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_HEADING_RE = re.compile(r"^#{1,3} +\S", re.MULTILINE)
_TITLE_RE = re.compile(r"^#{1,3} +(.+?)\s*$", re.MULTILINE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")

#: Bounds for the target chunk size an operator may pass as `chunk_chars`.
CHUNK_CHARS_MIN = 2_000
CHUNK_CHARS_MAX = 60_000
CHUNK_CHARS_DEFAULT = 12_000

#: Never plan more worker tasks than this per run, whatever the source size.
MAX_CHUNKS = 24
#: A heading section shorter than this is folded into its neighbour.
_MIN_SECTION_CHARS = 400

#: Directories never treated as macro components and never descended into.
#: Version control, virtualenvs, dependency trees and build output carry no
#: design of their own; dot-directories are tooling config, not components.
REPO_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".tox",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        "target",
        ".idea",
        ".vscode",
        ".fleet",
        ".beads",
    }
)

#: Suffixes never read into a component chunk: images, fonts, archives,
#: compiled artifacts and lockfiles (dependency pins, not design).
_REPO_BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".svg",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".whl",
        ".pyc",
        ".pyo",
        ".so",
        ".o",
        ".a",
        ".exe",
        ".dll",
        ".dylib",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".lock",
    }
)

#: Largest single file read into a chunk; bigger files are noted, not held.
_REPO_MAX_FILE_BYTES = 200_000

#: Root files folded into the overview chunk instead of their own component.
_REPO_ROOT_DOCS = frozenset(
    {
        "readme.md",
        "readme.rst",
        "readme.txt",
        "readme",
        "license",
        "license.md",
        "license.txt",
        "changelog.md",
        "contributing.md",
        "code_of_conduct.md",
        "pyproject.toml",
        "package.json",
        "cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "gemfile",
        "setup.py",
        "setup.cfg",
        "composer.json",
        "dune-project",
        "makefile",
        "justfile",
        "dockerfile",
        "docker-compose.yml",
    }
)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One contiguous piece of the source with a short human title."""

    index: int
    title: str
    text: str

    @property
    def slug(self) -> str:
        """Kebab-case file stem, e.g. `03-attention-mechanism`."""
        base = _SLUG_RE.sub("-", self.title.lower()).strip("-")[:48].strip("-") or "part"
        return f"{self.index:02d}-{base}"


def parse_chunk_chars(raw: str | None) -> int:
    """Target chunk size from the `chunk_chars` input, clamped to sane bounds."""
    if raw is None or not raw.strip():
        return CHUNK_CHARS_DEFAULT
    try:
        value = int(raw.strip())
    except ValueError:
        return CHUNK_CHARS_DEFAULT
    return max(CHUNK_CHARS_MIN, min(CHUNK_CHARS_MAX, value))


def _sections(text: str) -> list[str]:
    """Split on markdown headings when present, else on blank lines."""
    if len(_HEADING_RE.findall(text)) >= 2:  # noqa: PLR2004  # two headings = real structure
        starts = [m.start() for m in _HEADING_RE.finditer(text)]
        if starts[0] > 0:
            starts.insert(0, 0)
        pieces = [text[a:b] for a, b in zip(starts, [*starts[1:], len(text)], strict=True)]
        return [p for p in pieces if p.strip()]
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def _pack(pieces: list[str], target: int) -> list[str]:
    """Greedily join neighbouring pieces up to `target` characters each."""
    packed: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > target and len(current) >= _MIN_SECTION_CHARS:
            packed.append(current)
            current = piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        packed.append(current)
    return packed


def _split_long(piece: str, target: int) -> list[str]:
    """Cut one oversized piece at paragraph breaks so no chunk dwarfs the rest."""
    if len(piece) <= target * 2:
        return [piece]
    paragraphs = [p for p in re.split(r"\n\s*\n", piece) if p.strip()]
    if len(paragraphs) <= 1:
        return [piece]
    return _pack(paragraphs, target)


def _title_of(text: str, index: int) -> str:
    """Heading of the piece when it has one, else its first words."""
    match = _TITLE_RE.search(text)
    if match is not None:
        return match.group(1).strip("# ").strip()
    words = text.strip().split()
    return " ".join(words[:6]) if words else f"Part {index}"


def _merge_to_cap(pieces: list[str], cap: int) -> list[str]:
    """Merge neighbouring pieces pairwise until at most `cap` remain."""
    while len(pieces) > cap:
        merged: list[str] = []
        for i in range(0, len(pieces), 2):
            pair = pieces[i : i + 2]
            merged.append("\n\n".join(pair))
        pieces = merged
    return pieces


def chunk_text(text: str, target: int = CHUNK_CHARS_DEFAULT) -> list[Chunk]:
    """Cut `text` into structure-aligned chunks of roughly `target` characters."""
    body = text.strip()
    if not body:
        return []
    pieces: list[str] = []
    for section in _sections(body):
        pieces.extend(_split_long(section, target))
    packed = _merge_to_cap(_pack(pieces, target), MAX_CHUNKS)
    return [
        Chunk(index=i + 1, title=_title_of(piece, i + 1), text=piece.strip())
        for i, piece in enumerate(packed)
    ]


def _repo_files(component: Path) -> list[Path]:
    """Text files under `component`, skipping binary suffixes and oversize files."""
    found = []
    for path in sorted(component.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() in _REPO_BINARY_SUFFIXES:
            continue
        if any(part in REPO_SKIP_DIRS for part in path.parts):
            continue
        try:
            if path.stat().st_size > _REPO_MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        found.append(path)
    return found


def _repo_file_block(path: Path, anchor: Path, target: int) -> str | None:
    """One file as a headed fenced block; None when it is not readable text."""
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not text.strip():
        return None
    rel = path.relative_to(anchor).as_posix()
    lines = text.count("\n") + 1
    if len(text) > target:
        text = text[:target] + f"\n... (truncated, {len(text) - target} more characters)"
    fence = "```"
    return f"## {rel} ({lines} lines)\n\n{fence}\n{text.strip()}\n{fence}"


def _repo_component_chunk(name: str, root: Path, target: int) -> str | None:
    """Chunk body for one top-level directory; None when it holds no text."""
    blocks = []
    for path in _repo_files(root):
        block = _repo_file_block(path, root.parent, target)
        if block is not None:
            blocks.append(block)
    if not blocks:
        return None
    head = f"# Component: {name}\n\n{len(blocks)} source files.\n"
    return head + "\n\n".join(blocks)


def chunk_repo(repo: Path, target: int = CHUNK_CHARS_DEFAULT) -> list[Chunk]:
    """One chunk per macro component of a cloned repo, overview chunk first.

    Components are the repo's top-level directories (minus VCS, venvs and
    build output); root-level source files outside the doc/manifest set form
    a trailing `top-level-files` component. Every chunk keeps whole files,
    each file capped at `target` characters so one giant generated file
    cannot dwarf the rest. Always returns at least the overview chunk, so a
    wiki stage is never planned empty.
    """
    pieces: list[tuple[str, str]] = []
    entries = sorted(
        (p for p in repo.iterdir() if p.name not in REPO_SKIP_DIRS),
        key=lambda p: p.name.lower(),
    )
    for entry in entries:
        if entry.is_dir() and not entry.is_symlink():
            body = _repo_component_chunk(entry.name, entry, target)
            if body is not None:
                pieces.append((entry.name, body))
    root_files = [
        p
        for p in entries
        if p.is_file()
        and p.name.lower() not in _REPO_ROOT_DOCS
        and p.suffix.lower() not in _REPO_BINARY_SUFFIXES
    ]
    root_blocks = [
        block for path in root_files if (block := _repo_file_block(path, repo, target)) is not None
    ]
    if root_blocks:
        head = f"# Component: top-level-files\n\n{len(root_blocks)} source files.\n"
        pieces.append(("top-level-files", head + "\n\n".join(root_blocks)))
    if len(pieces) + 1 > MAX_CHUNKS:
        pieces = _merge_repo_pieces(pieces, MAX_CHUNKS - 1)
    overview = _repo_overview_chunk(repo, [name for name, _ in pieces])
    chunks = [Chunk(index=1, title="Overview", text=overview)]
    chunks += [
        Chunk(index=i + 2, title=name, text=body.strip()) for i, (name, body) in enumerate(pieces)
    ]
    return chunks


def _merge_repo_pieces(pieces: list[tuple[str, str]], cap: int) -> list[tuple[str, str]]:
    """Merge neighbouring (name, body) pairs until at most `cap` remain."""
    while len(pieces) > cap:
        merged: list[tuple[str, str]] = []
        for i in range(0, len(pieces), 2):  # noqa: PLR2004  # pairwise fold, like _merge_to_cap
            pair = pieces[i : i + 2]
            if len(pair) == 2:  # noqa: PLR2004  # a leftover single piece needs no merge
                name = f"{pair[0][0]}-and-{pair[1][0]}"
                merged.append((name, pair[0][1] + "\n\n" + pair[1][1]))
            else:
                merged.append(pair[0])
        pieces = merged
    return pieces


def _repo_overview_chunk(repo: Path, components: list[str]) -> str:
    """First chunk: what the repo is and which components follow."""
    lines = [f"# Overview: {repo.name}", ""]
    for readme in ("README.md", "README.rst", "README.txt", "README"):
        path = repo / readme
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:12_000]
            except OSError:
                text = ""
            if text.strip():
                lines += ["## README", "", text.strip(), ""]
            break
    lines += ["## Macro components", ""]
    lines += [f"- {name}/" for name in components] or ["- (no component directories)"]
    return "\n".join(lines).strip() + "\n"
