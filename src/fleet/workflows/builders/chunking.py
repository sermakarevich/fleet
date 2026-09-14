"""Split fetched source text into chapter-sized chunks along its own structure.

Called by `builders/summary_get.py`. Pure text in, list of chunks out: the
text is cut at markdown headings when it has them, else at blank lines,
and neighbouring pieces are packed greedily up to a target size so every
chunk is a whole section (or a run of whole paragraphs), never a cut mid
sentence. Chunk count is capped so a very long source still yields a
workable number of worker tasks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
        raise ValueError(f"chunk_chars: {raw!r} is not an integer") from None
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
