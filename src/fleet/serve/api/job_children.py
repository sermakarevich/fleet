"""Group a research/job epic's spawned children into extra run-page stages.

``workers/job.py`` writes ``tasks.json`` (the design), ``children.json`` /
``children_runs.json`` (what was spawned) and ``children_skipped.json``
(what was skipped, with why) into the epic task's artifacts dir. A
`research` run's real work — its `summarise` sub-runs and aggregation beads
— lives in those journals, invisible on the run page next to the single
epic card. This module turns the journals into the ``child_stages``
``serve/api/workflows.py`` attaches to a run: one stage per group
(`summarise`, `aggregate`), each a list of cards with a status and a link
target, matching the shape a normal workflow stage already renders.

Pure and I/O-free: callers pass parsed JSON plus small status lookups, so
this module is unit-testable without a store or queue.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

STAGE_SUMMARISE = "summarise"
STAGE_AGGREGATE = "aggregate"

#: `run_id -> status value` (e.g. a `WorkflowRun.status.value`), or None when unknown.
RunStatusLookup = Callable[[str], "str | None"]

#: `bead_id -> (title, status)`, both None when the bead is unknown.
BeadStatusLookup = Callable[[str], "tuple[str | None, str | None]"]


def _entries(tasks_json: Any) -> list[dict[str, Any]]:
    """Normalize tasks.json's list-or-``{"tasks": [...]}`` shape; bad entries drop."""
    raw = tasks_json.get("tasks") if isinstance(tasks_json, dict) else tasks_json
    if not isinstance(raw, list):
        return []
    return [
        item
        for item in raw
        if isinstance(item, dict) and isinstance(item.get("key"), str) and item["key"]
    ]


def _skip_reason(skipped: dict[str, Any], key: str) -> str | None:
    """The skip reason for *key*, coerced to text, or None when not skipped."""
    reason = skipped.get(key)
    if reason is None:
        return None
    return reason if isinstance(reason, str) else str(reason)


def _rank(key: str) -> int:
    """Stage-3 card order: topics, then aggregates, lenses, index (depends on all) last."""
    if key.startswith("topic-"):
        return 0
    if key == "agg-index":
        return 3
    if key.startswith("agg-"):
        return 1
    if key.startswith("lens-"):
        return 2
    return 4


def _summarise_item(
    entry: dict[str, Any],
    *,
    children: dict[str, Any],
    skipped: dict[str, Any],
    run_status: RunStatusLookup,
) -> dict[str, Any]:
    """One `src-NN` card: skipped, running/succeeded/etc, or not spawned yet."""
    key = entry["key"]
    title = entry.get("title") or key
    reason = _skip_reason(skipped, key)
    if reason is not None:
        return {
            "key": key,
            "title": title,
            "kind": "run",
            "ref": None,
            "status": "skipped",
            "reason": reason,
        }
    run_id = children.get(key)
    if isinstance(run_id, str) and run_id:
        return {
            "key": key,
            "title": title,
            "kind": "run",
            "ref": run_id,
            "status": run_status(run_id) or "unknown",
        }
    return {"key": key, "title": title, "kind": "run", "ref": None, "status": "pending"}


def _aggregate_item(
    entry: dict[str, Any],
    *,
    children: dict[str, Any],
    skipped: dict[str, Any],
    bead_status: BeadStatusLookup,
) -> dict[str, Any]:
    """One digest/aggregate/lens card: bead status, skipped, or not spawned yet."""
    key = entry["key"]
    fallback_title = entry.get("title") or key
    reason = _skip_reason(skipped, key)
    if reason is not None:
        return {
            "key": key,
            "title": fallback_title,
            "kind": "task",
            "ref": None,
            "status": "skipped",
            "reason": reason,
        }
    bead_id = children.get(key)
    if isinstance(bead_id, str) and bead_id:
        bead_title, status = bead_status(bead_id)
        return {
            "key": key,
            "title": bead_title or fallback_title,
            "kind": "task",
            "ref": bead_id,
            "status": status or "unknown",
        }
    return {"key": key, "title": fallback_title, "kind": "task", "ref": None, "status": "pending"}


def build_child_stages(
    tasks_json: Any,
    children: dict[str, Any],
    skipped: dict[str, Any],
    *,
    run_status: RunStatusLookup,
    bead_status: BeadStatusLookup,
) -> list[dict[str, Any]]:
    """Stage-2 (`summarise`) / stage-3 (`aggregate`) columns for a job epic.

    Returns ``[]`` when *tasks_json* has no usable task list (design not
    written yet, or an unrelated step). A group is omitted when it has no
    entries — a design with no `workflow` tasks yields no `summarise` stage.
    """
    entries = _entries(tasks_json)
    if not entries:
        return []
    summarise = [entry for entry in entries if entry.get("workflow")]
    aggregate = sorted(
        (entry for entry in entries if not entry.get("workflow")),
        key=lambda entry: _rank(entry["key"]),
    )
    stages: list[dict[str, Any]] = []
    if summarise:
        stages.append(
            {
                "title": STAGE_SUMMARISE,
                "items": [
                    _summarise_item(
                        entry, children=children, skipped=skipped, run_status=run_status
                    )
                    for entry in summarise
                ],
            }
        )
    if aggregate:
        stages.append(
            {
                "title": STAGE_AGGREGATE,
                "items": [
                    _aggregate_item(
                        entry, children=children, skipped=skipped, bead_status=bead_status
                    )
                    for entry in aggregate
                ],
            }
        )
    return stages
