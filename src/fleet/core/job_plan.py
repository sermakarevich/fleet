"""Job-level planning policy for the observer and job workers. Pure: no I/O.

Three rules live here:

- ``validate_followups``: an observer's RESULT.json may declare
  ``followups: [{title, body, cwd, depends_on}]`` when the job goal is only
  partly met. This checks the list before the worker creates beads.
- ``validate_tasks``: a job's artifacts/tasks.json declares
  ``{tasks: [{key, title, body, cwd, coder, model, priority,
  depends_on}]}``. Returns a list of error strings (empty when valid) so
  the spawn step can write them to DESIGN_ERRORS.md and send the job back
  to design.
- ``observer_rounds``: how many observer attempts already ended `partial`,
  read from attempts.jsonl history so reap can cap follow-up rounds.
"""

from __future__ import annotations

from fleet.core.errors import Json, PlanError

_TITLE_MAX_LEN = 120  # follow-up titles longer than this are rejected


def validate_followups(followups: Json, *, max_followups: int) -> list[dict]:
    """Check an observer RESULT.json `followups` list; return normalized specs.

    Each spec keeps ``{title, body, cwd, depends_on}`` (missing keys become
    "" / [] and are defaulted from the epic by the caller). ``depends_on``
    names *sibling follow-up titles* (their bead ids don't exist yet).

    Raises PlanError when the list is not a list, exceeds *max_followups*,
    has blank/duplicate titles, has a non-list ``depends_on``, references an
    unknown sibling, depends on itself, or contains a dependency cycle.
    """
    if not isinstance(followups, list):
        raise PlanError("followups must be a list")
    if len(followups) > max_followups:
        raise PlanError(f"too many follow-ups ({len(followups)} > {max_followups})")
    specs: list[dict] = []
    for i, item in enumerate(followups):
        if not isinstance(item, dict):
            raise PlanError(f"follow-up #{i} must be an object")
        title = str(item.get("title") or "").strip()
        if not title:
            raise PlanError(f"follow-up #{i} has a blank title")
        depends_on = item.get("depends_on") or []
        if not isinstance(depends_on, list) or not all(isinstance(d, str) for d in depends_on):
            raise PlanError(f"follow-up {title!r}: depends_on must be a list of titles")
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
        raise PlanError("follow-up titles must be unique")
    by_title = {s["title"]: s for s in specs}
    for spec in specs:
        for dep in spec["depends_on"]:
            if dep not in by_title:
                raise PlanError(f"follow-up {spec['title']!r} depends on unknown {dep!r}")
            if dep == spec["title"]:
                raise PlanError(f"follow-up {spec['title']!r} cannot depend on itself")
    _check_acyclic(specs)
    return specs


def _check_acyclic(specs: list[dict]) -> None:
    """Raise PlanError when sibling depends_on edges contain a cycle."""
    by_title = {s["title"]: s for s in specs}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(title: str, chain: list[str]) -> None:
        if title in done:
            return
        if title in visiting:
            raise PlanError(f"follow-up dependency cycle: {' -> '.join([*chain, title])}")
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
    observer run (``worker`` startswith "observer" or "job.observe", or
    unset — rows written before worker tagging carry None and, on an epic
    bead, can only be observer runs). "waiting" rows never count: the
    observer woke early, it did not validate anything.
    """
    count = 0
    for entry in history:
        if not isinstance(entry, dict):
            continue
        if entry.get("outcome") != "partial":
            continue
        worker = entry.get("worker")
        if worker is None or str(worker).startswith(("observer", "job.observe")):
            count += 1
    return count


def validate_tasks(doc: Json, max_children: int = 30) -> list[str]:  # noqa: PLR0912  # ADR 0006 bead 5
    """Check a parsed tasks.json doc; return error strings (empty when valid).

    Expected shape: ``{"tasks": [{key, title, body, cwd, coder, model,
    priority, depends_on}]}`` where ``depends_on`` names sibling *keys*.
    Errors: doc not an object, tasks not a list, empty list, too many
    tasks, blank/duplicate keys, title blank or > 120 chars, body blank,
    depends_on not a list of strings, unknown/self dependencies, cycles.
    """
    if not isinstance(doc, dict):
        return ["tasks.json must be an object with a 'tasks' list"]
    tasks = doc.get("tasks")
    if not isinstance(tasks, list):
        return ["tasks.json must be an object with a 'tasks' list"]
    if not tasks:
        return ["tasks list must not be empty"]
    if len(tasks) > max_children:
        return [f"too many tasks ({len(tasks)} > {max_children})"]
    errors: list[str] = []
    specs: list[dict] = []
    for i, item in enumerate(tasks):
        if not isinstance(item, dict):
            errors.append(f"task #{i} must be an object")
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            errors.append(f"task #{i} has a blank key")
            key = f"#{i}"
        title = str(item.get("title") or "").strip()
        if not title:
            errors.append(f"task {key!r} has a blank title")
        elif len(title) > _TITLE_MAX_LEN:
            errors.append(f"task {key!r} title exceeds {_TITLE_MAX_LEN} chars")
        body = str(item.get("body") or "").strip()
        if not body:
            errors.append(f"task {key!r} has a blank body")
        depends_on = item.get("depends_on") or []
        if not isinstance(depends_on, list) or not all(isinstance(d, str) for d in depends_on):
            errors.append(f"task {key!r}: depends_on must be a list of keys")
            depends_on = []
        specs.append({"key": key, "depends_on": list(depends_on)})
    keys = [s["key"] for s in specs]
    if len(set(keys)) != len(keys):
        errors.append("task keys must be unique")
    by_key = {s["key"]: s for s in specs}
    for spec in specs:
        for dep in spec["depends_on"]:
            if dep not in by_key:
                errors.append(f"task {spec['key']!r} depends on unknown {dep!r}")
            elif dep == spec["key"]:
                errors.append(f"task {spec['key']!r} cannot depend on itself")
    if not errors:
        try:
            _check_tasks_acyclic(specs)
        except PlanError as exc:
            errors.append(str(exc))
    return errors


def _check_tasks_acyclic(specs: list[dict]) -> None:
    """Raise PlanError when sibling key depends_on edges contain a cycle."""
    by_key = {s["key"]: s for s in specs}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(key: str, chain: list[str]) -> None:
        if key in done:
            return
        if key in visiting:
            raise PlanError(f"task dependency cycle: {' -> '.join([*chain, key])}")
        visiting.add(key)
        for dep in by_key[key]["depends_on"]:
            visit(dep, [*chain, key])
        visiting.discard(key)
        done.add(key)

    for spec in specs:
        visit(spec["key"], [])
