"""Tests for `serve/api/job_children.py`: grouping a job epic's children.

Covers the pure `build_child_stages` function: a design with `src-NN`
summarise tasks plus `topic-*`/`agg-*`/`lens-*` aggregate tasks groups into
`summarise` and `aggregate` stages with the right kind/status/order; a
skipped source gets a `skipped` card with its reason; a task not yet spawned
gets a `pending` card; and a design with no tasks.json yields no stages.
"""

from __future__ import annotations

from fleet.serve.api import job_children

_TASKS = {
    "tasks": [
        {"key": "src-01", "title": "summarise: Paper One", "workflow": "summarise"},
        {"key": "src-02", "title": "summarise: Paper Two", "workflow": "summarise"},
        {"key": "src-03", "title": "summarise: Paper Three", "workflow": "summarise"},
        {"key": "topic-01", "title": "digest: code-generation"},
        {"key": "agg-digest", "title": "digest.md"},
        {"key": "agg-index", "title": "index.md"},
        {"key": "lens-tech", "title": "lenses/tech.md"},
    ]
}


def _no_run_status(run_id: str) -> str | None:
    return None


def _no_bead_status(bead_id: str) -> tuple[str | None, str | None]:
    return None, None


def test_missing_tasks_json_yields_no_stages() -> None:
    """A step with no design (not a job epic, or not spawned yet) shows nothing."""
    assert job_children.build_child_stages(
        None, {}, {}, run_status=_no_run_status, bead_status=_no_bead_status
    ) == []
    assert job_children.build_child_stages(
        {}, {}, {}, run_status=_no_run_status, bead_status=_no_bead_status
    ) == []


def test_groups_summarise_and_aggregate_with_correct_order_and_status() -> None:
    """src-* -> summarise stage; topic/agg/lens -> aggregate stage, index last."""
    children = {
        "src-02": "wfr-child2",
        "src-03": "wfr-child3",
        "topic-01": "fleet-topic1",
        "agg-digest": "fleet-digest",
        "agg-index": "fleet-index",
        "lens-tech": "fleet-lens",
    }
    skipped = {"src-01": "HTTP Error 406: Not Acceptable"}

    def run_status(run_id: str) -> str | None:
        return {"wfr-child2": "succeeded", "wfr-child3": "running"}.get(run_id)

    def bead_status(bead_id: str) -> tuple[str | None, str | None]:
        titles = {
            "fleet-topic1": ("digest: code-generation", "closed"),
            "fleet-digest": ("digest.md", "open"),
            "fleet-index": ("index.md", "open"),
            "fleet-lens": ("lenses/tech.md", "closed"),
        }
        return titles.get(bead_id, (None, None))

    stages = job_children.build_child_stages(
        _TASKS, children, skipped, run_status=run_status, bead_status=bead_status
    )

    assert [stage["title"] for stage in stages] == ["summarise", "aggregate"]

    summarise = stages[0]["items"]
    assert summarise == [
        {
            "key": "src-01",
            "title": "summarise: Paper One",
            "kind": "run",
            "ref": None,
            "status": "skipped",
            "reason": "HTTP Error 406: Not Acceptable",
        },
        {
            "key": "src-02",
            "title": "summarise: Paper Two",
            "kind": "run",
            "ref": "wfr-child2",
            "status": "succeeded",
        },
        {
            "key": "src-03",
            "title": "summarise: Paper Three",
            "kind": "run",
            "ref": "wfr-child3",
            "status": "running",
        },
    ]

    aggregate = stages[1]["items"]
    assert [item["key"] for item in aggregate] == [
        "topic-01",
        "agg-digest",
        "lens-tech",
        "agg-index",
    ]
    assert aggregate[0] == {
        "key": "topic-01",
        "title": "digest: code-generation",
        "kind": "task",
        "ref": "fleet-topic1",
        "status": "closed",
    }


def test_not_yet_spawned_child_is_pending() -> None:
    """A design entry with no children.json / children_skipped.json entry is pending."""
    stages = job_children.build_child_stages(
        _TASKS, {}, {}, run_status=_no_run_status, bead_status=_no_bead_status
    )
    summarise_statuses = {item["key"]: item["status"] for item in stages[0]["items"]}
    aggregate_statuses = {item["key"]: item["status"] for item in stages[1]["items"]}
    assert summarise_statuses == {"src-01": "pending", "src-02": "pending", "src-03": "pending"}
    assert aggregate_statuses == {
        "topic-01": "pending",
        "agg-digest": "pending",
        "agg-index": "pending",
        "lens-tech": "pending",
    }


def test_design_with_only_summarise_tasks_has_no_aggregate_stage() -> None:
    """A design with no non-workflow tasks yields no `aggregate` stage."""
    tasks = {"tasks": [{"key": "src-01", "title": "summarise: Only One", "workflow": "summarise"}]}
    stages = job_children.build_child_stages(
        tasks, {}, {}, run_status=_no_run_status, bead_status=_no_bead_status
    )
    assert [stage["title"] for stage in stages] == ["summarise"]


def test_unknown_run_or_bead_reports_unknown_status() -> None:
    """A journaled run/bead id the store or queue never saw reports `unknown`."""
    children = {"src-01": "wfr-vanished"}
    tasks = {"tasks": [{"key": "src-01", "title": "summarise: X", "workflow": "summarise"}]}
    stages = job_children.build_child_stages(
        tasks, children, {}, run_status=_no_run_status, bead_status=_no_bead_status
    )
    assert stages[0]["items"][0]["status"] == "unknown"


def test_plain_list_tasks_json_shape_also_works() -> None:
    """tasks.json may be a bare list instead of `{"tasks": [...]}`."""
    tasks = [{"key": "src-01", "title": "summarise: X", "workflow": "summarise"}]
    stages = job_children.build_child_stages(
        tasks, {}, {}, run_status=_no_run_status, bead_status=_no_bead_status
    )
    assert [stage["title"] for stage in stages] == ["summarise"]
