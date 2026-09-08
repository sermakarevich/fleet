"""Epic claim rule: open epics with terminal children are claimable.

`bd ready` never lists an epic with a `blocked` child (beads only marks an
issue ready when every dependency closed), so BeadsQueue.claim_next falls
back to scanning open epics via beads/client.children_of +
core/job_ready.children_terminal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.beads.queue import BeadsQueue


class FakeBd:
    """Stand-in for BeadsQueue._bd: canned ready/open/show, recorded claims."""

    def __init__(
        self,
        *,
        ready: list | None = None,
        open_issues: list | None = None,
        shows: dict | None = None,
    ) -> None:
        self.ready = ready or []
        self.open_issues = open_issues or []
        self.shows = shows or {}
        self.claimed: list[str] = []
        self.deps_added: list[tuple[str, str]] = []
        self.created: list[dict] = []

    def __call__(self, *args: str, json_envelope: bool = True, actor=None):
        if args[0] == "ready":
            return {"data": self.ready}
        if args[0] == "list":
            return {"data": self.open_issues}
        if args[0] == "show":
            body = self.shows.get(args[1], {})
            return {"data": dict(body)}
        if args[0] == "update":
            self.claimed.append(args[1])
            return None
        if args[0] == "create":
            new_id = f"kid-{len(self.created) + 1}"
            title = args[args.index("--title") + 1] if "--title" in args else new_id
            self.created.append({"id": new_id, "title": title})
            return {"data": {"id": new_id, "title": title, "status": "open"}}
        if args[0] == "dep":
            self.deps_added.append((args[2], args[3]))
            return None
        raise AssertionError(f"unexpected bd call: {args}")


def _queue(tmp_path: Path, fake: FakeBd) -> BeadsQueue:
    q = BeadsQueue(tmp_path)
    q._bd = fake  # type: ignore[method-assign]
    return q


def _epic_row(epic_id: str = "epic-1") -> dict:
    return {
        "id": epic_id,
        "title": "Epic",
        "status": "open",
        "issue_type": "epic",
        "priority": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "metadata": {},
    }


def _terminal_children(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fleet.beads.client.children_of",
        lambda epic_id, cwd: [
            {"id": "c-1", "status": "closed"},
            {"id": "c-2", "status": "blocked"},
        ],
    )


def test_epic_with_terminal_children_claimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _terminal_children(monkeypatch)
    fake = FakeBd(ready=[], open_issues=[_epic_row()])
    q = _queue(tmp_path, fake)
    task = q.claim_next("supervisor")
    assert task is not None
    assert task.id == "epic-1"
    assert task.type == "epic"
    assert fake.claimed == ["epic-1"]


def test_epic_with_running_child_not_claimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "fleet.beads.client.children_of",
        lambda epic_id, cwd: [
            {"id": "c-1", "status": "closed"},
            {"id": "c-2", "status": "in_progress"},
        ],
    )
    fake = FakeBd(ready=[], open_issues=[_epic_row()])
    q = _queue(tmp_path, fake)
    assert q.claim_next("supervisor") is None
    assert fake.claimed == []


def test_epic_without_children_not_claimed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fleet.beads.client.children_of", lambda epic_id, cwd: [])
    fake = FakeBd(ready=[], open_issues=[_epic_row()])
    q = _queue(tmp_path, fake)
    assert q.claim_next("supervisor") is None
    assert fake.claimed == []


def test_ready_item_wins_over_epic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _terminal_children(monkeypatch)
    ready_row = {
        "id": "t-9",
        "title": "Task",
        "status": "open",
        "priority": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "metadata": {},
    }
    fake = FakeBd(ready=[ready_row], open_issues=[_epic_row()])
    q = _queue(tmp_path, fake)
    task = q.claim_next("supervisor")
    assert task is not None
    assert task.id == "t-9"
    assert fake.claimed == ["t-9"]


def test_create_child_links_epic_and_inherits_setup(tmp_path: Path) -> None:
    epic_body = {
        "id": "epic-1",
        "title": "Epic",
        "status": "in_progress",
        "issue_type": "epic",
        "metadata": {"fleet_coder": "claude", "fleet_model": "opus", "fleet_cwd": "/repo"},
    }
    fake = FakeBd(shows={"epic-1": epic_body, "kid-1": {"id": "kid-1", "title": "a"}})
    q = _queue(tmp_path, fake)
    child = q.create_child("epic-1", {"title": "a", "body": "do a", "cwd": None, "depends_on": []})
    assert child.id == "kid-1"
    assert child.coder == "claude"
    assert child.model == "opus"
    assert child.cwd == "/repo"
    # The epic gains a dependency on the child, so it sleeps until it closes.
    assert ("epic-1", "kid-1") in fake.deps_added
