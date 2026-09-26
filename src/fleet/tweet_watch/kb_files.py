"""M1 kb-files: watchlist parsing and state load/save (scaffold)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

SEED_HANDLES: tuple[str, ...] = (
    "omarsar0",
    "typesafeai",
    "cloneisjun",
    "goodhartproof",
    "SakanaAILabs",
)


def read_watchlist(watchlist_path: Path) -> list[str]:
    """SCAFFOLD (not implemented): parse the watchlist file into handles.

    Must do: read one X handle per line, ignoring blank lines and full-line
    ``#`` comments (even with leading whitespace), stripping surrounding
    whitespace and one leading ``@``; dedupe keeping first-occurrence order;
    handle CRLF and a UTF-8 BOM. Passes every other line through verbatim.
    Serves: M1, needed by R1, R2, R6.
    Depends on: nothing (stdlib only).
    Depended on by: worker.ensure_watchlist.
    """
    raise NotImplementedError


def load_state(state_path: Path) -> dict[str, str]:
    """SCAFFOLD (not implemented): load watch_state.json into a handle->id map.

    Must do: missing file reads as ``{}``; ids round-trip verbatim as
    strings (JSON numbers coerced via ``str()``); corrupt JSON, wrong
    top-level shape, or null/bool/list/dict values abort with an error
    naming the state path (and handle key); never silently reset to ``{}``.
    Serves: M1, needed by R1, R2, R6.
    Depends on: nothing (stdlib only).
    Depended on by: worker.find_new_tweets.
    """
    raise NotImplementedError


def save_state(state_path: Path, state: Mapping[str, str]) -> None:
    """SCAFFOLD (not implemented): persist the handle->id map atomically.

    Must do: create missing parent dirs (``mkdir -p``); write via temp file
    plus rename so readers never see a half-written file; preserve entries
    for handles no longer in the watchlist; on write failure raise an error
    naming the state path without advancing anything.
    Serves: M1, needed by R1, R2, R6.
    Depends on: nothing (stdlib only).
    Depended on by: worker.find_new_tweets.
    """
    raise NotImplementedError
