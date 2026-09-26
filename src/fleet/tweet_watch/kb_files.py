"""M1 kb-files: watchlist parsing and state load/save."""

from __future__ import annotations

import json
import os
import tempfile
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
    """Parse the watchlist file into handles.

    One X handle per line; blank lines and full-line ``#`` comments (even
    with leading whitespace) are ignored; surrounding whitespace is
    stripped and one leading ``@`` removed; duplicates collapse keeping
    first-occurrence order; CRLF and a UTF-8 BOM are handled. Every other
    line passes through verbatim for M2 to reject.
    """
    path = Path(watchlist_path)
    text = path.read_text(encoding="utf-8-sig")
    handles: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            line = line[1:]
            if not line:
                continue
        if line not in seen:
            seen.add(line)
            handles.append(line)
    return handles


def load_state(state_path: Path) -> dict[str, str]:
    """Load watch_state.json into a handle->id map.

    Missing file reads as ``{}``; JSON numbers are coerced via ``str()``;
    corrupt JSON, wrong top-level shape, or null/bool/list/dict values
    abort with an error naming the state path (and handle key).
    """
    path = Path(state_path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: expected object of {{handle: id-string}}, "
            f"got {type(data).__name__}"
        )
    state: dict[str, str] = {}
    for handle, value in data.items():
        if isinstance(value, str):
            state[handle] = value
        elif isinstance(value, bool) or value is None or isinstance(
            value, (list, dict)
        ):
            raise ValueError(
                f"{path}: invalid value for handle {handle!r}: "
                "expected id string"
            )
        elif isinstance(value, (int, float)):
            state[handle] = str(value)
        else:
            raise ValueError(
                f"{path}: invalid value for handle {handle!r}: "
                "expected id string"
            )
    return state


def save_state(state_path: Path, state: Mapping[str, str]) -> None:
    """Persist the handle->id map atomically via temp file plus rename."""
    path = Path(state_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"{path}: cannot create parent dir: {exc}") from exc
    try:
        if path.exists() and not os.access(path, os.W_OK):
            raise OSError(f"{path}: state file is not writable")
        payload = json.dumps(dict(state), ensure_ascii=False, indent=2) + "\n"
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(payload)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        if str(path) in str(exc):
            raise
        raise OSError(f"{path}: {exc}") from exc
