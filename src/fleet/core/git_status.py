"""Pure git-output classifiers: text in, facts out, no subprocess.

Called by ``orchestrator/worktree.py`` (and its ``GitRepo`` wrapper), which
runs git and hands the raw stdout here. Tests assert on literal
``git status --porcelain`` / ``git rev-list`` strings, never on repos.
"""

from __future__ import annotations

from dataclasses import dataclass

FLEET_SCAFFOLD_PREFIXES: tuple[str, ...] = (".claude/", ".fleet/")
"""Top-level dirs fleet writes into isolated worktrees (not worker output).

``ClaudeCoder.write_runtime_config`` drops ``.claude/settings.json`` and
``.fleet/hooks/*.sh`` into the project root. In repos that do not gitignore
them they show up as untracked in ``git status --porcelain`` and must not
count as worker dirt.
"""


_PORCELAIN_PREFIX_LEN = 3
"""``XY `` prefix width of one ``git status --porcelain`` line."""

_QUOTED_MIN_LEN = 2
"""Shortest length of a quoted porcelain path (two quote chars)."""


def _porcelain_path(line: str) -> str:
    """The path part of one ``git status --porcelain`` line (rename-aware)."""
    content = line[_PORCELAIN_PREFIX_LEN:] if len(line) > _PORCELAIN_PREFIX_LEN else ""
    content = content.strip()
    # Renames/copies: "orig -> new"; the live path is the right side.
    if " -> " in content:
        content = content.rsplit(" -> ", 1)[1].strip()
    # git quotes paths with special chars: strip one layer of quotes.
    if len(content) >= _QUOTED_MIN_LEN and content.startswith('"') and content.endswith('"'):
        content = content[1:-1]
    return content


def is_scaffold_path(path: str) -> bool:
    """True when *path* is fleet scaffolding (top-level .claude/ or .fleet/)."""
    normalized = path.lstrip("/")
    return normalized in (".claude", ".fleet") or normalized.startswith(FLEET_SCAFFOLD_PREFIXES)


def strip_scaffold_lines(porcelain_text: str) -> str:
    """Porcelain output with fleet-scaffolding lines removed."""
    kept = [
        line
        for line in porcelain_text.splitlines()
        if line.strip() and not is_scaffold_path(_porcelain_path(line))
    ]
    return "\n".join(kept) + ("\n" if kept else "")


@dataclass(frozen=True, slots=True)
class RepoStatus:
    """What ``git status --porcelain`` says about a checkout."""

    dirty: bool
    untracked: bool
    ahead: bool


def classify_status(porcelain_text: str, rev_list_text: str = "") -> RepoStatus:
    """Classify ``git status --porcelain`` output into a RepoStatus.

    Any non-blank line means dirty; a line starting with ``??`` means
    untracked files are present; *rev_list_text* (the raw
    ``git rev-list --count`` output) marks the checkout ahead when its
    count is above zero. Fleet scaffolding lines (``.claude/``, ``.fleet/``)
    are ignored: they are fleet-managed, not worker output.
    """
    filtered = strip_scaffold_lines(porcelain_text)
    dirty = bool(filtered.strip())
    untracked = any(line.startswith("??") for line in filtered.splitlines() if line.strip())
    return RepoStatus(dirty=dirty, untracked=untracked, ahead=is_ahead(rev_list_text))


def is_ahead(rev_list_text: str) -> bool:
    """True when ``git rev-list --count <base>..HEAD`` output counts above zero."""
    try:
        return int(rev_list_text.strip() or "0") > 0
    except ValueError:
        return False


def is_merge_conflict(combined_output: str, unmerged_files: str) -> bool:
    """True when a failed merge means conflict (not some other git error)."""
    if "CONFLICT" in combined_output:
        return True
    return bool(unmerged_files.strip())
