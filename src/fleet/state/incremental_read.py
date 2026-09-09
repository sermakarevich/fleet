"""Read bytes appended to a growing file since a byte offset.

The one increment-read primitive behind both `fleet tail --follow` (cli) and
the websocket event streamer (serve/event_stream.py) — each has its own idea of
what to do with the new bytes, but both need "what's new since I last looked."
"""

from __future__ import annotations

from pathlib import Path


def read_new_bytes(path: Path, offset: int) -> tuple[bytes, int]:
    """Return (new_bytes, new_offset). Returns (b"", offset) if nothing changed or unreadable."""
    try:
        size = path.stat().st_size
    except OSError:
        return b"", offset
    if size <= offset:
        return b"", offset
    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except OSError:
        return b"", offset
    return data, offset + len(data)
