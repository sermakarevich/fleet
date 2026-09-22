"""Load ``~/.env`` into the process environment for daemons started by launchd.

Interactive shells source ``~/.env`` from ``.zshrc``, so a supervisor started
from a terminal inherits every key in it (``TYPESAFE_API_KEY`` for jev,
``TWITTERAPI_IO_KEY`` for the x CLI, ...). launchd does not run a shell, so a
supervisor it restarts after a reboot or crash would lack them and research
jobs would block on the missing jev key. Loading the file here makes both
start paths equivalent.

Rules: only ``KEY=value`` and ``export KEY=value`` lines are read; blank lines
and ``#`` comments are skipped; single or double quotes around the value are
stripped; keys already present in the environment are never overridden.
"""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from pathlib import Path

_QUOTED_MIN_LEN = 2
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def parse_env_file(text: str) -> dict[str, str]:
    """Return the ``KEY -> value`` pairs in a shell-style env file."""
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if match is None:
            continue
        key, value = match.group(1), match.group(2)
        if len(value) >= _QUOTED_MIN_LEN and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        found[key] = value
    return found


def load_home_env(
    path: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> list[str]:
    """Merge ``~/.env`` into ``environ`` without overriding existing keys.

    Returns the names of the keys that were added. A missing or unreadable
    file adds nothing.
    """
    env_path = path if path is not None else Path.home() / ".env"
    target = environ if environ is not None else os.environ
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return []
    added: list[str] = []
    for key, value in parse_env_file(text).items():
        if key not in target:
            target[key] = value
            added.append(key)
    return added
