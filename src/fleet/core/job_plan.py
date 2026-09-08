"""Job-level planning policy for the observer worker. Pure: no I/O.

Two rules live here:

- ``validate_followups``: an observer's RESULT.json may declare
  ``followups: [{title, body, cwd, depends_on}]`` when the job goal is only
  partly met. This checks the list before the worker creates beads.
- ``observer_rounds``: how many observer attempts already ended `partial`,
  read from attempts.jsonl history so reap can cap follow-up rounds.
"""

from __future__ import annotations


def validate_followups(followups: object, *, max_followups: int) -> list[dict]:
    """Check an observer RESULT.json `followups` list; return normalized specs.

    Each spec keeps ``{title, body, cwd, depends_on}`` (missing keys become
    "" / [] and are defaulted from the epic by the caller). ``depends_on``
    names *sibling follow-up titles* (their bead ids don't exist yet).

    Raises ValueError when the list is not a list, exceeds *max_followups*,
    has blank/duplicate titles, has a non-list ``depends_on``, references an
    unknown sibling, depends on itself, or contains a dependency cycle.
    """
    if not isinstance(followups, list):
        raise ValueError("followups must be a list")
    if len(followups) > max_followups:
        raise ValueError(
            f"too many follow-ups ({len(followups)} > {max_followups})"
        )
    specs: list[dict] = []
    for i, item in enumerate(followups):
        if not isinstance(item, dict):
            raise ValueError(f"follow-up #{i} must be an object")
        title = str(item.get("title") or "").strip()
        if not title:
            raise ValueError(f"follow-up #{i} has a blank title")
        depends_on = item.get("depends_on") or []
        if not isinstance(depends_on, list) or not all(
            isinstance(d, str) for d in depends_on
        ):
            raise ValueError(f"follow-up {title!r}: depends_on must be a list of titles")
        specs.append(
            {
                "title": title,
                "body": str(item.get("body") or ""),
                "cwd": item.get("cwd"),
                "depends_on": list(depends_on),
            }
        )
    titles = [s["title"] for s in specs]
    if len(set(titles)) != len(titles):
        raise ValueError("follow-up titles must be unique")
    by_title = {s["title"]: s for s in specs}
    for spec in specs:
        for dep in spec["depends_on"]:
            if dep not in by_title:
                raise ValueError(
                    f"follow-up {spec['title']!r} depends on unknown {dep!r}"
                )
            if dep == spec["title"]:
                raise ValueError(
                    f"follow-up {spec['title']!r} cannot depend on itself"
                )
    _check_acyclic(specs)
    return specs


def _check_acyclic(specs: list[dict]) -> None:
    """Raise ValueError when sibling depends_on edges contain a cycle."""
    by_title = {s["title"]: s for s in specs}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(title: str, chain: list[str]) -> None:
        if title in done:
            return
        if title in visiting:
            raise ValueError(
                f"follow-up dependency cycle: {' -> '.join([*chain, title])}"
            )
        visiting.add(title)
        for dep in by_title[title]["depends_on"]:
            visit(dep, [*chain, title])
        visiting.discard(title)
        done.add(title)

    for spec in specs:
        visit(spec["title"], [])


def observer_rounds(history: list[dict]) -> int:
    """Count observer attempts in *history* that ended `partial`.

    A row counts when its outcome is "partial" and its worker is an
    observer run (``worker`` startswith "observer", or unset — rows written
    before worker tagging carry None and, on an epic bead, can only be
    observer runs). "waiting" rows never count: the observer woke early,
    it did not validate anything.
    """
    count = 0
    for entry in history:
        if not isinstance(entry, dict):
            continue
        if entry.get("outcome") != "partial":
            continue
        worker = entry.get("worker")
        if worker is None or str(worker).startswith("observer"):
            count += 1
    return count
