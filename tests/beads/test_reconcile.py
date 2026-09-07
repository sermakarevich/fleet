from __future__ import annotations

from fleet.beads.reconcile import merge_status


def test_missing_from_beads_becomes_closed() -> None:
    task_meta = {"id": "t1", "status": "in_progress", "created_at": "2025-01-01T00:00:00Z"}
    merged = merge_status(task_meta, None)
    assert merged["status"] == "closed"
    assert merged["created_at"] == "2025-01-01T00:00:00Z"


def test_bead_status_wins() -> None:
    task_meta = {"id": "t1", "status": "in_progress", "priority": 1}
    bead = {"status": "blocked", "priority": 2, "created_at": "2025-02-01T00:00:00Z"}
    merged = merge_status(task_meta, bead)
    assert merged["status"] == "blocked"
    assert merged["priority"] == 2
    assert merged["created_at"] == "2025-02-01T00:00:00Z"


def test_created_at_never_nulled_when_bead_lacks_it() -> None:
    task_meta = {"id": "t1", "status": "open", "created_at": "2025-01-01T00:00:00Z"}
    bead = {"status": "open", "created_at": None}
    merged = merge_status(task_meta, bead)
    assert merged["created_at"] == "2025-01-01T00:00:00Z"


def test_title_and_description_backfilled_from_bead() -> None:
    task_meta = {"id": "t1", "status": "open", "title": "", "description": None}
    bead = {"status": "open", "title": "Fix bug", "description": "details"}
    merged = merge_status(task_meta, bead)
    assert merged["title"] == "Fix bug"
    assert merged["description"] == "details"


def test_existing_title_not_overwritten() -> None:
    task_meta = {"id": "t1", "status": "open", "title": "Keep me"}
    bead = {"status": "open", "title": "Other title"}
    merged = merge_status(task_meta, bead)
    assert merged["title"] == "Keep me"
